# Dashcam Pothole Detection & Alert System

Implements the roadmap: Camera → YOLOv8 → GPS geotagging → SQLite → clustering → alerting → optional cloud sync.

## Files
- `config.py` — all tunable settings (camera source, GPS port, thresholds, cloud creds).
- `gps_reader.py` — background thread parsing NMEA (GPGGA/GPRMC) from a serial GNSS module or a Bluetooth-tethered phone; filters bad fixes; interpolates position to a frame's exact timestamp.
- `database.py` — SQLite storage; merges detections within `DUPLICATE_MATCH_RADIUS_M` into one row instead of duplicating.
- `clustering.py` — DBSCAN (haversine) to consolidate raw points into confirmed potholes; run periodically.
- `alerting.py` — distance / time-to-impact / heading check with per-pothole cooldown.
- `cloud_sync.py` — optional batch sync to AWS IoT (MQTT+TLS) or Firebase (REST); only anonymized fields are sent.
- `main.py` — wires it all together; run this.

## Setup
```bash
pip install -r requirements.txt
```
1. Put your trained YOLOv8 weights at the path set in `config.YOLO_MODEL_PATH`.
2. Set `config.CAMERA_SOURCE` (0 for a USB/webcam feed, or an RTSP/HDMI-capture path).
3. Set `config.GPS_SERIAL_PORT`:
   - USB/UART GNSS module (e.g. u-blox NEO-6M): its `/dev/ttyUSB*` device.
   - Phone GPS over Bluetooth: pair the phone, bind it to `/dev/rfcomm0`, and use an NMEA-broadcasting app (e.g. "GPS NMEA Tether") — same serial code path works unchanged.
4. If you have an OBD-II dongle for speed, set `OBD_ENABLED = True` and extend `main.py` to read speed via `python-obd` and feed it into the alert check (there's a stub in `config.py` for the port/baud).
5. For cloud sync, set `CLOUD_SYNC_ENABLED = True` and fill in either the MQTT/AWS IoT certs or the Firebase URL/token in `config.py`.

## Run
```bash
python main.py
```
This opens the camera, runs YOLOv8 on every `FRAME_SKIP`th frame, geotags any pothole detections against the live GPS feed, stores/merges them in `potholes.db`, and in the background: re-checks your live position against known potholes for alerts, re-clusters raw detections every 5 minutes, and (if enabled) syncs unsynced rows to the cloud every `CLOUD_SYNC_INTERVAL_SEC`.

## Notes / next steps
- Swap the `print()` alert in `alerting.AlertManager` for a real beep (e.g. GPIO buzzer) or an overlay on the dashcam's display.
- For higher accuracy, replace the "use latest fix" fallback with a proper Kalman/EKF fusion of GPS + IMU + OBD speed (the roadmap's sensor-fusion section) — `gps_reader.py` already exposes the raw fix history to build this on top of.
- The DB duplicate-match in `database.py` uses a bounding-box + haversine check, which is fine for a single device's local table; for large multi-vehicle datasets, do this consolidation server-side with a spatial index instead.
