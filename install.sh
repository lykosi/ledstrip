#!/bin/sh
# Sets up the LED strip service on a Raspberry Pi. Run ON THE PI from the folder
# holding leds.py:   sudo sh install.sh
# Safe to run again (e.g. after updating leds.py); your leds.conf is never overwritten.
set -e

if [ "$(id -u)" != 0 ]; then
    echo "Please run with sudo: sudo sh $0" >&2
    exit 1
fi

DIR=$(cd "$(dirname "$0")" && pwd)
USER_NAME=${SUDO_USER:-$(stat -c %U "$DIR")}
REBOOT=no

echo "==> Installing packages"
apt-get install -y -qq python3-spidev python3-gpiozero python3-lgpio >/dev/null

echo "==> Config file"
if [ -f "$DIR/leds.conf" ]; then
    echo "    keeping existing $DIR/leds.conf"
else
    cp "$DIR/leds.conf.example" "$DIR/leds.conf"
    chown "$USER_NAME": "$DIR/leds.conf"
    echo "    created $DIR/leds.conf from the example"
fi
chmod +x "$DIR/leds.py"

echo "==> Boot settings (SPI on, stable core clock, big SPI buffer)"
BOOT=/boot/firmware
[ -f $BOOT/config.txt ] || BOOT=/boot
if ! grep -q "^dtparam=spi=on" $BOOT/config.txt; then
    cp -n $BOOT/config.txt $BOOT/config.txt.bak-leds
    printf "\n[all]\n# LED strip (leds.service)\ndtparam=spi=on\ncore_freq=250\n" >> $BOOT/config.txt
    REBOOT=yes
fi
if ! grep -q "spidev.bufsiz" $BOOT/cmdline.txt; then
    cp -n $BOOT/cmdline.txt $BOOT/cmdline.txt.bak-leds
    sed -i "1 s/\$/ spidev.bufsiz=65536/" $BOOT/cmdline.txt
    REBOOT=yes
fi
[ -e /dev/spidev0.0 ] || REBOOT=yes   # settings present but not active yet
usermod -aG spi,gpio "$USER_NAME"

echo "==> Service (runs as $USER_NAME from $DIR)"
cat > /etc/systemd/system/leds.service <<EOF
[Unit]
Description=LED strip controlled by 4-position switch

[Service]
User=$USER_NAME
ExecStart=/usr/bin/python3 $DIR/leds.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q leds.service

if [ $REBOOT = yes ]; then
    echo "==> Done. Boot settings changed, rebooting in 5 seconds (Ctrl+C to cancel)..."
    sleep 5
    reboot
else
    systemctl restart leds.service
    echo "==> Done. Service restarted. Logs: journalctl -u leds -f"
fi
