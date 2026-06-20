import argparse
import io
import queue
import socket
import struct
import threading
try:
	from tkinter import *
	from tkinter import messagebox
except ModuleNotFoundError:
	Tk = None
	messagebox = None

from PIL import Image
try:
	from PIL import ImageTk
except ImportError:
	ImageTk = None

from MulticastCommon import (
	DEFAULT_INTERFACE,
	DEFAULT_MCAST_GROUP,
	DEFAULT_MCAST_PORT,
	GRID_N,
	GRID_M,
	MAX_DATAGRAM_SIZE,
	NUM_TILES,
	MulticastTileReassembler,
	monotonic_ms,
)


class MulticastVideoClient:
	def __init__(self, master, group, port, interface):
		self.master = master
		self.group = group
		self.port = int(port)
		self.interface = interface
		self.sock = None
		self.joined = False
		self.listen_thread = None
		self.stop_event = threading.Event()
		self.frame_queue = queue.Queue(maxsize=100)
		self.render_tick_ms = 50
		self.default_width = 640
		self.last_packet_ms = 0
		self.reassembler = MulticastTileReassembler()
		self.last_tiles = {}

		self.master.title("Multicast Video Client")
		self.master.protocol("WM_DELETE_WINDOW", self.close)
		self._build()
		self.master.after(self.render_tick_ms, self._render_tick)
		self.master.after(300, self._waiting_tick)

	def _build(self):
		self.master.configure(bg="#f4f6f8", padx=12, pady=12)
		self.master.grid_rowconfigure(0, weight=1)
		self.master.grid_columnconfigure(0, weight=1)

		self.video_frame = Frame(self.master, bg="#ffffff", bd=1, relief=RIDGE)
		self.video_frame.grid(row=0, column=0, sticky=N + S + E + W)
		self.video_frame.grid_rowconfigure(0, weight=1)
		self.video_frame.grid_columnconfigure(0, weight=1)
		self.label = Label(
			self.video_frame,
			text="Leave",
			bg="#0f172a",
			fg="#e5e7eb",
			font=("Trebuchet MS", 16, "bold"),
		)
		self.label.grid(row=0, column=0, sticky=N + S + E + W, padx=8, pady=8)

		self.controls = Frame(self.master, bg="#f4f6f8")
		self.controls.grid(row=1, column=0, sticky=E + W, pady=(10, 0))
		self.controls.grid_columnconfigure(0, weight=1)
		self.controls.grid_columnconfigure(1, weight=1)
		self.join_btn = Button(self.controls, text="Join Multicast", command=self.join_group,
							   bg="#0a9396", fg="white", activebackground="#005f73",
							   activeforeground="white", bd=0, padx=10, pady=9)
		self.join_btn.grid(row=0, column=0, sticky=E + W, padx=(0, 6))
		self.leave_btn = Button(self.controls, text="Leave", command=self.leave_group,
								bg="#bb3e03", fg="white", activebackground="#9a3412",
								activeforeground="white", bd=0, padx=10, pady=9)
		self.leave_btn.grid(row=0, column=1, sticky=E + W, padx=(6, 0))

		self.status = Label(self.master, text=f"Group: {self.group}:{self.port}",
							bg="#f4f6f8", fg="#475569", font=("Trebuchet MS", 10))
		self.status.grid(row=2, column=0, sticky=E, pady=(8, 0))

	def _create_socket(self):
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
		sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		try:
			sock.bind(("", self.port))
		except OSError:
			sock.bind((self.group, self.port))

		if self.interface == DEFAULT_INTERFACE:
			mreq = struct.pack("=4sl", socket.inet_aton(self.group), socket.INADDR_ANY)
		else:
			mreq = struct.pack("=4s4s", socket.inet_aton(self.group), socket.inet_aton(self.interface))
		sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
		sock.settimeout(0.5)
		return sock

	def join_group(self):
		if self.joined:
			return
		try:
			self.sock = self._create_socket()
		except OSError as exc:
			messagebox.showwarning("Join failed", str(exc))
			return
		self.stop_event.clear()
		self.joined = True
		self._reset_reassembly()
		self._clear_queue()
		self.label.configure(image="", text="Waiting")
		self.label.image = None
		self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
		self.listen_thread.start()

	def leave_group(self):
		if not self.joined:
			self.label.configure(image="", text="Leave")
			self.label.image = None
			return
		self.stop_event.set()
		self.joined = False
		if self.sock is not None:
			try:
				if self.interface == DEFAULT_INTERFACE:
					mreq = struct.pack("=4sl", socket.inet_aton(self.group), socket.INADDR_ANY)
				else:
					mreq = struct.pack("=4s4s", socket.inet_aton(self.group), socket.inet_aton(self.interface))
				self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
			except OSError:
				pass
			try:
				self.sock.close()
			except OSError:
				pass
			self.sock = None
		self._reset_reassembly()
		self._clear_queue()
		self.label.configure(image="", text="Leave")
		self.label.image = None

	def _listen_loop(self):
		while not self.stop_event.is_set():
			try:
				data, _ = self.sock.recvfrom(MAX_DATAGRAM_SIZE)
			except socket.timeout:
				continue
			except OSError:
				break
			self.last_packet_ms = monotonic_ms()
			self._handle_packet(data)

	def _handle_packet(self, data):
		result = self.reassembler.push(data)
		if result is None:
			return
		frame_number, tiles = result
		frame = self._compose_frame(tiles)
		if frame is None:
			return
		self._enqueue_frame(frame_number, frame)

	def _compose_frame(self, tiles):
		decoded = {}
		for index, tile in tiles.items():
			try:
				decoded[index] = Image.open(io.BytesIO(tile)).convert("RGB")
			except Exception:
				continue
		if not decoded:
			return None

		sample = next(iter(decoded.values()))
		tile_width, tile_height = sample.size
		canvas = Image.new("RGB", (tile_width * GRID_N, tile_height * GRID_M), (0, 0, 0))
		for index in range(NUM_TILES):
			col = index % GRID_N
			row = index // GRID_N
			position = (col * tile_width, row * tile_height)
			if index in decoded:
				tile = decoded[index]
				self.last_tiles[index] = tile
			elif index in self.last_tiles:
				tile = self.last_tiles[index]
			else:
				continue
			canvas.paste(tile, position)
		return canvas

	def _enqueue_frame(self, frame_number, frame):
		item = (frame_number, frame)
		while not self.stop_event.is_set():
			try:
				self.frame_queue.put(item, timeout=0.1)
				return
			except queue.Full:
				try:
					self.frame_queue.get_nowait()
				except queue.Empty:
					pass

	def _render_tick(self):
		try:
			_, frame = self.frame_queue.get_nowait()
			self._show_frame(frame)
		except queue.Empty:
			pass
		self.master.after(self.render_tick_ms, self._render_tick)

	def _waiting_tick(self):
		if self.joined and self.label.image is None and monotonic_ms() - self.last_packet_ms > 500:
			self.label.configure(text="Waiting")
		self.master.after(300, self._waiting_tick)

	def _show_frame(self, frame):
		try:
			if isinstance(frame, Image.Image):
				img = frame.convert("RGB")
			else:
				img = Image.open(io.BytesIO(frame)).convert("RGB")
		except Exception:
			return
		max_w = self.video_frame.winfo_width()
		max_h = self.video_frame.winfo_height()
		if max_w <= 1:
			max_w = self.label.winfo_width()
		if max_h <= 1:
			max_h = self.label.winfo_height()
		if max_w <= 1:
			max_w = self.default_width
		if max_h <= 1:
			max_h = int(self.default_width * 9 / 16)

		src_w, src_h = img.size
		scale = min(max_w / max(1, src_w), max_h / max(1, src_h))
		size = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
		resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
		img = img.resize(size, resample)
		photo = ImageTk.PhotoImage(img)
		self.label.configure(image=photo, text="", width=size[0], height=size[1])
		self.label.image = photo

	def _reset_reassembly(self):
		self.reassembler.reset()

	def _clear_queue(self):
		while True:
			try:
				self.frame_queue.get_nowait()
			except queue.Empty:
				break

	def close(self):
		self.leave_group()
		self.master.destroy()


def parse_args():
	parser = argparse.ArgumentParser(description="Multicast MJPEG/RTP video client")
	parser.add_argument("--group", default=DEFAULT_MCAST_GROUP)
	parser.add_argument("--port", type=int, default=DEFAULT_MCAST_PORT)
	parser.add_argument("--interface", default=DEFAULT_INTERFACE)
	return parser.parse_args()


def main():
	args = parse_args()
	if Tk is None or ImageTk is None:
		print("tkinter/ImageTk is not installed. Install python3-tk to run the client GUI.")
		return
	root = Tk()
	MulticastVideoClient(root, args.group, args.port, args.interface)
	root.mainloop()


if __name__ == "__main__":
	main()
