"""
gps_reader.py
Reads NMEA sentences (GPGGA / GPRMC) from a serial GNSS module or a
Bluetooth-tethered smartphone NMEA stream, keeps a short rolling history
of fixes, filters bad/jumpy fixes, and exposes interpolation so a video
frame timestamp can be matched to a precise lat/lon.

Works with:
  - USB/UART GNSS receivers (u-blox NEO-6M/7M etc.) via pyserial
  - Phone GPS tethered over Bluetooth SPP, which shows up as a serial
    device too (e.g. /dev/rfcomm0) once paired - same code path.
"""

import math
import threading
import time
from collections import deque

import serial

import config


def _nmea_to_decimal(raw, direction):
    """Convert NMEA ddmm.mmmm format to decimal degrees."""
    if not raw:
        return None
    raw = float(raw)
    degrees = int(raw // 100)
    minutes = raw - degrees * 100
    decimal = degrees + minutes / 60.0
    if direction in ("S", "W"):
        decimal = -decimal
    return decimal


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in meters between two lat/lon points."""
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


class GPSFix:
    __slots__ = ("lat", "lon", "hdop", "speed_kmh", "heading_deg", "timestamp")

    def __init__(self, lat, lon, hdop=None, speed_kmh=None, heading_deg=None, timestamp=None):
        self.lat = lat
        self.lon = lon
        self.hdop = hdop
        self.speed_kmh = speed_kmh
        self.heading_deg = heading_deg
        self.timestamp = timestamp if timestamp is not None else time.time()


class GPSReader:
    """
    Background thread that continuously reads NMEA sentences and keeps a
    rolling buffer of recent fixes for interpolation and jump-filtering.
    """

    def __init__(self, port=None, baudrate=None, history_size=20):
        self.port = port or config.GPS_SERIAL_PORT
        self.baudrate = baudrate or config.GPS_BAUDRATE
        self._history = deque(maxlen=history_size)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._serial = None

    # ---------------- lifecycle ----------------
    def start(self):
        self._serial = serial.Serial(self.port, self.baudrate, timeout=1)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._serial:
            self._serial.close()

    # ---------------- internal ----------------
    def _run(self):
        while not self._stop_event.is_set():
            try:
                raw = self._serial.readline().decode("ascii", errors="ignore").strip()
            except Exception:
                continue
            if not raw:
                continue
            fix = self._parse_sentence(raw)
            if fix is not None:
                self._maybe_accept(fix)

    def _parse_sentence(self, line):
        parts = line.split(",")
        if line.startswith("$GPGGA") or line.startswith("$GNGGA"):
            # $GPGGA,time,lat,N,lon,E,fixquality,numsats,hdop,alt,...
            if len(parts) < 9:
                return None
            lat = _nmea_to_decimal(parts[2], parts[3])
            lon = _nmea_to_decimal(parts[4], parts[5])
            hdop = float(parts[8]) if parts[8] else None
            if lat is None or lon is None:
                return None
            return GPSFix(lat=lat, lon=lon, hdop=hdop)

        if line.startswith("$GPRMC") or line.startswith("$GNRMC"):
            # $GPRMC,time,status,lat,N,lon,E,speed_knots,heading,date,...
            if len(parts) < 9 or parts[2] != "A":
                return None
            lat = _nmea_to_decimal(parts[3], parts[4])
            lon = _nmea_to_decimal(parts[5], parts[6])
            speed_kmh = float(parts[7]) * 1.852 if parts[7] else None
            heading = float(parts[8]) if parts[8] else None
            if lat is None or lon is None:
                return None
            return GPSFix(lat=lat, lon=lon, speed_kmh=speed_kmh, heading_deg=heading)

        return None

    def _maybe_accept(self, fix):
        with self._lock:
            # HDOP filter
            if fix.hdop is not None and fix.hdop > config.GPS_HDOP_MAX:
                return

            # Jump filter vs. last accepted fix
            if self._history:
                last = self._history[-1]
                dt = max(fix.timestamp - last.timestamp, 1e-3)
                dist = haversine_m(last.lat, last.lon, fix.lat, fix.lon)
                # Reject implausible jumps (e.g. > threshold in ~1s of travel)
                if dist > config.GPS_MAX_JUMP_METERS and dt < 1.5:
                    return
                # Carry forward hdop/speed/heading if this sentence didn't have them
                if fix.hdop is None:
                    fix.hdop = last.hdop
                if fix.speed_kmh is None:
                    fix.speed_kmh = last.speed_kmh
                if fix.heading_deg is None:
                    fix.heading_deg = last.heading_deg

            self._history.append(fix)

    # ---------------- public API ----------------
    def latest_fix(self):
        with self._lock:
            if not self._history:
                return None
            fix = self._history[-1]
            if time.time() - fix.timestamp > config.GPS_MAX_FIX_AGE_SEC:
                return None  # stale, caller should handle gracefully
            return fix

    def interpolated_fix(self, target_time):
        """
        Return an interpolated GPSFix for target_time by finding the two
        nearest history fixes that bracket it. Falls back to nearest fix
        if bracketing points aren't available.
        """
        with self._lock:
            if not self._history:
                return None
            fixes = list(self._history)

        # find bracketing pair
        before = None
        after = None
        for f in fixes:
            if f.timestamp <= target_time:
                before = f
            elif f.timestamp > target_time and after is None:
                after = f
                break

        if before and after:
            span = after.timestamp - before.timestamp
            ratio = 0.0 if span <= 0 else (target_time - before.timestamp) / span
            lat = before.lat + (after.lat - before.lat) * ratio
            lon = before.lon + (after.lon - before.lon) * ratio
            hdop = before.hdop if before.hdop is not None else after.hdop
            speed = before.speed_kmh if before.speed_kmh is not None else after.speed_kmh
            heading = before.heading_deg if before.heading_deg is not None else after.heading_deg
            return GPSFix(lat, lon, hdop=hdop, speed_kmh=speed, heading_deg=heading, timestamp=target_time)

        # no bracket available - use nearest single fix
        return before or after
