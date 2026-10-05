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
apt-get update -qq
apt-get install -y -qq python3-spidev python3-gpiozero >/dev/null
# lgpio is the GPIO backend on current Raspberry Pi OS. Older releases don't
# package it, so fall back to RPi.GPIO there (gpiozero picks whichever exists).
if apt-get install -y -qq python3-lgpio >/dev/null 2>&1; then
    echo "    GPIO backend: lgpio"
else
    apt-get install -y -qq python3-rpi.gpio >/dev/null
    echo "    python3-lgpio not available on this OS, using RPi.GPIO instead"
fi

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
CFG=$BOOT/config.txt
MODEL=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || true)
echo "    board: ${MODEL:-unknown}"

# Adds a line to config.txt if it is missing, under an [all] section of our own
add_boot_line() {
    if ! grep -qx "$1" $CFG; then
        cp -n $CFG $CFG.bak-leds
        grep -qx "# LED strip (leds.service)" $CFG || printf "\n[all]\n# LED strip (leds.service)\n" >> $CFG
        echo "$1" >> $CFG
        REBOOT=yes
    fi
}

add_boot_line "dtparam=spi=on"
# The SPI clock follows the core clock, which the Pi changes with load.
# Pi 4 / 400 / CM4 need it fixed at 500 MHz, older boards at 250 MHz.
case "$MODEL" in
    *"Raspberry Pi 4"* | *"Raspberry Pi 400"* | *"Compute Module 4"*)
        add_boot_line "core_freq=500"
        add_boot_line "core_freq_min=500"
        ;;
    *)
        add_boot_line "core_freq=250"
        ;;
esac

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
Description=LED strip controlled by a rotary switch and encoder

[Service]
User=$USER_NAME
ExecStart=/usr/bin/python3 $DIR/leds.py run
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q leds.service

echo "==> Command line tool: leds (try: leds help)"
cat > /usr/local/bin/leds <<EOF
#!/bin/sh
exec /usr/bin/python3 $DIR/leds.py "\$@"
EOF
chmod 755 /usr/local/bin/leds

if [ $REBOOT = yes ]; then
    echo "==> Done. Boot settings changed, rebooting in 5 seconds (Ctrl+C to cancel)..."
    sleep 5
    reboot
else
    systemctl restart leds.service
    echo "==> Done. Service restarted. Logs: journalctl -u leds -f"
fi
