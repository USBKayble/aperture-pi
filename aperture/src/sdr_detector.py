#!/usr/bin/env python3
"""
SDR Detector — Passive LTE uplink energy detection via RTL-SDR v4.

Monitors the cellular uplink bands that Flock cameras' Quectel BG95-M3 modems use.
When a camera uploads telemetry/ALPR data, it transmits short bursts on these
frequencies. We detect the energy spikes (no demodulation, no decoding).

Supported bands (BG95-M3 uplink):
  - Band 28: 703-733 MHz (700 MHz) — primary in North America
  - Band 8:  880-905 MHz (900 MHz) — AT&T/T-Mobile
  - Band 26: 814-849 MHz (850 MHz) — Verizon
  - Band 71: 617-663 MHz (600 MHz) — T-Mobile low-band
  - EGPRS:   824/850/900 MHz       — GSM/EDGE fallback

Method: rtl_power scans with 100kHz RBW, 10ms integration.
Trigger: power spike > baseline + threshold dB, sustained for 2+ consecutive scans.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("aperture.sdr_detector")

# --- Config ---

# LTE uplink bands to monitor (frequency ranges in MHz)
LTE_BANDS = [
    {"name": "B28_700", "freq_range": (617, 866), "description": "Band 28/71/12/13/14/20/85 (600-800 MHz)"},
    {"name": "B8_900",  "freq_range": (880, 960), "description": "Band 8/26/5 (850-960 MHz)"},
]

# Detection parameters
RBW_HZ = 100_000        # Resolution bandwidth
INTEGRATION_MS = 10     # Integration time per FFT bin
THRESHOLD_DB = 10.0     # dB above baseline to count as a spike
MIN_CONSECUTIVE_HITS = 2  # Must see sustained activity
BASELINE_WINDOW = 100   # Samples for baseline calculation

# Map frequency ranges to likely carrier bands for labeling
BAND_MAP = [
    (617, 716, "Band 71 / Band 12-14 / Band 28 UL (600-700 MHz)"),
    (716, 733, "Band 28 UL (700 MHz)"),
    (791, 821, "Band 20 UL (800 MHz)"),
    (814, 849, "Band 26 / Band 5 UL (850 MHz)"),
    (824, 849, "EGPRS 850 (824-849 MHz)"),
    (880, 905, "Band 8 UL (900 MHz)"),
    (880, 925, "EGPRS 900 (880-925 MHz)"),
]

TSHARK_FIELDS = [
    "frame.time_epoch",
    "wlan.ta",       # transmitter address (addr2)
    "wlan.ra",       # receiver address (addr1)
    "wlan.ssid",     # raw SSID bytes (empty string = wildcard)
    "wlan.fc.type_subtype",
    "wlan_radio.channel",
    "wlan_radio.frequency",
    "wlan_radio.dbm_antsignal",
    "frame.interface_name",
]


class SDRDetector:
    """Passive LTE energy detector using RTL-SDR."""

    def __init__(self, gain=40, ppm_error=0, direct_sampling=True):
        self.gain = gain
        self.ppm_error = ppm_error
        self.direct_sampling = direct_sampling
        self._running = False
        self._detection_queue = []
        self._lock = threading.Lock()
        self._baseline = {}  # freq_MHz -> baseline power
        self._history = {}   # freq_MHz -> deque of recent power readings

    def _check_rtl_sdr(self) -> bool:
        """Verify RTL-SDR device is connected."""
        try:
            result = subprocess.run(
                ["rtl_test", "-t", "-q"],
                capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0 and "Found" in result.stderr
        except Exception:
            return False

    def _build_rtl_power_cmd(self, start_mhz: float, stop_mhz: float, step_hz: int) -> list:
        """Build rtl_power command for scanning a frequency range."""
        cmd = [
            "rtl_power",
            "-f", f"{int(start_mhz*1e6)}:{int(stop_mhz*1e6)}:{step_hz}",
            "-g", str(self.gain),
            "-p", str(self.ppm_error),
        ]
        if self.direct_sampling:
            # RTL-SDR v4: direct sampling is needed for HF/VHF, but 600-900 MHz
            # is in the normal range. Keep it on for better coverage.
            cmd += ["-D", "2"]  # Direct sampling mode 2 (Q-branch)
        cmd += ["-"]
        return cmd

    def _parse_rtl_power_line(self, line: str) -> dict:
        """
        Parse rtl_power CSV output line.
        Format: date,time,lowest_octave,highest_freq,step_hz,bins...
        Each bin is a power reading in dBm.
        """
        parts = line.strip().split(",")
        if len(parts) < 7:
            return None

        date_str = parts[0]
        time_str = parts[1]
        freq_start = int(parts[3])  # Hz
        step_hz = int(parts[4])

        # Parse power bins
        powers = []
        for p in parts[6:]:
            try:
                powers.append(float(p))
            except ValueError:
                powers.append(None)

        # Calculate timestamp from date+time
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            timestamp = dt.replace(tzinfo=timezone.utc).isoformat()
            epoch = dt.timestamp()
        except ValueError:
            timestamp = datetime.now(timezone.utc).isoformat()
            epoch = time.time()

        readings = []
        for i, power_dbm in enumerate(powers):
            if power_dbm is None:
                continue
            freq_mhz = (freq_start + i * step_hz) / 1e6
            readings.append({
                "frequency_mhz": round(freq_mhz, 3),
                "power_dbm": power_dbm,
                "timestamp": timestamp,
                "epoch": epoch,
            })

        return readings

    def _classify_band(self, freq_mhz: float) -> str:
        """Map a frequency to its likely LTE band description."""
        for lo, hi, desc in BAND_MAP:
            if lo <= freq_mhz <= hi:
                return desc
        return "Unknown band"

    def _detect_energy_spike(self, reading: dict, band_name: str) -> dict:
        """
        Check if this reading represents an energy spike above baseline.

        Uses a running baseline (median of recent readings) per frequency bin.
        """
        freq_key = round(reading["frequency_mhz"], 1)

        # Initialize history and baseline
        if freq_key not in self._history:
            self._history[freq_key] = deque(maxlen=BASELINE_WINDOW)
            self._baseline[freq_key] = -100.0  # dBm

        power = reading["power_dbm"]
        history = self._history[freq_key]

        # Calculate baseline from history
        if len(history) >= 10:
            sorted_powers = sorted(history)
            baseline = sorted_powers[len(sorted_powers) // 2]  # median
            self._baseline[freq_key] = baseline

        history.append(power)

        # Check for spike
        delta = power - self._baseline[freq_key]
        if delta >= THRESHOLD_DB:
            return {
                "frequency_mhz": reading["frequency_mhz"],
                "power_dbm": power,
                "baseline_dbm": round(self._baseline[freq_key], 1),
                "delta_db": round(delta, 1),
                "band": band_name,
                "band_description": self._classify_band(reading["frequency_mhz"]),
                "timestamp": reading["timestamp"],
                "epoch": reading["epoch"],
                "type": "lte_energy",
                "confidence_tier": 2,  # Medium — energy spike, not confirmed Flock
            }
        return None

    def start(self):
        """Start the SDR detector in a background thread."""
        if not self._check_rtl_sdr():
            logger.error("RTL-SDR device not found. Is it plugged in?")
            return False

        self._running = True
        logger.info("Starting SDR energy detector on LTE uplink bands")

        def run():
            for band in LTE_BANDS:
                if not self._running:
                    return

                freq_start, freq_stop = band["freq_range"]
                step_hz = RBW_HZ
                cmd = self._build_rtl_power_cmd(
                    start_mhz=freq_start,
                    stop_mhz=freq_stop,
                    step_hz=step_hz,
                )

                logger.info(f"Scanning {band['name']}: {freq_start}-{freq_stop} MHz")

                try:
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1
                    )

                    for line in process.stdout:
                        if not self._running:
                            break

                        readings = self._parse_rtl_power_line(line)
                        if not readings:
                            continue

                        for reading in readings:
                            spike = self._detect_energy_spike(reading, band["name"])
                            if spike:
                                with self._lock:
                                    self._detection_queue.append(spike)
                                logger.info(
                                    f"LTE energy spike: {spike['frequency_mhz']} MHz "
                                    f"(Δ={spike['delta_db']}dB, band={spike['band_description']})"
                                )

                except subprocess.TimeoutExpired:
                    logger.warning(f"Timeout scanning {band['name']}")
                except Exception as e:
                    logger.error(f"Error scanning {band['name']}: {e}")
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()

                # Brief pause between bands
                time.sleep(0.1)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        """Stop the SDR detector."""
        self._running = True
        self._running = False
        if hasattr(self, "_thread"):
            self._thread.join(timeout=5)

    def get_detections(self) -> list:
        """Get and clear the detection queue."""
        with self._lock:
            detections = list(self._detection_queue)
            self._detection_queue.clear()
        return detections


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    detector = SDRDetector()
    if not detector.start():
        print("Failed to start SDR detector")
        sys.exit(1)

    try:
        while True:
            detections = detector.get_detections()
            for d in detections:
                print(json.dumps(d))
            time.sleep(0.1)
    except KeyboardInterrupt:
        detector.stop()
        print("\nStopped")
