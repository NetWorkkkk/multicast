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
RTP_HEADER_SIZE = 12
MAX_RTP_PAYLOAD_SIZE = MAX_DATAGRAM_SIZE - RTP_HEADER_SIZE
MAX_FRAGMENT_DATA_SIZE = MAX_RTP_PAYLOAD_SIZE - FRAGMENT_HEADER.size


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


def split_frame(frame_bytes):
	"""Yield frame payload fragments sized safely for UDP multicast."""
	for offset in range(0, len(frame_bytes), MAX_FRAGMENT_DATA_SIZE):
		yield frame_bytes[offset:offset + MAX_FRAGMENT_DATA_SIZE]


def frame_timestamp(frame_number):
	"""Use a stable per-frame RTP timestamp, not wall-clock seconds."""
	return frame_number & 0xFFFFFFFF


def monotonic_ms():
	return int(time.monotonic() * 1000)


class MulticastFrameReassembler:
	"""Reassemble one fragmented RTP/MJPEG frame at a time.

	If a packet sequence gap is detected, the current frame is discarded and
	the reassembler waits for the next RTP timestamp.
	"""

	def __init__(self):
		self.last_completed_timestamp = None
		self.reset()

	def reset(self):
		self.current_timestamp = None
		self.expected_seq = None
		self.current_fragments = {}
		self.current_bad = False

	def push(self, data):
		packet = RtpPacket()
		try:
			packet.decode(data)
			payload = packet.getPayload()
			frame_number, fragment_index = FRAGMENT_HEADER.unpack(payload[:FRAGMENT_HEADER.size])
			fragment = payload[FRAGMENT_HEADER.size:]
		except Exception:
			return None

		timestamp = packet.timestamp()
		seq = packet.seqNum()
		if self.current_timestamp != timestamp:
			self.current_timestamp = timestamp
			self.expected_seq = seq
			self.current_fragments = {}
			self.current_bad = False

		if self.current_bad:
			return None

		if self.expected_seq is not None and seq != self.expected_seq:
			self.current_bad = True
			self.current_fragments = {}
			return None

		self.expected_seq = (seq + 1) & 0xFFFF
		self.current_fragments[fragment_index] = fragment

		if not packet.marker():
			return None

		if self.current_bad or not self.current_fragments:
			self.reset()
			return None

		try:
			frame = b"".join(self.current_fragments[idx] for idx in sorted(self.current_fragments))
		except Exception:
			self.reset()
			return None

		self.reset()
		if timestamp == self.last_completed_timestamp:
			return None
		self.last_completed_timestamp = timestamp
		return frame_number, frame
