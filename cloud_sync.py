"""
cloud_sync.py
Optional cloud sync: batches unsynced local detections and pushes them
to either AWS IoT Core over MQTT+TLS, or Firebase (Realtime DB) over
REST. Designed to be resilient to intermittent connectivity - it only
marks rows as submitted after a successful publish, so anything that
fails just gets retried on the next cycle.

Anonymization: only lat/lon/timestamp/accuracy/count are sent - never
anything that could identify the driver or exact trip history beyond
the pothole event itself.
"""

import json
import time

import config
from database import PotholeDB


def _build_payload(row):
    return {
        "deviceId": config.DEVICE_ID,   # random/anonymous id, not tied to a person
        "id": row["id"],
        "lat": row["latitude"],
        "lon": row["longitude"],
        "t": row["timestamp"],
        "accuracy": row["accuracy"],
        "count": row["count"],
    }


# ---------------- MQTT / AWS IoT ----------------
def sync_via_mqtt(db: PotholeDB):
    import paho.mqtt.client as mqtt

    client = mqtt.Client(client_id=config.MQTT_CLIENT_ID)
    client.tls_set(
        ca_certs=config.MQTT_CA_CERT,
        certfile=config.MQTT_CLIENT_CERT,
        keyfile=config.MQTT_CLIENT_KEY,
    )
    client.connect(config.MQTT_ENDPOINT, config.MQTT_PORT)
    client.loop_start()

    rows = db.get_unsynced(limit=config.CLOUD_SYNC_BATCH_SIZE)
    synced_ids = []
    for row in rows:
        payload = json.dumps(_build_payload(row))
        result = client.publish(config.MQTT_TOPIC, payload, qos=1)
        result.wait_for_publish(timeout=5)
        if result.is_published():
            synced_ids.append(row["id"])

    db.mark_submitted(synced_ids)
    client.loop_stop()
    client.disconnect()
    return len(synced_ids)


# ---------------- Firebase (REST) ----------------
def sync_via_firebase(db: PotholeDB):
    import requests

    rows = db.get_unsynced(limit=config.CLOUD_SYNC_BATCH_SIZE)
    synced_ids = []
    for row in rows:
        payload = _build_payload(row)
        url = f"{config.FIREBASE_DB_URL}/potholes/{row['id']}.json"
        params = {"auth": config.FIREBASE_AUTH_TOKEN} if config.FIREBASE_AUTH_TOKEN else {}
        resp = requests.put(url, json=payload, params=params, timeout=5)
        if resp.status_code == 200:
            synced_ids.append(row["id"])

    db.mark_submitted(synced_ids)
    return len(synced_ids)


def sync_once(db: PotholeDB = None):
    own_db = db is None
    db = db or PotholeDB()
    try:
        if config.CLOUD_BACKEND == "mqtt":
            n = sync_via_mqtt(db)
        elif config.CLOUD_BACKEND == "firebase":
            n = sync_via_firebase(db)
        else:
            raise ValueError(f"Unknown CLOUD_BACKEND: {config.CLOUD_BACKEND}")
        return n
    finally:
        if own_db:
            db.close()


def run_sync_loop():
    """Blocking loop: call sync_once() every CLOUD_SYNC_INTERVAL_SEC. Run in its own thread/process."""
    db = PotholeDB()
    while True:
        try:
            n = sync_once(db)
            if n:
                print(f"[cloud_sync] Synced {n} detections.")
        except Exception as e:
            print(f"[cloud_sync] Sync failed, will retry: {e}")
        time.sleep(config.CLOUD_SYNC_INTERVAL_SEC)


if __name__ == "__main__":
    run_sync_loop()
