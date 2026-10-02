#!/bin/sh
# Copy the project to a Raspberry Pi and install it. Run ON YOUR COMPUTER:
#   ./deploy.sh pi@192.168.1.15          (installs into ~/leds on the Pi)
#   ./deploy.sh pi@192.168.1.15 ledstrip (installs into ~/ledstrip instead)
# The Pi's own leds.conf is kept, so each Pi keeps its own LED numbers.
set -e

if [ -z "$1" ]; then
    echo "Usage: $0 user@pi-address [folder-on-pi]" >&2
    exit 1
fi
TARGET=$1
REMOTE_DIR=${2:-leds}
cd "$(dirname "$0")"

echo "==> Copying files to $TARGET:~/$REMOTE_DIR"
ssh "$TARGET" "mkdir -p ~/$REMOTE_DIR"
scp -q leds.py leds.conf.example install.sh switch_scan.py "$TARGET:$REMOTE_DIR/"

echo "==> Installing (you may be asked for the Pi's sudo password)"
ssh -t "$TARGET" "sudo sh ~/$REMOTE_DIR/install.sh"
