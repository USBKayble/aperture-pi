# Aperture

Headless Flock camera wardriver for Raspberry Pi 4 + RTL-SDR v4 + GPS6MV2 (NEO-6M).

Detects Flock Safety ALPR cameras via two independent methods:
1. **WiFi probe-request sniffing** — passive 2.4 GHz, OUI + IE fingerprinting
2. **LTE uplink energy detection** — RTL-SDR monitors cellular bands (700/850/900 MHz)

Correlates detections with GPS position, logs to SQLite, serves a live web dashboard.

## Hardware

| Component | Model |
|---|---|
| SBC | Raspberry Pi 4 (any RAM) |
| WiFi | USB adapter supporting monitor mode (Alfa AWUS036ACS, Panda PAU09) |
| SDR | RTL-SDR v4 (R820T2) |
| GPS | GPS6MV2 / GY-NEO6MV2 (u-blox NEO-6M, UART) |
| Power | 5V/3A USB-C power bank or adapter |
| Case | Apache 2000 series (or any Pi case with USB ports accessible) |

## Quick Start

```bash
# On your Linux build machine (not the Pi):
./build.sh
# This downloads RPi OS Lite, runs sdm to install all deps and config,
# and produces aperture-pi.img.gz in the deploy/ directory.

# Flash to SD card:
gunzip -c deploy/aperture-pi.img.gz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync

# Boot the Pi, connect to WiFi AP "aperture-wardrive" (no password)
# Open http://10.42.42.1:8080
```

## Software Architecture

```
aperture/
├── bin/                    # CLI entry points
├── src/                    # Detection + dashboard code
│   ├── wifi_scanner.py     # tshark-based WiFi probe request sniffer
│   ├── sdr_detector.py     # RTL-SDR energy detection on LTE bands
│   ├── gps_handler.py      # gpsd → lat/lon/alt
│   ├── correlator.py       # Merges detections, assigns confidence tiers
│   ├── database.py         # SQLite persistence
│   └── dashboard.py        # Flask web UI
├── config/                 # OUI lists, signatures, settings
├── data/                   # Detections database, logs
├── static/                 # Web UI CSS/JS
├── templates/              # Web UI HTML
└── sdm-hooks/              # Pre/post-install scripts for sdm
```

## Detection Methods

### WiFi (Primary)

Passive 2.4 GHz sniffing via tshark on monitor-mode USB WiFi adapter.
Channel hopping: 1, 6, 11 at 250ms dwell.

**Detection signature:**
- 802.11 Management, type=0 subtype=4 (Probe Request)
- SSID Information Element (tag 0) with length=0 (wildcard)
- `addr2` (transmitter) matches known Flock OUI list
- **IE fingerprint** — specific Information Element fields unique to Flock hardware

Confidence tiers:
- Tier 4: Wildcard probe + OUI + IE fingerprint (highest)
- Tier 3: Wildcard probe + OUI only
- Tier 2: Transmitter OUI on any frame
- Tier 1: Receiver/BSSID OUI echo (noisier)

### LTE SDR (Secondary)

RTL-SDR v4 tuned to Flock camera cellular uplink bands:
- Band 28: 703-733 MHz (700 MHz, North America)
- Band 8: 880-905 MHz (900 MHz, AT&T/T-Mobile)
- Band 26: 814-849 MHz (850 MHz, Verizon)
- Band 71: 617-663 MHz (600 MHz, T-Mobile low-band)

**Method:** Continuous power measurement via `rtl_power`. Detects energy spikes
>10dB above baseline noise floor, timestamped and correlated with GPS position.

### GPS

NEO-6M module wired to Pi GPIO UART:
- VCC → Pin 1 (3.3V)
- GND → Pin 6 (GND)
- TX → Pin 10 (GPIO15/RXD)
- RX → Pin 8 (GPIO14/TXD, not used)

`gpsd` receives NMEA sentences at 9600 baud.

## First Boot

1. Flash image to SD card (32GB+ recommended)
2. Insert SD card, connect USB WiFi adapter, connect RTL-SDR
3. Power up (external antenna for GPS recommended, near a window)
4. Connect phone/laptop to WiFi AP `aperture-wardrive` (no password)
5. Browse to `http://10.42.42.1:8080`
6. Wait ~30s for GPS to acquire fix (LED blinks green when fixed)

## Web Dashboard

- Live map with detection markers (Leaflet.js)
- Detection list with timestamps, MAC, RSSI, confidence tier
- Export to KML, CSV, GPX
- System status (WiFi, SDR, GPS, battery)

## License

MIT — for research and educational use only.
