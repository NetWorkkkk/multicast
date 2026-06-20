import struct
import time

from RtpPacket import RtpPacket


RTP_PAYLOAD_TYPE_MJPEG = 26
DEFAULT_MCAST_GROUP = "239.255.42.99"
DEFAULT_MCAST_PORT = 5004
DEFAULT_INTERFACE = "0.0.0.0"
DEFAULT_TTL = 1
FRAME_INTERVAL_SECONDS = 0.05
MAX_DATAGRAM_SIZE = 1400
FRAGMENT_HEADER = struct.Struct("!HH")
GRID_N = 8
GRID_M = 8
NUM_TILES = GRID_N * GRID_M
MIN_TILES_TO_RENDER = (NUM_TILES + 1) * 3 // 4


def make_multicast_rtp(payload, packet_seq, frame_number, fragment_index, marker, timestamp):
	"""Build one RTP packet for a multicast MJPEG frame fragment."""
	rtp_payload = FRAGMENT_HEADER.pack(frame_number & 0xFFFF, fragment_index & 0xFFFF) + payload
	packet = RtpPacket()
	packet.encode(
		2,
		0,
		0,
		0,
		packet_seq & 0xFFFF,
		marker,
		RTP_PAYLOAD_TYPE_MJPEG,
		frame_number & 0xFFFFFFFF,
		rtp_payload,
		timestamp=timestamp,
	)
	return packet.getPacket()


def frame_timestamp(frame_number):
	"""Use a stable per-frame RTP timestamp, not wall-clock seconds."""
	return frame_number & 0xFFFFFFFF


def monotonic_ms():
	return int(time.monotonic() * 1000)


class MulticastTileReassembler:
	"""Collect independently encoded frame tiles.

	Packet loss is handled as a missing tile, not a corrupted whole frame.
	A frame is closed when all tiles arrive or when the next frame starts.
	"""

	def __init__(self):
		self.last_completed_timestamp = None
		self.reset()

	def reset(self):
		self.current_timestamp = None
		self.current_frame_number = None
		self.current_tiles = {}

	def push(self, data):
		packet = RtpPacket()
		try:
			packet.decode(data)
			payload = packet.getPayload()
			frame_number, tile_index = FRAGMENT_HEADER.unpack(payload[:FRAGMENT_HEADER.size])
			tile = payload[FRAGMENT_HEADER.size:]
		except Exception:
			return None

		timestamp = packet.timestamp()
		if timestamp == self.last_completed_timestamp:
			return None

		closed = None
		if self.current_timestamp is None:
			self.current_timestamp = timestamp
			self.current_frame_number = frame_number
		elif self.current_timestamp != timestamp:
			closed = self._close_current()
			self.current_timestamp = timestamp
			self.current_frame_number = frame_number
			self.current_tiles = {}

		if 0 <= tile_index < NUM_TILES:
			self.current_tiles[tile_index] = tile

		if len(self.current_tiles) == NUM_TILES or packet.marker():
			complete = self._close_current()
			return complete or closed
		return closed

	def _close_current(self):
		if self.current_timestamp is None:
			return None
		timestamp = self.current_timestamp
		frame_number = self.current_frame_number
		tiles = self.current_tiles
		self.reset()

		if len(tiles) < MIN_TILES_TO_RENDER:
			return None
		self.last_completed_timestamp = timestamp
		return frame_number, tiles
