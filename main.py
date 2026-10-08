"""
main.py
Ties everything together, matching the roadmap's integration plan:

  Camera Frames -> YOLOv8 -> Attach GPS+Time -> Store in DB
                                                    |
  GPS/IMU  ----------------------------------------+--> Alert loop vs known potholes
                                                    |
                                             Cloud sync (optional, background thread)
                                                    |
                                  Clustering/map-match (periodic background job)

Run:
    python main.py
"""

import threading
import time

import cv2
from ultralytics import YOLO

import config
from gps_network_reader import GPSNetworkReader
from database import PotholeDB
from alerting import AlertManager
from clustering import run_clustering

try:
    import cloud_sync
except ImportError:
    cloud_sync = None


def clustering_loop(interval_sec=300):
    """Periodically consolidate raw detections into confirmed pothole clusters."""
    while True:
        time.sleep(interval_sec)
        try:
            n = run_clustering()
            print(f"[clustering] {n} clusters consolidated.")
        except Exception as e:
            print(f"[clustering] failed: {e}")


def cloud_sync_loop():
    if not config.CLOUD_SYNC_ENABLED or cloud_sync is None:
        return
    cloud_sync.run_sync_loop()


def alert_loop(db: PotholeDB, gps: GPSNetworkReader, alert_manager: AlertManager, interval_sec=1.0):
    """Continuously checks current position against known potholes."""
    while True:
        fix = gps.latest_fix()
        if fix is not None:
            known = db.get_active_potholes()
            alert_manager.check(
                current_lat=fix.lat,
                current_lon=fix.lon,
                heading_deg=fix.heading_deg,
                speed_kmh=fix.speed_kmh or 0.0,
                known_potholes=known,
            )
        time.sleep(interval_sec)


def main():
    # ---- Set up components ----
    db = PotholeDB(config.DB_PATH)
    gps = GPSNetworkReader(config.GPS_PHONE_IP, config.GPS_PHONE_PORT).start()
    alert_manager = AlertManager()
    model = YOLO(config.YOLO_MODEL_PATH)
    cap = cv2.VideoCapture(config.CAMERA_SOURCE)

    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera source: {config.CAMERA_SOURCE}")

    # ---- Background threads ----
    threading.Thread(target=alert_loop, args=(db, gps, alert_manager), daemon=True).start()
    threading.Thread(target=clustering_loop, daemon=True).start()
    if config.CLOUD_SYNC_ENABLED:
        threading.Thread(target=cloud_sync_loop, daemon=True).start()

    frame_idx = 0
    print("Pothole detection system running. Press ESC to quit.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Camera frame read failed, stopping.")
                break

            frame_idx += 1
            frame_time = time.time()

            if frame_idx % config.FRAME_SKIP != 0:
                if cv2.waitKey(1) == 27:
                    break
                continue

            results = model(frame, verbose=False)

            for r in results:
                boxes = getattr(r, "boxes", None)
                if boxes is None:
                    continue
                for box in boxes.data.tolist():
                    x1, y1, x2, y2, conf, cls_id = box
                    if int(cls_id) != config.POTHOLE_CLASS_ID or conf < config.YOLO_CONF_THRESHOLD:
                        continue

                    # Geotag: interpolate GPS to the frame's capture time
                    fix = gps.interpolated_fix(frame_time) or gps.latest_fix()
                    if fix is None:
                        print("No GPS fix available yet, skipping detection.")
                        continue

                    row_id = db.insert_or_merge(
                        lat=fix.lat,
                        lon=fix.lon,
                        accuracy=fix.hdop,
                        speed=fix.speed_kmh,
                        heading=fix.heading_deg,
                        timestamp=frame_time,
                    )
                    print(f"Pothole detected -> row {row_id} at {fix.lat:.6f}, {fix.lon:.6f} "
                          f"(conf={conf:.2f})")

            if cv2.waitKey(1) == 27:  # ESC to quit
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()
        gps.stop()
        db.close()


if __name__ == "__main__":
    main()
