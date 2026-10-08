"""
config.py
Central configuration for the pothole detection + dashcam integration system.
Tune these values for your hardware and deployment.
"""

# ---------------- Camera ----------------
CAMERA_SOURCE = "http://192.168.137.174:8080/video"               # 0 = default webcam/USB capture card. Use RTSP/file path if needed.
FRAME_SKIP = 2                    # run YOLO every Nth frame to save compute
YOLO_MODEL_PATH = "pothole_model.pt"   # trained YOLOv8 weights
YOLO_CONF_THRESHOLD = 0.5
POTHOLE_CLASS_ID = 0               # class index for "pothole" in your model

# ---------------- GPS ----------------
GPS_SOURCE_TYPE = "serial"         # "serial" (USB/UART GNSS) or "bluetooth" (phone NMEA tether)
GPS_SERIAL_PORT = "COM3"           # Adjust this to your GPS serial port
GPS_BAUDRATE = 9600
GPS_MAX_FIX_AGE_SEC = 3.0          # ignore GPS fixes older than this when geotagging
GPS_MAX_JUMP_METERS = 20.0         # reject fixes that imply an unrealistic jump in 1s
GPS_HDOP_MAX = 5.0
GPS_PHONE_IP = "192.168.137.174"
GPS_PHONE_PORT = 11123                 # ignore fixes with HDOP worse than this (higher = less accurate)

# ---------------- OBD-II (optional, vehicle speed) ----------------
OBD_ENABLED = False
OBD_PORT = "/dev/ttyUSB1"
OBD_BAUDRATE = 38400

# ---------------- Storage ----------------
DB_PATH = "potholes.db"
DUPLICATE_MATCH_RADIUS_M = 10.0    # detections within this radius are merged into one pothole
POTHOLE_STALE_DAYS = 365           # mark potholes as "resolved" if unseen this long

# ---------------- Clustering ----------------
CLUSTER_EPS_METERS = 8.0           # DBSCAN neighborhood radius
CLUSTER_MIN_SAMPLES = 2            # min detections to form a confirmed cluster

# ---------------- Alerting ----------------
ALERT_DISTANCE_M = 25.0            # alert if within this distance of a known pothole
ALERT_TIME_TO_IMPACT_SEC = 2.5     # or if time-to-impact is below this (uses current speed)
ALERT_HEADING_TOLERANCE_DEG = 35.0 # only alert if pothole is roughly ahead of travel direction
ALERT_COOLDOWN_SEC = 60            # don't re-alert for the same pothole within this window

# ---------------- Cloud Sync (optional) ----------------
CLOUD_SYNC_ENABLED = False
CLOUD_BACKEND = "mqtt"             # "mqtt" (e.g. AWS IoT) or "firebase"

# MQTT / AWS IoT settings
MQTT_ENDPOINT = "your-endpoint.iot.us-east-1.amazonaws.com"
MQTT_PORT = 8883
MQTT_TOPIC = "potholes/reports"
MQTT_CA_CERT = "certs/AmazonRootCA1.pem"
MQTT_CLIENT_CERT = "certs/device-cert.pem.crt"
MQTT_CLIENT_KEY = "certs/private.pem.key"
MQTT_CLIENT_ID = "dashcam-device-001"

# Firebase settings (REST or Admin SDK)
FIREBASE_DB_URL = "https://your-project.firebaseio.com"
FIREBASE_AUTH_TOKEN = ""           # or use a service account with firebase_admin

# Sync behaviour
CLOUD_SYNC_INTERVAL_SEC = 30
CLOUD_SYNC_BATCH_SIZE = 20

# Anonymized device identity (do NOT use anything personally identifiable)
DEVICE_ID = "dashcam-anon-001"
