# Aperture — Detection Methodology

## Overview

Aperture uses two independent detection methods to find Flock Safety ALPR cameras:

1. **WiFi probe request sniffing** — captures 802.11 management frames
2. **LTE uplink energy detection** — detects cellular transmission bursts via SDR

## WiFi Detection

### Background

Flock Safety cameras use Quectel BG95-M3 modules for connectivity. Prior to
December 2025, cameras advertised a WiFi management AP (SSID starting with "Flock").
After that, they switched to STA mode and began emitting **wildcard probe requests**
(SSID = empty string) approximately every 125ms, hopping channels 1→6→11.

### Detection Signature

The high-confidence signature (ported from [flock-you](https://github.com/colonelpanichacks/flock-you) dev branch):

1. **Frame type:** 802.11 Management, type=0, subtype=4 (Probe Request)
2. **SSID IE:** Tag 0, length=0 (wildcard — empty SSID)
3. **Transmitter OUI:** addr2 (TA) matches known Flock MAC prefixes
4. **IE Fingerprint:** Specific Information Element fields that are unique to
   Flock hardware (research by Pintor & Atzori, 2022)

### Confidence Tiers

| Tier | Detection Method | Confidence |
|---|---|---|
| 4 | Wildcard probe + OUI + IE fingerprint | **Highest** — confirmed Flock camera |
| 3 | Wildcard probe + OUI only | High — very likely Flock camera |
| 2 | Transmitter OUI match (any frame type) | Medium — possibly Flock |
| 1 | Receiver/BSSID OUI echo (addr1/addr3) | Low — indirect detection, may be false positive |

### OUI List

The OUI (Organizationally Unique Identifier) list contains 40 known Flock MAC
prefixes, sourced from community research:

- `b4:1e:52` — Direct IEEE registration (most reliable)
- `82:6b:f2` — DeFlockJoplin contribution (note: has locally-administered bit set)
- 28 additional prefixes from Flock's supplier/OEM network
- 8 extended battery device prefixes

List is maintained in `config/ouis.json` and updated from community sources.

### IE Fingerprint

The Information Element fingerprint is based on research showing that specific
IE field patterns are unique to Flock hardware. The current implementation
checks for:

- SSID IE (tag 0) with zero length
- Supported Rates IE (tag 1) with specific rate set
- DS Parameter IE (tag 3) with single channel value
- Additional vendor-specific IEs (tag 221) with Flock's OUI

**Note:** Full IE fingerprint parsing requires raw frame capture. The current
implementation uses tshark's parsed fields. A future version will use
`pyshark` for raw frame analysis to enable complete IE fingerprinting.

## LTE Detection

### Background

Flock cameras upload ALPR data and telemetry to Flock's cloud via LTE-M or NB-IoT.
The Quectel BG95-M3 modem transmits on cellular uplink bands when uploading data.
These transmissions are detectable as short energy bursts.

### Supported Bands

The BG95-M3 supports the following **uplink** bands (what we detect):

| Band | Frequency (UL) | Region | RTL-SDR Coverage |
|---|---|---|---|
| B71 | 617–663 MHz | T-Mobile 600 | ✅ |
| B12 | 699–716 MHz | AT&T/T-Mobile 700 | ✅ |
| B13 | 729–746 MHz | Verizon 700 | ✅ |
| B14 | 728–746 MHz | FirstNet 700 | ✅ |
| B20 | 791–821 MHz | European 800 | ✅ |
| B5 | 824–849 MHz | 850 MHz | ✅ |
| B26 | 814–849 MHz | Sprint 850 | ✅ |
| B8 | 880–905 MHz | 900 MHz | ✅ |
| EGPRS | 824/850/900 MHz | GSM/EDGE | ✅ |

**All uplink bands are within the RTL-SDR v4's 24–1766 MHz range.**

### Detection Method

1. **Frequency scanning:** `rtl_power` scans 617–866 MHz and 880–960 MHz
   in 100kHz steps with 10ms integration
2. **Baseline calculation:** Running median of power readings per frequency bin
3. **Spike detection:** Power > baseline + 10dB triggers a detection
4. **Sustained activity:** Requires 2+ consecutive spikes to reduce false positives
5. **Correlation:** LTE spikes within 3 seconds of a WiFi detection boost confidence

### Limitations

- **No demodulation:** We detect energy, not decode LTE frames
- **No cell ID:** We cannot identify which tower/camera is transmitting
- **False positives:** Other LTE devices (phones, IoT) will trigger
- **Mitigation:** WiFi + LTE correlation, GPS clustering, confidence tiers

## GPS Integration

### GPS Source

The GPS6MV2 (NEO-6M) module provides position data via NMEA sentences on UART.
Connected to Pi GPIO pins:
- VCC → 3.3V (Pin 1)
- GND → Ground (Pin 6)
- TX → RXD (Pin 10, GPIO15)
- RX → TXD (Pin 8, GPIO14) — not used

### gpsd

The system uses `gpsd` as the GPS daemon, which:
- Reads NMEA from `/dev/serial0` at 9600 baud
- Serves JSON over TCP port 2947
- Handles GPS hot-plug and re-connection

### GPS Accuracy

- **NEO-6M:** Consumer-grade GPS, ~2.5m CEP accuracy
- **Update rate:** 1Hz (one position per second)
- **Fix types:** Cold (35s), Warm (27s), Hot (<1s)

### GPS in Correlations

- GPS fixes are cached and updated every 500ms
- Detections include the GPS fix at the time of detection
- Stale fixes (>5s old) are not used for geotagging
- **GPS is optional:** Without GPS, detections are logged with timestamp only

## Correlation Engine

The correlator merges detections from WiFi and LTE sources:

```
WiFi Detection (epoch=T) ──┐
                           ├─→ Correlator (3s window) ──→ Database
LTE Spike (epoch=T±Δ) ─────┘
```

**Correlation logic:**
1. New WiFi detection arrives
2. Correlator checks LTE queue for spikes within ±3s window
3. If found: boost tier, mark as "LTE correalted", include LTE band info
4. Get GPS fix (must be <5s old)
5. Dedup by MAC (30s cooldown for same camera)
6. Write to SQLite database + emit to web dashboard
