import argparse
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
	frame_timestamp,
	make_multicast_rtp,
	split_frame,
)
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
			fragments = list(split_frame(frame))
			with self.lock:
				for index, fragment in enumerate(fragments):
					marker = 1 if index == len(fragments) - 1 else 0
					packet = make_multicast_rtp(
						fragment,
						self.packet_seq,
						self.frame_number,
						index,
						marker,
						timestamp,
					)
					self.sock.sendto(packet, self.destination)
					self.packet_seq = (self.packet_seq + 1) & 0xFFFF
			time.sleep(FRAME_INTERVAL_SECONDS)


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


def parse_args():
	parser = argparse.ArgumentParser(description="Multicast MJPEG/RTP video server")
	parser.add_argument("filename", nargs="?", default="movie.Mjpeg")
	parser.add_argument("--group", default=DEFAULT_MCAST_GROUP)
	parser.add_argument("--port", type=int, default=DEFAULT_MCAST_PORT)
	parser.add_argument("--interface", default=DEFAULT_INTERFACE)
	parser.add_argument("--ttl", type=int, default=DEFAULT_TTL)
	parser.add_argument("--autoplay", action="store_true")
	return parser.parse_args()


def main():
	args = parse_args()
	if Tk is None:
		print("tkinter is not installed. Install python3-tk to run the server GUI.")
		return
	server = MulticastVideoServer(args.filename, args.group, args.port, args.interface, args.ttl)
	if args.autoplay:
		server.play()
	root = Tk()
	ServerApp(root, server)
	root.mainloop()


if __name__ == "__main__":
	main()
