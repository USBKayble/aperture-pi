#!/usr/bin/env python3
"""
GPS Handler — Reads NMEA data from NEO-6M via gpsd.

Wired to Pi GPIO UART:
  GPS VCC  → Pi Pin 1 (3.3V)
  GPS GND  → Pi Pin 6 (GND)
  GPS TX   → Pi Pin 10 (GPIO15/RXD)
  GPS RX   → Pi Pin 8 (GPIO14/TXD, not connected)

gpsd listens on localhost:2947 and serves NMEA/JSON.
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

try:
    import gps3
except ImportError:
    gps3 = None

logger = logging.getLogger("aperture.gps_handler")

# Default gpsd settings (matches Raspbian defaults)
GPSD_HOST = "localhost"
GPSD_PORT = 2947
GPSD_TIMEOUT = 5.0  # seconds


class GPSHandler:
    """Handles GPS data from gpsd / NEO-6M module."""

    def __init__(self, host=GPSD_HOST, port=GPSD_PORT):
        self.host = host
        self.port = port
        self._running = False
        self._thread = None
        self._lock = threading.Lock()

        # Current GPS state
        self._fix = None
        self._lat = None
        self._lon = None
        self._alt = None
        self._speed = None
        self._satellites = 0
        self._last_update = 0
        self._fix_quality = 0

    def _connect(self):
        """Connect to gpsd."""
        if gps3 is None:
            logger.warning("gps3 library not installed — GPS will be simulated")
            return None
        try:
            from gps3 import gps3
            gps_socket = gps3.GPSDSocket(
                host=self.host,
                port=self.port,
                timeout=GPSD_TIMEOUT
            )
            gps_socket.connect()
            data_stream = gps3.DataStream()
            gps_socket.watch(data_stream)
            return gps_socket, data_stream
        except Exception as e:
            logger.error(f"Failed to connect to gpsd: {e}")
            return None

    def _parse_nmea_direct(self):
        """Fallback: parse NMEA directly from serial port if gpsd is unavailable."""
        import serial
        try:
            ser = serial.Serial(
                port="/dev/serial0",
                baudrate=9600,
                timeout=1
            )
            while self._running:
                line = ser.readline().decode('ascii', errors='replace').strip()
                if line.startswith("$GPGGA"):
                    parts = line.split(",")
                    if len(parts) >= 14:
                        # Parse GGA: time, lat, N/S, lon, E/W, fix, sats, ...
                        if parts[6] and int(parts[6]) > 0:  # valid fix
                            lat = self._parse_nmea_coord(parts[2], parts[3])
                            lon = self._parse_nmea_coord(parts[4], parts[5])
                            if lat and lon:
                                self._set_fix(lat, lon, alt=float(parts[9]) if parts[9] else 0)
                elif line.startswith("$GPRMC"):
                    parts = line.split(",")
                    if len(parts) >= 12 and parts[2] == "A":  # valid
                        lat = self._parse_nmea_coord(parts[3], parts[4])
                        lon = self._parse_nmea_coord(parts[5], parts[6])
                        speed = float(parts[7]) if parts[7] else 0.0
                        if lat and lon:
                            self._set_fix(lat, lon, speed=speed)
        except Exception as e:
            logger.error(f"Direct NMEA parse error: {e}")

    @staticmethod
    def _parse_nmea_coord(coord_str: str, direction: str) -> Optional[float]:
        """Parse NMEA coordinate (DDMM.MMMM) to decimal degrees."""
        if not coord_str:
            return None
        try:
            # DDMM.MMMM format
            if direction in ("N", "S"):
                degrees = float(coord_str[:2])
                minutes = float(coord_str[2:])
            else:
                degrees = float(coord_str[:3])
                minutes = float(coord_str[3:])

            decimal = degrees + minutes / 60.0
            if direction in ("S", "W"):
                decimal = -decimal
            return decimal
        except (ValueError, IndexError):
            return None

    def _set_fix(self, lat, lon, alt=None, speed=None, sats=None, quality=None):
        """Update GPS fix data."""
        with self._lock:
            self._lat = lat
            self._lon = lon
            self._alt = alt
            self._speed = speed
            if sats is not None:
                self._satellites = sats
            if quality is not None:
                self._fix_quality = quality
            self._last_update = time.time()

    def start(self):
        """Start GPS monitoring in a background thread."""
        self._running = True
        logger.info(f"Starting GPS handler (gpsd: {self.host}:{self.port})")

        def run():
            # Try gpsd first
            conn = self._connect()
            if conn and gps3 is not None:
                gps_socket, data_stream = conn
                for new_data in gps_socket:
                    if not self._running:
                        break
                    if new_data:
                        data_stream.unpack(new_data)
                        if 'lat' in data_stream.TPV:
                            self._set_fix(
                                lat=data_stream.TPV['lat'],
                                lon=data_stream.TPV['lon'],
                                alt=data_stream.TPV.get('alt'),
                                speed=data_stream.TPV.get('speed'),
                                sats=data_stream.TPV.get('satellites'),
                                quality=data_stream.TPV.get('mode')
                            )
            else:
                # Fallback to direct serial
                logger.warning("gpsd not available, falling back to direct serial")
                self._parse_nmea_direct()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop GPS monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def get_current_fix(self) -> Optional[dict]:
        """Get current GPS fix as a dict, or None if no fix."""
        with self._lock:
            if self._lat is None or self._lon is None:
                return None
            # Consider stale after 5 seconds
            if time.time() - self._last_update > 5.0:
                return None
            return {
                "lat": round(self._lat, 8),
                "lon": round(self._lon, 8),
                "alt": round(self._alt, 1) if self._alt is not None else None,
                "speed_kmh": round(self._speed * 3.6, 1) if self._speed is not None else None,
                "satellites": self._satellites,
                "fix_quality": self._fix_quality,
                "last_update": datetime.fromtimestamp(self._last_update, tz=timezone.utc).isoformat(),
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    gps = GPSHandler()
    gps.start()

    try:
        while True:
            fix = gps.get_current_fix()
            if fix:
                print(json.dumps(fix))
            else:
                print(json.dumps({"status": "no fix"}))
            time.sleep(1)
    except KeyboardInterrupt:
        gps.stop()
        print("\nStopped")
