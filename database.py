"""
database.py
Local SQLite storage for pothole detections, matching the schema in the
integration roadmap: id, latitude, longitude, timestamp, accuracy, count,
status, last_seen, speed, heading, image_ref, submitted.

New detections within DUPLICATE_MATCH_RADIUS_M of an existing pothole
update that row (increment count, refresh last_seen) instead of creating
a duplicate row.
"""

import sqlite3
import time

import config
from gps_reader import haversine_m

SCHEMA = """
CREATE TABLE IF NOT EXISTS potholes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    timestamp INTEGER NOT NULL,
    accuracy REAL,
    count INTEGER DEFAULT 1,
    status TEXT DEFAULT 'active',
    last_seen INTEGER,
    speed REAL,
    heading REAL,
    image_ref TEXT,
    submitted BOOLEAN DEFAULT 0
);
"""


class PotholeDB:
    def __init__(self, path=None):
        self.path = path or config.DB_PATH
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def insert_or_merge(self, lat, lon, accuracy=None, speed=None, heading=None,
                         image_ref=None, timestamp=None):
        """
        Insert a new detection, or merge into an existing nearby pothole
        row if one is within DUPLICATE_MATCH_RADIUS_M.
        Returns the row id that was inserted or updated.
        """
        ts = int(timestamp if timestamp is not None else time.time())
        existing = self._find_nearby(lat, lon)

        if existing:
            row_id = existing["id"]
            self.conn.execute(
                """UPDATE potholes
                   SET count = count + 1,
                       last_seen = ?,
                       accuracy = COALESCE(?, accuracy),
                       status = 'active'
                   WHERE id = ?""",
                (ts, accuracy, row_id),
            )
            self.conn.commit()
            return row_id

        cur = self.conn.execute(
            """INSERT INTO potholes
               (latitude, longitude, timestamp, accuracy, count, status,
                last_seen, speed, heading, image_ref, submitted)
               VALUES (?, ?, ?, ?, 1, 'active', ?, ?, ?, ?, 0)""",
            (lat, lon, ts, accuracy, ts, speed, heading, image_ref),
        )
        self.conn.commit()
        return cur.lastrowid

    def _find_nearby(self, lat, lon):
        """
        Coarse bounding-box pre-filter (cheap) then precise haversine check.
        Good enough for a local on-device DB with a modest number of rows;
        for very large datasets, use a spatial index or geohash instead.
        """
        # ~1 degree latitude ~= 111km; build a generous box first
        deg_margin = (config.DUPLICATE_MATCH_RADIUS_M / 111000.0) * 3
        rows = self.conn.execute(
            """SELECT id, latitude, longitude FROM potholes
               WHERE latitude BETWEEN ? AND ?
                 AND longitude BETWEEN ? AND ?
                 AND status = 'active'""",
            (lat - deg_margin, lat + deg_margin, lon - deg_margin, lon + deg_margin),
        ).fetchall()

        for row_id, r_lat, r_lon in rows:
            if haversine_m(lat, lon, r_lat, r_lon) <= config.DUPLICATE_MATCH_RADIUS_M:
                return {"id": row_id}
        return None

    def get_active_potholes(self):
        cur = self.conn.execute(
            "SELECT id, latitude, longitude, accuracy, count, last_seen FROM potholes WHERE status = 'active'"
        )
        cols = ["id", "latitude", "longitude", "accuracy", "count", "last_seen"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_unsynced(self, limit=None):
        q = "SELECT * FROM potholes WHERE submitted = 0"
        if limit:
            q += f" LIMIT {int(limit)}"
        cur = self.conn.execute(q)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def mark_submitted(self, ids):
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        self.conn.execute(f"UPDATE potholes SET submitted = 1 WHERE id IN ({placeholders})", ids)
        self.conn.commit()

    def expire_stale(self):
        """Mark potholes not seen in POTHOLE_STALE_DAYS as resolved (likely repaired)."""
        cutoff = int(time.time()) - config.POTHOLE_STALE_DAYS * 86400
        self.conn.execute(
            "UPDATE potholes SET status = 'resolved' WHERE last_seen < ? AND status = 'active'",
            (cutoff,),
        )
        self.conn.commit()
