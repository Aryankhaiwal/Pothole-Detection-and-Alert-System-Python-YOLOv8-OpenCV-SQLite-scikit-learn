"""
alerting.py
Runtime alert loop: compares current vehicle position/heading/speed
against known potholes and triggers an alert when approaching one,
with a cooldown so the same pothole isn't re-announced repeatedly.
"""

import math
import time

import config
from gps_reader import haversine_m


def bearing_deg(lat1, lon1, lat2, lon2):
    """Compass bearing (0-360) from point 1 to point 2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def angle_diff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


class AlertManager:
    def __init__(self, on_alert=None):
        """
        on_alert: callback(pothole_dict, distance_m) invoked when an alert
        should fire. Defaults to printing / could trigger audio, a beep on
        a GPIO buzzer, or an overlay on the dashcam UI.
        """
        self.on_alert = on_alert or self._default_alert
        self._last_alert_time = {}  # pothole_id -> timestamp

    def _default_alert(self, pothole, distance_m):
        print(f"[ALERT] Pothole ahead in {distance_m:.1f} m (id={pothole['id']}, "
              f"seen {pothole['count']}x)")

    def check(self, current_lat, current_lon, heading_deg, speed_kmh, known_potholes):
        """
        current_* : vehicle's current fused position/heading/speed
        known_potholes : list of dicts with latitude/longitude/id/count (from db.get_active_potholes())
        """
        speed_mps = max(speed_kmh, 0) / 3.6 if speed_kmh else 0.0
        now = time.time()

        for p in known_potholes:
            dist = haversine_m(current_lat, current_lon, p["latitude"], p["longitude"])

            # Only consider potholes roughly ahead of travel direction
            if heading_deg is not None:
                brg = bearing_deg(current_lat, current_lon, p["latitude"], p["longitude"])
                if angle_diff(brg, heading_deg) > config.ALERT_HEADING_TOLERANCE_DEG:
                    continue

            time_to_impact = dist / speed_mps if speed_mps > 0.5 else float("inf")

            within_distance = dist <= config.ALERT_DISTANCE_M
            within_time = time_to_impact <= config.ALERT_TIME_TO_IMPACT_SEC

            if not (within_distance or within_time):
                continue

            last = self._last_alert_time.get(p["id"], 0)
            if now - last < config.ALERT_COOLDOWN_SEC:
                continue  # cooldown active, skip

            self._last_alert_time[p["id"]] = now
            self.on_alert(p, dist)
