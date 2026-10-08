"""
clustering.py
Consolidates raw detection rows into confirmed "known potholes" using
DBSCAN over haversine distance, as described in the roadmap. Run this
periodically (e.g. on a schedule, or nightly) rather than on every frame.
"""

import numpy as np
from sklearn.cluster import DBSCAN

import config
from database import PotholeDB


def run_clustering(db: PotholeDB = None):
    """
    Reads all active potholes, clusters nearby points, and merges each
    cluster into a single representative row (centroid, summed count).
    Returns the number of clusters found.
    """
    own_db = db is None
    db = db or PotholeDB()

    rows = db.get_active_potholes()
    if len(rows) < 2:
        if own_db:
            db.close()
        return 0

    coords_deg = np.radians([[r["latitude"], r["longitude"]] for r in rows])
    eps_rad = config.CLUSTER_EPS_METERS / 6371000.0  # convert meters to radians for haversine metric

    labels = DBSCAN(
        eps=eps_rad,
        min_samples=config.CLUSTER_MIN_SAMPLES,
        metric="haversine",
    ).fit_predict(coords_deg)

    clusters = {}
    for row, label in zip(rows, labels):
        if label == -1:
            continue  # noise point, leave as its own unconfirmed entry
        clusters.setdefault(label, []).append(row)

    for label, members in clusters.items():
        _merge_cluster(db, members)

    if own_db:
        db.close()
    return len(clusters)


def _merge_cluster(db: PotholeDB, members):
    """Collapse a cluster of rows into the first row (centroid + summed count), delete the rest."""
    lat = sum(m["latitude"] for m in members) / len(members)
    lon = sum(m["longitude"] for m in members) / len(members)
    total_count = sum(m["count"] for m in members)
    last_seen = max(m["last_seen"] for m in members)
    keep_id = members[0]["id"]
    other_ids = [m["id"] for m in members[1:]]

    db.conn.execute(
        "UPDATE potholes SET latitude = ?, longitude = ?, count = ?, last_seen = ? WHERE id = ?",
        (lat, lon, total_count, last_seen, keep_id),
    )
    if other_ids:
        placeholders = ",".join("?" * len(other_ids))
        db.conn.execute(f"DELETE FROM potholes WHERE id IN ({placeholders})", other_ids)
    db.conn.commit()


if __name__ == "__main__":
    n = run_clustering()
    print(f"Clustering complete: {n} confirmed pothole clusters.")
