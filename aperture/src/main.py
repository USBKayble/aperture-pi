#!/usr/bin/env python3
"""
Aperture Main — Orchestrates WiFi + SDR + GPS detection and correlation.

Runs as a systemd service. Starts all subsystems, feeds detections to
the correlator, logs to SQLite, and serves the web dashboard.

Usage:
  python3 main.py           # foreground
  python3 main.py --daemon   # background daemon (systemd service wraps this)
"""

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from wifi_scanner import WiFiSniffer  # noqa: E402
from sdr_detector import SDRDetector  # noqa: E402
from gps_handler import GPSHandler  # noqa: E402
from correlator import Correlator  # noqa: E402
from database import Database  # noqa: E402

# --- Logging Setup ---

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / f"aperture-{datetime.now().strftime('%Y%m%d')}.log"),
    ]
)
logger = logging.getLogger("aperture.main")


class Aperture:
    """Main orchestrator for Flock camera wardetection."""

    def __init__(self, wifi_iface="wlan1", sdr_enabled=True, gps_enabled=True):
        self.wifi_iface = wifi_iface
        self.sdr_enabled = sdr_enabled
        self.gps_enabled = gps_enabled

        # Initialize subsystems
        self.wifi = None
        self.sdr = None
        self.gps = None
        self.correlator = None
        self.db = None

        self._running = False

    def start(self):
        """Start all subsystems."""
        logger.info("Starting Aperture wardrive system...")

        # Initialize database
        self.db = Database()
        logger.info("Database initialized")

        # Start GPS first (other systems need it)
        if self.gps_enabled:
            self.gps = GPSHandler()
            self.gps.start()
            logger.info("GPS handler started (NEO-6M on /dev/serial0)")

        # Start correlator
        self.correlator = Correlator(gps_handler=self.gps)
        self.correlator.start()
        logger.info("Correlator started")

        # Start WiFi scanner
        try:
            self.wifi = WiFiSniffer(iface=self.wifi_iface)
            if self.wifi.start():
                logger.info(f"WiFi scanner started on {self.wifi_iface}")
        except Exception as e:
            logger.error(f"WiFi scanner failed to start: {e}")

        # Start SDR detector
        if self.sdr_enabled:
            try:
                self.sdr = SDRDetector()
                if self.sdr.start():
                    logger.info("SDR energy detector started")
            except Exception as e:
                logger.error(f"SDR detector failed to start: {e}")

        self._running = True

        # Main loop: collect detections, log to DB
        logger.info("Aperture is running. Press Ctrl+C to stop.")
        self._main_loop()

    def _main_loop(self):
        """Main detection loop."""
        try:
            while self._running:
                # Get correlated detections
                detections = self.correlator.get_detections() if self.correlator else []

                for det in detections:
                    gps_fix = det.get("correlation", {}).get("gps")
                    row_id = self.db.push_detection(det, gps_fix)

                    logger.info(
                        f"Detection logged (id={row_id}): {det.get('mac', 'N/A')} "
                        f"[{det.get('type', 'unknown')}] "
                        f"tier={det.get('confidence_tier', '?')} "
                        f"rssi={det.get('rssi', '?')} "
                        f"lat={gps_fix.get('lat', 'N/A') if gps_fix else 'N/A'}"
                    )

                # Feed new detections from sensors to correlator
                if self.wifi:
                    for d in self.wifi.get_detections():
                        self.correlator.add_wifi_detection(d)

                if self.sdr:
                    for d in self.sdr.get_detections():
                        self.correlator.add_lte_detection(d)

                time.sleep(0.2)

        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self):
        """Stop all subsystems."""
        logger.info("Shutting down Aperture...")

        if self._running:
            self._running = False

        if self.wifi:
            self.wifi.stop()
            logger.info("WiFi scanner stopped")

        if self.sdr:
            self.sdr.stop()
            logger.info("SDR detector stopped")

        if self.gps:
            self.gps.stop()
            logger.info("GPS handler stopped")

        if self.correlator:
            self.correlator.stop()
            logger.info("Correlator stopped")

        if self.db:
            stats = self.db.get_statistics()
            logger.info(
                f"Session summary: {stats['total_detections']} detections, "
                f"{stats['unique_cameras']} unique cameras"
            )

        logger.info("Aperture stopped.")

    def status(self) -> dict:
        """Get current system status."""
        return {
            "running": self._running,
            "wifi": {"started": self.wifi is not None},
            "sdr": {"started": self.sdr is not None},
            "gps": {"started": self.gps is not None},
            "correlator": {"started": self.correlator is not None},
            "database": {"connected": self.db is not None},
        }


def main():
    parser = argparse.ArgumentParser(description="Aperture Flock camera wardriver")
    parser.add_argument("--wifi-iface", default="wlan1", help="WiFi interface for monitoring")
    parser.add_argument("--no-sdr", action="store_true", help="Disable RTL-SDR energy detection")
    parser.add_argument("--no-gps", action="store_true", help="Disable GPS handler")
    parser.add_argument("--daemon", action="store_true", help="Run as background daemon")

    args = parser.parse_args()

    aperture = Aperture(
        wifi_iface=args.wifi_iface,
        sdr_enabled=not args.no_sdr,
        gps_enabled=not args.no_gps,
    )

    # Handle signals
    def signal_handler(signum, frame):
        aperture.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    if args.daemon:
        # Daemonize
        import daemon
        with daemon.DaemonContext():
            aperture.start()
    else:
        aperture.start()


if __name__ == "__main__":
    main()
