#!/usr/bin/env python3
"""
Database — SQLite persistence for Flock camera detections.

Schema:
  detections table: all correlated detections (WiFi + LTE + GPS)
  sessions table: drive session metadata
"""

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("aperture.database")

DB_PATH = Path(__file__).parent.parent / "data" / "detections.db"


class Database:
    """SQLite database for storing Flock camera detections."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path=None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path=None):
        if self._initialized:
            return
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()
        self._initialized = True

    @property
    def conn(self):
        """Thread-local SQLite connection."""
        if not hasattr(self._local, "conn"):
            self._local["conn"] = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0
            )
            self._local["conn"].execute("PRAGMA journal_mode = WAL")
            self._local["conn"].execute("PRAGMA synchronous = NORMAL")
        return self._local["conn"]

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._lock:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    notes TEXT,
                    device_count INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    epoch REAL NOT NULL,
                    type TEXT NOT NULL,           -- 'wifi', 'lte', 'correlated'
                    mac TEXT,
                    ssid TEXT,
                    rssi INTEGER,
                    frequency_mhz REAL,
                    channel INTEGER,
                    band TEXT,
                    confidence_tier INTEGER,      -- 1-4
                    method TEXT,                  -- e.g., 'wildcard_probe_ie_sig', 'lte_energy'

                    -- GPS fields
                    lat REAL,
                    lon REAL,
                    alt REAL,
                    gps_accuracy_m REAL,
                    speed_kmh REAL,
                    satellites INTEGER,

                    -- Correlation fields
                    lte_correlated INTEGER DEFAULT 0,
                    lte_bands TEXT,
                    frame_count INTEGER,

                    session_id INTEGER DEFAULT 1,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );

                CREATE INDEX IF NOT EXISTS idx_detections_mac ON detections(mac);
                CREATE INDEX IF NOT EXISTS idx_detections_time ON detections(epoch);
                CREATE INDEX IF NOT EXISTS idx_detections_confidence ON detections(confidence_tier);
                CREATE INDEX IF NOT EXISTS idx_detections_coords ON detections(lat, lon);
            """)
            self.conn.commit()

            # Ensure a session exists
            cursor = self.conn.execute(
                "INSERT OR IGNORE INTO sessions (id, start_time) VALUES (1, ?)",
                (datetime.now(timezone.utc).isoformat(),)
            )
            if cursor.rowcount > 0:
                self.conn.commit()

    def push_detection(self, detection: dict, gps_fix: dict = None) -> int:
        """Insert a detection record. Returns the row ID."""
        with self._lock:
            cursor = self.conn.execute("""
                INSERT INTO detections (
                    timestamp, epoch, type, mac, ssid, rssi,
                    frequency_mhz, channel, band, confidence_tier, method,
                    lat, lon, alt, speed_kmh, satellites,
                    lte_correlated, lte_bands, frame_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                detection.get("timestamp", datetime.now(timezone.utc).isoformat()),
                detection.get("epoch", 0),
                detection.get("type", "unknown"),
                detection.get("mac"),
                detection.get("ssid"),
                detection.get("rssi"),
                detection.get("frequency_mhz"),
                detection.get("channel"),
                detection.get("band"),
                detection.get("confidence_tier", 0),
                detection.get("method", detection.get("detection_method")),
                gps_fix.get("lat") if gps_fix else None,
                gps_fix.get("lon") if gps_fix else None,
                gps_fix.get("alt") if gps_fix else None,
                gps_fix.get("speed_kmh") if gps_fix else None,
                gps_fix.get("satellites") if gps_fix else 0,
                int(detection.get("correlation", {}).get("lte_correlated", False)) if "correlation" in detection else 0,
                json.dumps(detection.get("correlation", {}).get("lte_bands", [])) if "correlation" in detection else None,
                detection.get("frame_count"),
            ))
            self.conn.commit()
            return cursor.lastrowid

    def get_recent(self, limit=1000) -> list:
        """Get recent detections."""
        cursor = self.conn.execute("""
            SELECT * FROM detections
            ORDER BY epoch DESC
            LIMIT ?
        """, (limit,))
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_statistics(self) -> dict:
        """Get detection statistics."""
        cursor = self.conn.cursor()

        total = cursor.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
        unique_macs = cursor.execute(
            "SELECT COUNT(DISTINCT mac) FROM detections WHERE mac IS NOT NULL"
        ).fetchone()[0]

        tier_counts = cursor.execute("""
            SELECT confidence_tier, COUNT(*) FROM detections
            WHERE confidence_tier IS NOT NULL
            GROUP BY confidence_tier
            ORDER BY confidence_tier DESC
        """).fetchall()

        types = cursor.execute("""
            SELECT type, COUNT(*) FROM detections
            GROUP BY type
        """).fetchall()

        return {
            "total_detections": total,
            "unique_cameras": unique_macs,
            "by_tier": dict(tier_counts),
            "by_confidence": dict(tier_counts),
            "by_type": dict(types),
        }

    def export_kml(self) -> str:
        """Export detections to KML for Google Earth."""
        rows = self.conn.execute("""
            SELECT lat, lon, mac, confidence_tier, timestamp, type, rssi
            FROM detections
            WHERE lat IS NOT NULL AND lon IS NOT NULL
            ORDER BY epoch
        """).fetchall()

        kml = ["""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>Aperture Wardrive Results</name>
  <description>Flock camera detections</description>
  <Style id="tier4">
    <IconStyle><Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon><color>ff00ffff</color></IconStyle>
  <Style id="tier3">
    <IconStyle><Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon><color>ff00aaff</color></IconStyle>
  <Style id="tier2">
    <IconStyle><Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon><color>ff00ff00</color></IconStyle>
  <Style id="tier1">
    <IconStyle><Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon><color>ff0000ff</color></IconStyle>
"""]

        for lat, lon, mac, tier, ts, det_type, rssi in rows:
            style_id = f"tier{tier or 1}"
            kml.append(f"""
  <Placemark>
    <name>{mac or 'Unknown'} (T{tier or 1})</name>
    <description>
      Type: {det_type}
      RSSI: {rssi} dBm
      Time: {ts}
      Confidence: Tier {tier or 1}
    </description>
    <styleUrl>#{style_id}</styleUrl>
    <Point><coordinates>{lon},{lat}</coordinates></Point>
  </Placemark>""")

        kml.append("</Document>\n</kml>")
        return "\n".join(kml)

    def export_csv(self) -> str:
        """Export detections to CSV."""
        import csv
        import io
        rows = self.conn.execute("""
            SELECT timestamp, type, mac, ssid, rssi, frequency_mhz, channel,
                   confidence_tier, lat, lon, alt, speed_kmh, lte_correlated
            FROM detections
            ORDER BY epoch
        """).fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "timestamp", "type", "mac", "ssid", "rssi", "freq_mhz", "channel",
            "tier", "lat", "lon", "alt_m", "speed_kmh", "lte_correlated"
        ])
        writer.writerows(rows)
        return output.getvalue()

    def close(self):
        """Close the database connection."""
        if hasattr(self._local, "conn"):
            self._local["conn"].close()


if __name__ == "__main__":
    db = Database()
    print("Statistics:", json.dumps(db.get_statistics(), indent=2))
