#!/usr/bin/env bash
set -euo pipefail

#
# build.sh — One-command image builder for Aperture wardriver
#
# Prerequisites:
#   - sdm installed: https://github.com/gitbls/sdm
#   - sudo privileges
#   - ~4GB free disk space
#
# Usage:
#   ./build.sh
#
# Output: deploy/aperture-pi.img.gz
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMG_NAME="aperture-pi"
IMG_VERSION="1.0.0"
PI_OS_URL="https://downloads.raspberrypi.org/rpd-x86/piper-20250127-v1.iso"
PI_OS_LITE_URL="https://github.com/raspberrypi-pi-gen/images/releases/download/20240704T112324Z/2024-70-raspios-bookworm-arm64-lite.img.xz"
DEPLOY_DIR="${SCRIPT_DIR}/deploy"
WORK_DIR="${SCRIPT_DIR}/work"
CONFIG_DIR="${SCRIPT_DIR}/sdm-hooks"
APERTURE_DIR="${SCRIPT_DIR}/aperture"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[build]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
err() { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

# Check dependencies
check_deps() {
    for cmd in sdm qemu-system-aarch64 unzip xz; do
        if ! command -v "$cmd" &>/dev/null; then
            err "$cmd not found. Install it first."
        fi
    done
}

# Download RPi OS Lite if not present
download_os() {
    local img="${WORK_DIR}/raspios-lite.img"
    if [ -f "$img" ]; then
        warn "RPi OS Lite image already exists, skipping download"
        return
    fi

    # First decompress if .xz exists
    if [ -f "${WORK_DIR}/raspios-lite.img.xz" ]; then
        log "Decompressing RPi OS Lite..."
        xz -d "${WORK_DIR}/raspios-lite.img.xz"
        return
    fi

    log "Downloading RPi OS Lite (this may take a while)..."
    mkdir -p "$WORK_DIR"
    # Use a known-good RPi OS Lite image
    curl -L -o "${WORK_DIR}/raspios-lite.img.xz" "$PI_OS_LITE_URL"
    log "Decompressing..."
    xz -d "${WORK_DIR}/raspios-lite.img.xz"
}

# Build the image using sdm
build_image() {
    local base_img="${WORK_DIR}/raspios-lite.img"
    local out_img="${DEPLOY_DIR}/${IMG_NAME}.img"
    local out_img_gz="${DEPLOY_DIR}/${IMG_NAME}.img.gz"

    mkdir -p "$DEPLOY_DIR"

    if [ -f "$out_img" ] || [ -f "$out_img_gz" ]; then
        warn "Existing image found, removing..."
        rm -f "$out_img" "$out_img_gz"
    fi

    log "Building Aperture image with sdm..."

    # sdm --expand adds boot and root partitions, expands root FS
    # sdm --copy copies files from config dirs into the image
    # sdm --install installs packages
    # sdm --enable enables services
    # sdm --with-boot-config writes config.txt and cmdline.txt

    sdm \
        --image "$base_img" \
        --deploy-dir "$DEPLOY_DIR" \
        --hostname "aperture" \
        --password "raspberry" \
        --username "aperture" \
        --ssh-password-access \
        --expand \
        --copy "${CONFIG_DIR}/etc:etc" \
        --copy "${APERTURE_DIR}:/opt/aperture" \
        --install "tshark,rtl-sdr,gpsd,gpsd-clients,hostapd,dnsmasq" \
        --pip-install "scapy,pyrtlsdr,gps3,flask,rich,pyshark" \
        --enable "aperture-wifi,aperture-sdr,aperture-gps,aperture-web,aperture-monitor,gpsd,hostapd,dnsmasq" \
        --with-boot-config "${CONFIG_DIR}/boot/config.txt:${CONFIG_DIR}/boot/cmdline.txt" \
        --name "$IMG_NAME" \
        --compress

    log "Image built successfully!"
    log "Output: ${DEPLOY_DIR}/${IMG_NAME}.img.gz"
}

# Print instructions
show_instructions() {
    echo ""
    cat << 'INSTRUCTIONS'
=====================================================================
  Aperture image built successfully!

  To flash to SD card:
    gunzip -c deploy/aperture-pi.img.gz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync

  After first boot:
    - Connect to WiFi AP: aperture-wardrive (no password)
    - Dashboard: http://10.42.42.1:8080
    - SSH: ssh aperture@10.42.42.1 (password: raspberry)

  Wiring:
    NEO-6M GPS → Pi GPIO pins 1, 6, 8, 10
    RTL-SDR v4 → USB 2.0 port (use USB 2.0, not 3.0 — power issues)
    WiFi adapter → USB 3.0 port

INSTRUCTIONS
}

main() {
    log "Starting Aperture image build..."
    log "Version: ${IMG_VERSION}"

    check_deps
    download_os
    build_image
    show_instructions
}

main "$@"
