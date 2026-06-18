#!/bin/bash
set -e

echo "=== AI DevOps - Encrypted Docker Volume Setup ==="
echo "This script creates an encrypted Docker volume for PostgreSQL."
echo ""

VOLUME_NAME="enterprise-postgres-data"
ENCRYPTED_DIR="/docker/encrypted-volumes/postgres"
KEY_FILE="/docker/encrypted-volumes/postgres-key"

detect_platform() {
    if command -v cryptsetup &>/dev/null; then
        echo "linux"
    elif command -v bitlocker &>/dev/null || command -v manage-bde &>/dev/null; then
        echo "windows"
    else
        echo "unknown"
    fi
}

setup_linux_luks() {
    echo "[Linux] Setting up LUKS-encrypted volume..."
    mkdir -p "$(dirname "$KEY_FILE")" "$ENCRYPTED_DIR"

    if [ ! -f "$KEY_FILE" ]; then
        dd if=/dev/urandom bs=32 count=1 of="$KEY_FILE" 2>/dev/null
        echo "[Linux] Generated encryption key at $KEY_FILE"
    fi

    IMG_FILE="${ENCRYPTED_DIR}.img"
    if [ ! -f "$IMG_FILE" ]; then
        echo "[Linux] Creating 10GB encrypted backing file..."
        dd if=/dev/zero bs=1M count=10240 of="$IMG_FILE" 2>/dev/null
        LOOP_DEV=$(losetup -f --show "$IMG_FILE")
        echo "[Linux] Using loop device $LOOP_DEV"

        cryptsetup luksFormat "$LOOP_DEV" --key-file "$KEY_FILE"
        cryptsetup open "$LOOP_DEV" postgres-enc --key-file "$KEY_FILE"
        mkfs.ext4 /dev/mapper/postgres-enc
        mount /dev/mapper/postgres-enc "$ENCRYPTED_DIR"
        echo "[Linux] Encrypted filesystem mounted at $ENCRYPTED_DIR"
    fi

    if ! mountpoint -q "$ENCRYPTED_DIR" 2>/dev/null; then
        LOOP_DEV=$(losetup -f --show "$IMG_FILE")
        cryptsetup open "$LOOP_DEV" postgres-enc --key-file "$KEY_FILE"
        mount /dev/mapper/postgres-enc "$ENCRYPTED_DIR"
    fi

    echo "[Linux] Creating Docker volume pointing to encrypted mount..."
    docker volume create --driver local --opt type=none \
        --opt device="$ENCRYPTED_DIR" \
        --opt o=bind "$VOLUME_NAME" 2>/dev/null || true

    echo "[Linux] Volume '$VOLUME_NAME' ready."
    echo "[Linux] To use, add to docker-compose:"
    echo "  volumes:"
    echo "    - $VOLUME_NAME:/var/lib/postgresql/data"
}

setup_windows_bitlocker() {
    echo "[Windows] Detected. Recommend BitLocker on the drive hosting Docker volumes."
    echo "[Windows] Run: manage-bde -on C: -used"
    echo ""
    echo "[Windows] For Docker Desktop WSL2 backend, encrypt the WSL2 VHD:"
    echo "  1. wsl --shutdown"
    echo "  2. manage-bde -on <path-to-ext4.vhdx>"
    echo ""
    echo "[Windows] Fallback: Use Docker volume with Windows DPAPI-NG encryption:"
    docker volume create "$VOLUME_NAME"
    echo "[Windows] Volume '$VOLUME_NAME' created (rely on host-level BitLocker)."
}

case "$(detect_platform)" in
    linux)
        if [ "$(id -u)" -ne 0 ]; then
            echo "This script must be run as root on Linux."
            exit 1
        fi
        setup_linux_luks
        ;;
    windows)
        setup_windows_bitlocker
        ;;
    *)
        echo "Could not detect platform. Creating unencrypted volume as fallback."
        echo "WARNING: Ensure host-level disk encryption (LUKS/BitLocker/FileVault) is enabled."
        docker volume create "$VOLUME_NAME"
        ;;
esac

echo ""
echo "=== Done ==="
echo "PostgreSQL data volume: $VOLUME_NAME"
echo "Encryption status: $(docker volume inspect "$VOLUME_NAME" --format '{{.Driver}}')"
