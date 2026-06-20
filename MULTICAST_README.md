# Multicast Video Streaming

This folder contains a simple RTP/UDP multicast video streaming program with a
GUI server and GUI clients.

## Files

- `MulticastServer.py`: streams an MJPEG video to a multicast group and provides
  `Play` / `Pause` controls.
- `MulticastClient.py`: joins/leaves the multicast group, receives video, caches
  complete frames, and resizes playback to the window.
- `MulticastCommon.py`: shared multicast RTP packetization, fragmentation, and
  reassembly logic.
- `RtpPacket.py`: RTP header encode/decode helper.
- `VideoStream.py`: MJPEG frame reader.
- `mcastsend.py` / `mcastrecv.py`: small multicast reference examples.

## Requirements

Install Python packages/modules needed by the GUI:

```bash
pip install Pillow
```

On Linux, Tkinter may need a system package:

```bash
sudo apt install python3-tk
```

or:

```bash
sudo dnf install python3-tkinter
```

## Run

Open a terminal in this folder:

```bash
cd /home/ntdpkg/Documents/hkvi/lap_trinh_mang/Project_01_cq/Project_01/skeleton_python_rtp/python_rtp/multicast
```

Start the server:

```bash
python MulticastServer.py movie.Mjpeg --group 239.255.42.99 --port 5004 --autoplay
```

Run the server without GUI:

```bash
python MulticastServer.py movie.Mjpeg --group 239.255.42.99 --port 5004 --autoplay --no-gui
```

In no-GUI mode, type `play`, `pause`, `status`, or `quit` in the terminal.

Start one or more clients in other terminals:

```bash
python MulticastClient.py --group 239.255.42.99 --port 5004
```

In the client GUI, click `Join Multicast`. If the client has joined but the
server is paused or has not started streaming yet, the video area shows
`Waiting`.

## Multicast Addressing

The server does not need each client IP address. It sends packets to:

```text
239.255.42.99:5004
```

Any client that joins the same multicast group and port can receive the stream.

If the machine has multiple network interfaces, pass the local NIC IP with
`--interface`.

Server example:

```bash
python MulticastServer.py movie.Mjpeg --group 239.255.42.99 --port 5004 --interface 192.168.1.10
```

Client example:

```bash
python MulticastClient.py --group 239.255.42.99 --port 5004 --interface 192.168.1.20
```

`--interface` is the local interface IP of the machine running the command, not
the IP of the other side.

## Implementation Notes

- Video is sent as MJPEG over RTP/UDP multicast.
- Each MJPEG frame is split into an 8x8 grid of independently encoded JPEG
  tiles, matching the packet-loss handling used by the RTSP reference source.
- RTP `timestamp` identifies the video frame.
- RTP `seqNum` is packet-global across the stream.
- The last fragment of each frame uses the RTP marker bit.
- If a tile packet is lost, the client fills that tile from the cached tile at
  the same position in the previous rendered frames.
- If too many tiles are missing, the client drops the current frame and waits
  for the next frame.
- Complete frames are cached in a bounded queue before rendering.
- Rendered frames are resized to fit the current client window.
