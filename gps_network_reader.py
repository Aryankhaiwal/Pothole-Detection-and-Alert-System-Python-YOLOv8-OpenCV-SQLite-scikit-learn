"""
gps_network_reader.py
Same role as gps_reader.GPSReader, but reads NMEA sentences from a phone
broadcasting over Wi-Fi (TCP socket) instead of a serial/COM port. Use
this when you don't have a USB GNSS module and are using an Android app
like "Share GPS" or "BlueNMEA" (network mode) to stream GPS data.

Drop-in replacement: same start()/stop()/latest_fix()/interpolated_fix()
interface as GPSReader, so main.py needs only a two-line change to use it.
"""

import socket
import threading
import time

from gps_reader import GPSReader  # reuse all the parsing / filtering logic


class GPSNetworkReader(GPSReader):
    def __init__(self, host, port, history_size=20, connect_timeout=5):
        # Skip GPSReader.__init__'s serial-specific setup; set up the same
        # internal state (_history, _lock, _stop_event) by calling the
        # parent's init with dummy serial args, then override connection bits.
        super().__init__(port="unused", baudrate=0, history_size=history_size)
        self.host = host
        self.net_port = int(port)
        self.connect_timeout = connect_timeout
        self._sock = None

    def start(self):
        self._sock = socket.create_connection((self.host, self.net_port), timeout=self.connect_timeout)
        self._sock.settimeout(1.0)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._sock:
            self._sock.close()

    def _run(self):
        buf = b""
        while not self._stop_event.is_set():
            try:
                chunk = self._sock.recv(1024)
                if not chunk:
                    time.sleep(0.5)
                    continue
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    raw = line.decode("ascii", errors="ignore").strip()
                    if not raw:
                        continue
                    fix = self._parse_sentence(raw)
                    if fix is not None:
                        self._maybe_accept(fix)
            except socket.timeout:
                continue
            except Exception:
                time.sleep(0.5)
                continue


if __name__ == "__main__":
    # Quick manual test:
    #   python gps_network_reader.py 192.168.1.42 11123
    import sys
    host, port = sys.argv[1], sys.argv[2]
    g = GPSNetworkReader(host, port).start()
    print(f"Connected to {host}:{port}, reading GPS for 10 seconds...")
    for _ in range(10):
        time.sleep(1)
        fix = g.latest_fix()
        if fix:
            print(f"lat={fix.lat}, lon={fix.lon}, hdop={fix.hdop}, "
                  f"speed_kmh={fix.speed_kmh}, heading={fix.heading_deg}")
        else:
            print("no fix yet")
    g.stop()
