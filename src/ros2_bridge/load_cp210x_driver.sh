#!/usr/bin/env bash
set -u

DRIVER="${1:-/home/user/cp210x.ko}"

echo "[1/6] kernel:"
uname -r

echo
echo "[2/6] driver info: ${DRIVER}"
if [ -f "${DRIVER}" ]; then
  modinfo "${DRIVER}" | grep -E "filename|vermagic|alias" || true
else
  echo "missing driver file: ${DRIVER}"
  exit 1
fi

echo
echo "[3/6] load usbserial"
sudo modprobe usbserial

echo
echo "[4/6] load cp210x"
if lsmod | grep -q "^cp210x"; then
  echo "cp210x already loaded"
else
  sudo insmod "${DRIVER}"
fi

echo
echo "[5/6] recent kernel log"
dmesg -T | grep -Ei "cp210|10c4|ea60|ttyUSB|usbserial|invalid|error|Unknown" | tail -n 100 || true

echo
echo "[6/6] serial devices"
lsmod | grep -E "cp210x|usbserial" || true
ls -l /dev/ttyUSB* 2>/dev/null || true
ls -l /dev/serial/by-id/ 2>/dev/null || true
