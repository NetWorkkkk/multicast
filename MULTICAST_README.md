# Multicast Video Streaming

Run the server:

```bash
python MulticastServer.py movie.Mjpeg --group 239.255.42.99 --port 5004 --autoplay
```

Run one or more clients:

```bash
python MulticastClient.py --group 239.255.42.99 --port 5004
```

The client joins/leaves the multicast group from the GUI. If it has joined but the
server is paused or has not started streaming, the video area shows `Waiting`.

If the machine has multiple network interfaces, pass the NIC IP explicitly:

```bash
python MulticastServer.py movie.Mjpeg --interface 192.168.1.10
python MulticastClient.py --interface 192.168.1.10
```

Implementation notes:

- Video is sent as MJPEG over RTP/UDP multicast.
- Each frame is fragmented into UDP-safe RTP packets.
- RTP `timestamp` identifies the video frame; RTP `seqNum` is packet-global.
- The client drops a whole frame if a fragment sequence gap is detected, then
  waits for the next frame.
- Received complete frames are cached in a bounded queue before Tkinter renders
  them, and each frame is resized to fit the current window.
