import argparse
from io import BytesIO
import socket
import threading
import time
try:
	from tkinter import *
	from tkinter import messagebox
except ModuleNotFoundError:
	Tk = None
	messagebox = None

from MulticastCommon import (
	DEFAULT_INTERFACE,
	DEFAULT_MCAST_GROUP,
	DEFAULT_MCAST_PORT,
	DEFAULT_TTL,
	FRAME_INTERVAL_SECONDS,
	GRID_M,
	GRID_N,
	NUM_TILES,
	frame_timestamp,
	make_multicast_rtp,
)
from PIL import Image
from VideoStream import VideoStream


class MulticastVideoServer:
	def __init__(self, filename, group, port, interface, ttl):
		self.filename = filename
		self.group = group
		self.port = int(port)
		self.interface = interface
		self.ttl = int(ttl)
		self.destination = (self.group, self.port)
		self.packet_seq = 0
		self.frame_number = 0
		self.running = threading.Event()
		self.shutdown = threading.Event()
		self.lock = threading.Lock()
		self.sock = self._create_socket()
		self.stream = VideoStream(self.filename)
		self.worker = threading.Thread(target=self._send_loop, daemon=True)
		self.worker.start()

	def _create_socket(self):
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
		sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.ttl)
		if self.interface != DEFAULT_INTERFACE:
			sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self.interface))
		return sock

	def play(self):
		self.running.set()

	def pause(self):
		self.running.clear()

	def stop(self):
		self.shutdown.set()
		self.running.set()
		self.worker.join(timeout=1.0)
		try:
			self.sock.close()
		except OSError:
			pass
		try:
			self.stream.file.close()
		except Exception:
			pass

	def _next_frame(self):
		frame = self.stream.nextFrame()
		if frame:
			return frame
		self.stream.reset()
		return self.stream.nextFrame()

	def _send_loop(self):
		while not self.shutdown.is_set():
			if not self.running.wait(timeout=0.2):
				continue
			frame = self._next_frame()
			if not frame:
				time.sleep(FRAME_INTERVAL_SECONDS)
				continue

			self.frame_number = self.stream.frameNbr()
			timestamp = frame_timestamp(self.frame_number)
			tiles = list(self._split_frame_tiles(frame))
			with self.lock:
				for index, tile in tiles:
					marker = 1 if index == NUM_TILES - 1 else 0
					packet = make_multicast_rtp(
						tile,
						self.packet_seq,
						self.frame_number,
						index,
						marker,
						timestamp,
					)
					self.sock.sendto(packet, self.destination)
					self.packet_seq = (self.packet_seq + 1) & 0xFFFF
			time.sleep(FRAME_INTERVAL_SECONDS)

	def _split_frame_tiles(self, jpeg_bytes):
		"""Split an MJPEG frame into GRID_N x GRID_M JPEG tiles."""
		img = Image.open(BytesIO(jpeg_bytes)).convert("RGB")
		width, height = img.size
		tile_width = width // GRID_N
		tile_height = height // GRID_M
		for index in range(NUM_TILES):
			col = index % GRID_N
			row = index // GRID_N
			box = (
				col * tile_width,
				row * tile_height,
				(col + 1) * tile_width,
				(row + 1) * tile_height,
			)
			tile = img.crop(box)
			buffer = BytesIO()
			tile.save(buffer, format="JPEG")
			yield index, buffer.getvalue()


class ServerApp:
	def __init__(self, master, server):
		self.master = master
		self.server = server
		self.master.title("Multicast Video Server")
		self.master.protocol("WM_DELETE_WINDOW", self.close)
		self._build()
		self._tick()

	def _build(self):
		self.master.configure(bg="#f4f6f8", padx=14, pady=14)
		Label(self.master, text="Multicast Video Server", bg="#f4f6f8", fg="#111827",
			  font=("Trebuchet MS", 16, "bold")).grid(row=0, column=0, columnspan=2, sticky=W)
		self.status = Label(self.master, text="", bg="#f4f6f8", fg="#475569", font=("Trebuchet MS", 11))
		self.status.grid(row=1, column=0, columnspan=2, sticky=W, pady=(6, 14))

		self.play_btn = Button(self.master, text="Play", command=self.server.play, bg="#0a9396",
							   fg="white", activebackground="#005f73", bd=0, padx=24, pady=10)
		self.play_btn.grid(row=2, column=0, sticky=E + W, padx=(0, 6))
		self.pause_btn = Button(self.master, text="Pause", command=self.server.pause, bg="#64748b",
								fg="white", activebackground="#475569", bd=0, padx=24, pady=10)
		self.pause_btn.grid(row=2, column=1, sticky=E + W, padx=(6, 0))

	def _tick(self):
		state = "Streaming" if self.server.running.is_set() else "Paused"
		self.status.configure(
			text=f"{state} | {self.server.filename} -> {self.server.group}:{self.server.port} | frame {self.server.frame_number}"
		)
		self.master.after(250, self._tick)

	def close(self):
		if messagebox.askokcancel("Quit", "Stop multicast server?"):
			self.server.stop()
			self.master.destroy()


def run_cli(server):
	print(f"Multicast server: {server.filename} -> {server.group}:{server.port}")
	print("Commands: play, pause, status, quit")
	try:
		while not server.shutdown.is_set():
			try:
				command = input("server> ").strip().lower()
			except EOFError:
				break
			except KeyboardInterrupt:
				print()
				break

			if command in ("play", "p"):
				server.play()
				print("Streaming")
			elif command in ("pause", "pa"):
				server.pause()
				print("Paused")
			elif command in ("status", "s"):
				state = "Streaming" if server.running.is_set() else "Paused"
				print(f"{state} | frame {server.frame_number}")
			elif command in ("quit", "exit", "q"):
				break
			elif command == "":
				continue
			else:
				print("Unknown command. Use: play, pause, status, quit")
	finally:
		server.stop()
		print("Server stopped")


def parse_args():
	parser = argparse.ArgumentParser(description="Multicast MJPEG/RTP video server")
	parser.add_argument("filename", nargs="?", default="movie.Mjpeg")
	parser.add_argument("--group", default=DEFAULT_MCAST_GROUP)
	parser.add_argument("--port", type=int, default=DEFAULT_MCAST_PORT)
	parser.add_argument("--interface", default=DEFAULT_INTERFACE)
	parser.add_argument("--ttl", type=int, default=DEFAULT_TTL)
	parser.add_argument("--autoplay", action="store_true")
	parser.add_argument("--no-gui", action="store_true", help="run server in terminal mode")
	return parser.parse_args()


def main():
	args = parse_args()
	server = MulticastVideoServer(args.filename, args.group, args.port, args.interface, args.ttl)
	if args.autoplay:
		server.play()
	if args.no_gui:
		run_cli(server)
		return
	if Tk is None:
		print("tkinter is not installed. Install python3-tk to run the server GUI, or use --no-gui.")
		server.stop()
		return
	root = Tk()
	ServerApp(root, server)
	root.mainloop()


if __name__ == "__main__":
	main()
