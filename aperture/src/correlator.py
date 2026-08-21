#!/usr/bin/env python3
"""
Correlator — Merges WiFi + LTE detections, correlates with GPS, assigns confidence.

Takes detections from WiFiSniffer and SDRDetector, correlates them by
timestamp + GPS proximity, deduplicates by MAC, and outputs unified
detection events for database logging and web dashboard.
"""

import json
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("aperture.correlator")

# Correlation parameters
CORRELATION_WINDOW_S = 3.0     # Seconds within which WiFi + LTE hits are correlated
DEDUP_WINDOW_S = 30.0          # Seconds before same MAC is logged again
GPS_FRESHNESS_S = 5.0          # GPS fix must be this fresh
LOCATION_CLUSTER_M = 50.0      # Meters — detections within this distance are clustered


class Correlator:
    """Correlates detections across WiFi, LTE, and GPS."""

    def __init__(self, gps_handler=None):
        self.gps_handler = gps_handler
        self._running = False
        self._thread = None
        self._lock = threading.Lock()

        # Detection queues from sensors
        self._wifi_queue = deque()
        self._lte_queue = deque()

        # Unified detection output
        self._detection_queue = deque()

        # Dedup tracking: mac -> last_seen_epoch
        self._last_seen = {}  # mac -> epoch

        # GPS cache
        self._last_gps = None
        self._gps_update_thread = None

    def add_wifi_detection(self, detection: dict):
        """Add a WiFi detection to the correlator."""
        with self._lock:
            self._wifi_queue.append(detection)

    def add_lte_detection(self, detection: dict):
        """Add an LTE detection to the correlator."""
        with self._lock:
            self._lte_queue.append(detection)

    def _get_fresh_gps(self) -> Optional[dict]:
        """Get GPS fix if fresh enough."""
        if self.gps_handler:
            fix = self.gps_handler.get_current_fix()
            if fix:
                self._last_gps = fix
            return fix
        return self._last_gps

    def _correlate_wifi_lte(self, wifi_det: dict) -> dict:
        """
        Check if an LTE energy spike occurred within CORRELATION_WINDOW_S
        of this WiFi detection. Merge into a combined detection.
        """
        wifi_epoch = wifi_det.get("epoch", time.time())
        gps = self._get_fresh_gps()

        result = dict(wifi_det)
        result["correlation"] = {
            "lte_correlated": False,
            "lte_bands": [],
            "gps": gps,
        }

        # Check LTE queue for recent spikes
        matched_lte = []
        to_remove = []
        for i, lte_det in enumerate(self._lte_queue):
            lte_epoch = lte_det.get("epoch", time.time())
            if abs(lte_epoch - wifi_epoch) <= CORRELATION_WINDOW_S:
                matched_lte.append(lte_det)
                to_remove.append(i)

        # Remove matched items (reverse order to not mess up indices)
        for i in sorted(to_remove, reverse=True):
            del self._lte_queue[i]

        if matched_lte:
            result["correlation"]["lte_correlated"] = True
            result["correlation"]["lte_bands"] = [
                m["band_description"] for m in matched_lte
            ]
            # Boost confidence if WiFi + LTE both detected
            if result.get("confidence_tier", 0) < 4:
                result["confidence_tier"] = min(4, result.get("confidence_tier", 0) + 1)
            result["correlation"]["lte_spikes"] = len(matched_lte)

        # Clean old items from LTE queue
        now = time.time()
        while self._lte_queue and now - self._lte_queue[0].get("epoch", 0) > CORRELATION_WINDOW_S * 5:
            self._lte_queue.popleft()

        return result

    def _check_dedup(self, mac: str) -> bool:
        """Check if this MAC was seen recently. Returns True if should skip."""
        now = time.time()
        last = self._last_seen.get(mac, 0)
        if now - last < DEDUP_WINDOW_S:
            return True
        self._last_seen[mac] = now
        # Clean old entries
        self._last_seen = {k: v for k, v in self._last_seen.items()
                          if now - v < DEDUP_WINDOW_S * 5}
        return False

    def _gps_monitor(self):
        """Background thread to keep GPS fresh."""
        while self._running:
            if self.gps_handler:
                self._last_gps = self.gps_handler.get_current_fix()
            time.sleep(0.5)

    def start(self):
        """Start the correlator in a background thread."""
        self._running = True
        if self.gps_handler:
            self._gps_update_thread = threading.Thread(
                target=self._gps_monitor, daemon=True
            )
            self._gps_update_thread.start()

        logger.info("Starting correlator")

        def run():
            while self._running:
                self._process_queues()
                time.sleep(0.1)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the correlator."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def _process_queues(self):
        """Process pending detections."""
        # Process WiFi detections
        while self._wifi_queue:
            wifi_det = self._wifi_queue.popleft()

            mac = wifi_det.get("mac")
            if mac and self._check_dedup(mac):
                # Still update GPS, but skip logging
                continue

            # Correlate with LTE + GPS
            correlated = self._correlate_wifi_lte(wifi_det)

            # Add to output queue
            with self._lock:
                self._detection_queue.append(correlated)

            logger.info(
                f"Correlation: {mac} tier={correlated['confidence_tier']} "
                f"lte={correlated['correlation']['lte_correlated']} "
                f"gps={'yes' if correlated['correlation']['gps'] else 'no'}"
            )

        # Process standalone LTE detections (no WiFi match)
        now = time.time()
        standalone_lte = []
        while self._lte_queue:
            lte_det = self._lte_queue[0]
            lte_epoch = lte_det.get("epoch", 0)
            # If older than correlation window, it's standalone
            if now - lte_epoch > CORRELATION_WINDOW_S:
                standalone_lte.append(self._lte_queue.popleft())
            else:
                break

        for lte_det in standalone_lte:
            gps = self._get_fresh_gps()
            result = dict(lte_det)
            result["correlation"] = {
                "lte_correlated": False,
                "gps": gps,
            }
            with self._lock:
                self._detection_queue.append(result)

    def get_detections(self) -> list:
        """Get and clear the unified detection queue."""
        with self._lock:
            detections = list(self._detection_queue)
            self._detection_queue.clear()
        return detections
