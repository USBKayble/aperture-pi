#!/usr/bin/env python3
"""
Aperture — Flock camera wardriver for Raspberry Pi 4 + RTL-SDR v4 + GPS.

This is the sdm setup script that runs inside the image during first boot.
It sets up the Python virtualenv, installs dependencies, and configures
the system.
"""

import os
import subprocess
import sys
from pathlib import Path

APERTURE_DIR = Path("/opt/aperture")
VENV_DIR = APERTURE_DIR / ".venv"


def run(cmd, check=True, env=None):
    """Run a command, streaming output."""
    print(f"  → {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False, env=env)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return result


def main():
    print("=== Aperture Setup ===")

    # Create directories
    for d in [APERTURE_DIR / "data", APERTURE_DIR / "logs"]:
        d.mkdir(parents=True, exist_ok=True)

    # Create virtualenv
    if not VENV_DIR.exists():
        print("Creating Python virtual environment...")
        run(["python3", "-m", "venv", str(VENV_DIR)])

    # Install Python packages
    pip = str(VENV_DIR / "bin" / "pip")
    print("Installing Python packages...")

    # Core packages
    run([pip, "install", "--upgrade", "pip"])
    run([pip, "install",
         "scapy",           # IE fingerprint parsing
         "pyrtlsdr",        # RTL-SDR Python bindings
         "gps3",            # GPSd client
         "flask",           # Web dashboard
         "rich",            # Terminal UI
         "pyshark",         # WiFi frame parsing
         "numpy",           # SDR signal processing
         "matplotlib",      # Graphing (for export)
    ])

    # Install aperture as a package (editable)
    run([pip, "install", "-e", str(APERTURE_DIR / "aperture")])

    # Install bin scripts
    bin_dir = APERTURE_DIR / "bin"
    bin_dir.chmod(0o755)
    for script in bin_dir.iterdir():
        if script.is_file():
            os.symlink(str(script), f"/usr/local/bin/{script.name}")

    # Copy service files
    print("Installing systemd services...")
    for service in Path("/opt/aperture/sdm-hooks").glob("*.service"):
        dest = f"/etc/systemd/system/{service.name}"
        run(["cp", str(service), dest])

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "aperture-monitor"])
    run(["systemctl", "enable", "aperture-web"])

    # Configure gpsd
    print("Configuring gpsd...")
    run(["sudo", "gpsd", "/dev/serial0", "-F", "/var/run/gpsd.sock", "-n"], check=False)
    run(["sudo", "systemctl", "enable", "gpsd.socket"])

    # Configure WiFi AP
    print("Configuring WiFi access point...")
    run(["sudo", "cp", "/opt/aperture/sdm-hooks/hostapd.conf", "/etc/hostapd/hostapd.conf"])
    run(["sudo", "cp", "/opt/aperture/sdm-hooks/dnsmasq.conf", "/etc/dnsmasq.conf"])

    print("\n=== Setup complete! ===")
    print("Reboot or start services manually:")
    print("  sudo systemctl start aperture-monitor")
    print("  sudo systemctl start aperture-web")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Setup failed: {e}", file=sys.stderr)
        sys.exit(1)
