#!/usr/bin/env python3
"""
Aperture Dashboard — Flask web UI for live Flock camera detections.

Shows:
  - Live map with detection markers (Leaflet.js)
  - Detection list table
  - Statistics (total detections, unique cameras, tier breakdown)
  - System status (WiFi, SDR, GPS)
  - Export to KML, CSV, GPX

Access: http://10.42.42.1:8080/
"""

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template, jsonify, send_file
from database import Database

logger = logging.getLogger("aperture.dashboard")

app = Flask(
    __name__,
    static_folder=Path(__file__).parent.parent / "static",
    template_folder=Path(__file__).parent.parent / "templates",
)

db = Database()


@app.route("/")
def index():
    """Serve the main dashboard page."""
    return render_template("index.html")


@app.route("/api/detections")
def api_detections():
    """Get recent detections as JSON."""
    detections = db.get_recent(limit=500)
    return jsonify(detections)


@app.route("/api/stats")
def api_stats():
    """Get detection statistics."""
    stats = db.get_statistics()
    return jsonify(stats)


@app.route("/api/system")
def api_system():
    """Get system status including battery."""
    status = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "wifi": {"status": "running", "interface": "wlan1"},
        "sdr": {"status": "running", "device": "RTL-SDR v4"},
        "gps": {"status": "active" if db.get_recent(1) else "no fix"},
        "battery": _get_battery_status(),
    }
    return jsonify(status)


def _get_battery_status():
    """Check UPS HAT / battery status via sysfs or CLI tools."""
    # Check sysfs power supply interfaces
    power_supply_paths = [
        "/sys/class/power_supply/ups-battery",
        "/sys/class/power_supply/BAT0",
        "/sys/class/power_supply/rpi-battery",
    ]

    for path in power_supply_paths:
        try:
            if os.path.exists(f"{path}/capacity"):
                capacity = open(f"{path}/capacity").read().strip()
                status = open(f"{path}/status").read().strip() if os.path.exists(f"{path}/status") else "unknown"
                voltage = None
                if os.path.exists(f"{path}/voltage_now"):
                    voltage = int(open(f"{path}/voltage_now").read().strip()) / 1_000_000
                return {
                    "capacity": int(capacity) if capacity.isdigit() else capacity,
                    "status": status,
                    "voltage_v": round(voltage, 2) if voltage else None,
                }
        except Exception:
            continue

    # Check for x735/x705 UPS HAT
    try:
        result = subprocess.run(
            ["x735-get-power"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            # Parse output like "Voltage: 16.8V"
            for line in result.stdout.splitlines():
                if "Voltage" in line:
                    voltage = line.split(":")[-1].strip().replace("V", "")
                    return {"voltage_v": float(voltage) if voltage else None, "status": "detected"}
    except Exception:
        pass

    return {"status": "not detected"}


def _get_wifi_status():
    """Check WiFi monitor mode status."""
    try:
        result = subprocess.run(
            ["iw", "dev", "wlan1", "info"],
            capture_output=True, text=True, timeout=2
        )
        return {
            "monitor_mode": "monitor" in result.stdout,
            "interface": "wlan1",
        }
    except Exception:
        return {"monitor_mode": False, "interface": "wlan1"}


@app.route("/api/wifi-status")
def api_wifi_status():
    """Check if WiFi interface is in monitor mode."""
    return jsonify(_get_wifi_status())


@app.route("/export/kml")
def export_kml():
    """Export detections to KML."""
    kml = db.export_kml()
    return (kml, 200, {
        "Content-Type": "application/vnd.google-earth.kml+xml",
        "Content-Disposition": "attachment; filename=aperture_detections.kml",
    })


@app.route("/export/csv")
def export_csv():
    """Export detections to CSV."""
    csv_data = db.export_csv()
    return (csv_data, 200, {
        "Content-Type": "text/csv",
        "Content-Disposition": "attachment; filename=aperture_detections.csv",
    })


@app.route("/export/gpx")
def export_gpx():
    """Export detections to GPX."""
    rows = db.conn.execute("""
        SELECT lat, lon, timestamp, mac, confidence_tier
        FROM detections
        WHERE lat IS NOT NULL AND lon IS NOT NULL
        ORDER BY epoch
    """).fetchall()

    gpx = ["""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Aperture Wardriver"
     xmlns="http://www.topografix.com/GPX/1/1">
  <metadata>
    <name>Aperture Wardrive Track</name>
    <time>%s</time>
  </metadata>""" % datetime.now(timezone.utc).isoformat()]

    for lat, lon, ts, mac, tier in rows:
        gpx.append(f"""
  <wpt lat="{lat}" lon="{lon}">
    <name>{mac or 'Unknown'} (T{tier or 1})</name>
    <time>{ts}</time>
    <sym>Waypoint</sym>
  </wpt>""")

    gpx.append("</gpx>")
    return ("\n".join(gpx), 200, {
        "Content-Type": "application/gpx+xml",
        "Content-Disposition": "attachment; filename=aperture_detections.gpx",
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
