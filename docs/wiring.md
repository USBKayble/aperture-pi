# Aperture — Hardware Wiring Guide

## Overview

Aperture runs on a Raspberry Pi 4 with three peripherals:

1. **USB WiFi adapter** — for passive 2.4 GHz probe request sniffing
2. **RTL-SDR v4** — for LTE uplink energy detection (600-900 MHz)
3. **NEO-6M GPS** (GPS6MV2) — for geotagging detections

## Wiring Diagram

### GPS6MV2 → Pi 4 GPIO

```
GPS6MV2        Pi 4 GPIO (40-pin header)
--------       -------------------------
VCC    →     Pin 1   (3.3V / 5V — module accepts both)
GND    →     Pin 6   (Ground)
TX     →     Pin 10  (GPIO15 / UART0 RXD)
RX     →     Pin 8   (GPIO14 / UART0 TXD — not used)
PPS    →     (not connected)
```

**Important:** Connect GPS **TX** to Pi **RXD** (Pin 10). The GPS sends data to the Pi, not the other way around.

### USB Peripherals

```
Port   Device
----   ------
USB 2.0  RTL-SDR v4   (bottom port — Pi 4's USB 2.0 ports share bus)
USB 3.0  WiFi adapter (Alfa AWUS036ACS, Panda PAU09, etc.)
```

**Note:** Use USB 2.0 port for RTL-SDR v4 — the Pi 4's USB 3.0 ports can cause noise issues with the SDR. USB 2.0 also provides sufficient bandwidth for 8-bit I/Q at 2.4 MS/s.

### Power

Use a **5V/3A** power supply or a high-capacity USB-C power bank (20,000+ mAh).
The RTL-SDR draws ~250mA, WiFi adapter ~150-300mA, GPS ~30mA.

## GPIO Pinout Reference

```
Pi 4 GPIO (40-pin header, USB ports facing you):

 3.3V(1)  5V(2)
SDA1(3)  5V(4)
SCL1(5)  GND(6)
GP04(7)  GP02(11... wait, let me fix this

Correct pinout (USB sockets at bottom, HDMI at top):
┌─3.3V─(1)──(2)─5V──┐
SDA1─(3)──(4)─5V     │
SCL1─(5)──(6)─GND    │
GP04─(7)──(8)─TXD0   │
     ─(9)──(10)─RXD0  │
GP17─(11)──(12)─GP18 │
GP27─(13)──(14)─GND  │
GP22─(15)──(16)─GP23 │
     ─(17)──(18)─GP24 │
GP10─(19)──(20)─GND  │
GP09─(21)──(22)─GP25 │
GP11─(23)──(24)─GP08 │
     ─(25)──(26)─GP07 │
ID_SD─(27)──(28)─ID_SC │
GP05─(29)──(30)─GND  │
GP06─(31)──(32)─GP12 │
GP13─(33)──(34)─GND  │
GP19─(35)──(36)─GP16 │
GP26─(37)──(38)─GP20 │
     ─(39)──(40)─GP21 │
└────────────────────────┘
```

### Serial Port Configuration

1. **Disable serial console** (frees UART for GPS):
   ```bash
   sudo raspi-config
   # Interface Options → Serial → "No" (to login shell)
   # Interface Options → Serial → "Yes" (to serial port hardware)
   ```

2. **Verify UART is enabled** in `/boot/config.txt`:
   ```
   enable_uart=1
   ```

3. **Test GPS output:**
   ```bash
   cat /dev/serial0
   # Should show NMEA sentences: $GPGGA, $GPRMC, etc.
   ```

4. **Start gpsd:**
   ```bash
   sudo systemctl enable gpsd.socket
   sudo systemctl restart gpsd.socket
   cgps -s  # Test GPS data
   ```

## WiFi Adapter Compatibility

Tested working (monitor mode + packet injection):
- Alfa AWUS036ACS (recommended — dual band, good sensitivity)
- Alfa AWUS036ACM (dual band, AC1200)
- Panda PAU09 (2.4 GHz only, but reliable)
- TP-Link Archer T2U Plus (dual band)

**Not recommended:** The Pi's onboard WiFi — it can work but is less sensitive
and shares the PCIe bus with the USB controller, causing contention with the SDR.

## Antenna Recommendations

### WiFi
- 2.4 GHz + 5 GHz dual-band antenna (if using dual-band adapter)
- 2 dBi rubber duck is fine for close-range; 5 dBi panel for longer range

### SDR (RTL-SDR v4)
- **Broadband antenna:** "Boat stick" discone (25-1300 MHz) — good general coverage
- **LTE-specific:** 700-900 MHz yagi or log-periodic for directional hunting
- **Ground plane:** Needed for omni antennas — 4x wires ~6.5cm long

### GPS
- **Active GPS antenna** (with preamp) — strongly recommended
- The NEO-6M's ceramic patch antenna works indoors near windows but is poor in a vehicle
- Active antennas with 3m USB extension cables work well on car windshields
