# Aperture Usage Guide

## Quick Start

### After imaging the SD card:
1. Insert SD card into Pi 4
2. Connect WiFi adapter to USB 3.0 port
3. Connect RTL-SDR v4 to USB 2.0 port
4. Connect GPS6MV2 to GPIO pins (1, 6, 8, 10)
5. Connect active GPS antenna
6. Power on with 5V/3A adapter or power bank

### First boot (takes 1-2 minutes):
```bash
# System starts automatically
# Connect to WiFi AP: aperture-wardrive (no password)
# Browse to: http://10.42.42.1:8080
```

### Check status:
```bash
# SSH in (if enabled in image)
ssh aperture@10.42.42.1
# Password: raspberry

# Watch live detections
tail -f /opt/aperture/logs/aperture-$(date +%Y%m%d).log

# Check system status
aperture-status
```

## Web Dashboard

| Tab | Description |
|---|---|
| **Map** | Live map with detection markers (click to see details) |
| **List** | Table of all detections (sortable) |
| **Stats** | Statistics: total, unique cameras, tier breakdown |
| **System** | WiFi, SDR, GPS status |

### Map Colors
- 🟢 Green — Tier 4 (WiFi probe + OUI + IE fingerprint) — highest confidence
- 🔵 Blue — Tier 3 (WiFi probe + OUI)
- 🟡 Yellow — Tier 2 (WiFi OUI or LTE energy spike)
- 🔴 Red — Tier 1 (WiFi echo / low confidence)

### Export Options
- **KML** — Google Earth (colored by tier)
- **CSV** — Spreadsheet analysis
- **GPX** — GPS waypoints for other tools

## Command Line

```bash
# Start/stop the wardriver
sudo systemctl start aperture-monitor
sudo systemctl stop aperture-monitor
sudo systemctl status aperture-monitor

# Start/stop the dashboard
sudo systemctl start aperture-web
sudo systemctl status aperture-web

# Manual run (for debugging)
python3 /opt/aperture/aperture/src/main.py

# View live detections
python3 /opt/aperture/aperture/src/main.py --tail

# Check GPS
cgps -s
```

## Detection Workflow

```
[WiFi Camera] → Probe Request → tshark → OUI + IE Check → Detection
[RTL-SDR]     → LTE Energy    → rtl_power → Spike Detection → Detection
                                           ↓
                                   Correlator (3s window)
                                           ↓
                                  SQLite + Web Dashboard
```

A detection is logged when:
1. WiFi probe request matches Flock OUI + wildcard SSID, OR
2. LTE energy spike detected on cellular uplink band, OR
3. Both methods correlate within 3 seconds (confidence boost)

## Field Operations

### Before going out:
1. Ensure GPS has satellite lock (wait 30-60 seconds outside)
2. Verify RTL-SDR is detected: `rtl_test -t`
3. Verify WiFi adapter is in monitor mode: `iw wlan1 info`
4. Check web dashboard loads on phone: `http://10.42.42.1:8080`

### During wardriving:
- The dashboard updates in real-time
- New detections appear as colored markers on the map
- Audio alerts: none yet (planned for v2)
- Detection count shown on OLED/status page

### After the drive:
- Export KML/CSV from the web dashboard
- Database is at `/opt/aperture/data/detections.db`
- Logs are at `/opt/aperture/logs/`

## Troubleshooting

### GPS not working
```
# Check if gpsd sees the device
cgps -s

# If no data, check serial port
sudo cat /dev/serial0 | head -5
# Should show $GPGGA/$GPRMC lines

# Ensure serial console is disabled
sudo raspi-config → Interface Options → Serial → No
```

### RTL-SDR not detected
```
# Test the device
rtl_test -t

# If "No supported devices found":
# - Check USB cable/power
# - Try a powered USB hub
# - Ensure you're using USB 2.0 port
```

### WiFi not capturing probes
```
# Check monitor mode
iw wlan1 info
# Should show "type monitor"

# Check tshark sees frames
sudo tshark -i wlan1 -c 5 -Y "wlan.fc.type_subtype == 0x04"
# Should show probe requests (may need to wait for nearby WiFi devices)
```

### Dashboard not loading
```
# Check service
sudo systemctl status aperture-web

# Check port
ss -tlnp | grep 8080

# Check logs
journalctl -u aperture-web -f
```
