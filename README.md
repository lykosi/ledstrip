# ledstrip

A Raspberry Pi turns part of a WS2812B LED strip on in a different color for each
position of a 4-position rotary switch. When you turn the switch, the whole strip
shows a moving rainbow for a moment, then only the selected section stays lit.

| Switch position | LEDs lit (example) | Color  |
|-----------------|--------------------|--------|
| 1               | 0 – 9              | white  |
| 2               | 10 – 19            | green  |
| 3               | 20 – 29            | orange |
| 4               | 30 – 39            | red    |

LED ranges, colors, brightness and rainbow timing are set in a plain text file,
`leds.conf`. Changes apply within a second of saving, with no restart needed.
Each Pi has its own `leds.conf`, so strips of different lengths work with the same code.

## Parts

- Raspberry Pi (tested on a Pi Zero 2 W, Raspberry Pi OS Trixie). Any Pi with a 40-pin header should work.
- WS2812B / NeoPixel LED strip (3 wires: 5V, GND, DIN)
- 5V power supply for the strip, sized for it (see [Power](#power))
- 4-position rotary switch (for example an LW26-20 cam switch)
- Optional: 74AHCT125 level shifter (see [Troubleshooting](#troubleshooting))

## Wiring

> Wire everything with the power off.

| From | To Pi | Header pin |
|---|---|---|
| LED strip **DIN** | **GPIO10** (SPI MOSI) | pin 19 |
| LED strip **GND** | **GND** | pin 20 |
| Switch position 1 | **GPIO5** | pin 29 |
| Switch position 2 | **GPIO6** | pin 31 |
| Switch position 3 | **GPIO13** | pin 33 |
| Switch position 4 | **GPIO19** | pin 35 |
| Switch common | **GND** | pin 39 |
| LED strip **5V** | external 5V supply **+** | – |
| External supply **−** | LED strip GND (and so also Pi GND) | – |

For the TAISS LW26-20 0-4/2 switch, see [the switch](#the-switch) for which terminal is
which.

```
                       Raspberry Pi 40-pin header
         (pin 1 has a square solder pad on the back of the board;
          on a Pi Zero it is at the SD-card end, on a full-size Pi
          at the end away from the USB ports. Run `pinout` on the Pi
          to print this drawing for your exact board.)

                       3V3  (1) (2)  5V
                     GPIO2  (3) (4)  5V
                     GPIO3  (5) (6)  GND
                     GPIO4  (7) (8)  GPIO14
                       GND  (9) (10) GPIO15
                    GPIO17 (11) (12) GPIO18
                    GPIO27 (13) (14) GND
                    GPIO22 (15) (16) GPIO23
                       3V3 (17) (18) GPIO24
   LED strip DIN ── GPIO10 (19) (20) GND ──── LED strip GND
                     GPIO9 (21) (22) GPIO25
                    GPIO11 (23) (24) GPIO8
                       GND (25) (26) GPIO7
                     GPIO0 (27) (28) GPIO1
 Switch position 1 ─ GPIO5 (29) (30) GND      (switch terminal 1)
 Switch position 2 ─ GPIO6 (31) (32) GPIO12   (switch terminal 3)
 Switch position 3 ─ GPIO13 (33) (34) GND     (switch terminal 5)
 Switch position 4 ─ GPIO19 (35) (36) GPIO16  (switch terminal 7)
                    GPIO26 (37) (38) GPIO20
   Switch common ──── GND (39) (40) GPIO21    (switch terminals 2 + 6)
```

```
  5V power supply                         LED strip
  ┌────────────┐                    ┌──────────────────────
  │        +5V ├────────────────────┤ 5V
  │        GND ├──────────┬─────────┤ GND
  └────────────┘          │    ┌────┤ DIN
                          │    │    └──────────────────────
                        Pi GND  Pi GPIO10
                       (pin 20) (pin 19)

   TAISS LW26-20 0-4/2 switch             Pi
  ┌──────────────────────────┐
  │ terminal 2 ──┐           │
  │              ├── linked ─┼──────── GND     (pin 39)
  │ terminal 6 ──┘           │
  │ terminal 1 (position 1) ─┼──────── GPIO5   (pin 29)
  │ terminal 3 (position 2) ─┼──────── GPIO6   (pin 31)
  │ terminal 5 (position 3) ─┼──────── GPIO13  (pin 33)
  │ terminal 7 (position 4) ─┼──────── GPIO19  (pin 35)
  │ terminals 4, 8: unused   │
  └──────────────────────────┘
```

### The switch

The Pi uses its internal pull-up resistors, so no extra resistors are needed. A switch
position counts as selected when its pin is connected to GND. If no position is
connected (for example an "off" position on the switch), all LEDs turn off.

**LW26-20 cam switch:** it has numbered contact pairs (1-2, 3-4, 5-6, 7-8, …), and
which pair closes in which position depends on the exact model. Find out with a
multimeter in continuity (beep) mode:

1. Turn the switch to position 1 and find the contact pair that beeps.
2. Wire one side of that pair to GND (pin 39) and the other side to GPIO5 (pin 29).
3. Repeat for positions 2, 3 and 4 with GPIO6 (pin 31), GPIO13 (pin 33) and GPIO19 (pin 35).

The GND sides of all pairs can be linked together with short jumper wires.

**TAISS LW26-20 0-4/2 (5 positions: off + 4, 8 terminals)** — measured wiring.
Terminals 2 and 4 are permanently connected inside the switch, and so are 6 and 8;
these are the common terminals. Each on-position connects one of 1, 3, 5 or 7 to
its common:

| Switch terminal | To Pi | Header pin |
|---|---|---|
| 2 and 6 (linked together) | GND | pin 39 |
| 1 | GPIO5 | pin 29 |
| 3 | GPIO6 | pin 31 |
| 5 | GPIO13 | pin 33 |
| 7 | GPIO19 | pin 35 |

Make sure the four GPIO wires sit in the same row (pins 29, 31, 33, 35) and not on the
GND pins next to them (30, 34).

Terminals 4 and 8 stay unused. Position 0 connects nothing, so the LEDs are off. If
the colors come in the wrong order as you turn the knob, reorder `switch_pins` in
`leds.conf`.

**No multimeter, or the switch doesn't behave as expected?** Let the Pi map it. Wire
each switch terminal to its own GPIO (and nothing to GND):

| Terminal | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| GPIO | GPIO17 | GPIO27 | GPIO22 | GPIO23 | GPIO24 | GPIO25 | GPIO12 | GPIO16 |
| Header pin | 11 | 13 | 15 | 16 | 18 | 22 | 32 | 36 |

Then run `python3 ~/leds/switch_scan.py 17 27 22 23 24 25 12 16` and turn the switch
slowly. Press Ctrl+C when done, and remove these wires again afterwards. It prints which terminals are connected in each position, for example
`connected: 1-2   5-6`.

> Use the switch for this low-voltage signal only. Never mix mains wiring onto the same switch.

### Power

Don't power the strip from the Pi's 5V pin except for a handful of LEDs. Each LED
draws up to about 60 mA at full white, so 100 LEDs can need up to 6 A. The
`brightness` setting scales that down. Always connect the supply's GND to the Pi's
GND so the data signal has a common reference.

## Installation

### 1. Prepare the Pi

1. Flash **Raspberry Pi OS Lite** with [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
   In the settings, set a username (for example `pi`), Wi-Fi and **enable SSH**.
2. Boot it, find its IP address (from your router, or try `ping raspberrypi.local`).
3. From your computer, set up key login once (optional, but you won't have to type the password each time):
   ```sh
   ssh-copy-id pi@192.168.1.15
   ```

### 2. Deploy

From this folder on your computer:

```sh
./deploy.sh pi@192.168.1.15
```

This copies the files to `~/leds` on the Pi and runs `install.sh` there. That script:

- installs the needed packages (`python3-spidev`, `python3-gpiozero`, `python3-lgpio`)
- creates `leds.conf` from `leds.conf.example` (only the first time)
- enables SPI and fixes the core clock in the boot config (backups saved as `*.bak-leds`)
- installs and starts the `leds` service so it runs at every boot
- reboots the Pi if the boot config changed (only on the first install)

Run the same command again whenever you change `leds.py`. The Pi's `leds.conf` is
never overwritten.

**Manual install without `deploy.sh`:** copy `leds.py`, `leds.conf.example` and
`install.sh` into a folder on the Pi, then run `sudo sh install.sh` in that folder.

## Configuration

Edit the config on the Pi:

```sh
ssh pi@192.168.1.15
nano ~/leds/leds.conf
```

```ini
led_count = 60          # total LEDs on the strip
brightness = 50         # percent, 1-100

# positionN = FIRST-LAST COLOR   (LED numbers start at 0, both ends included)
position1 = 0-9 white
position2 = 10-19 green
position3 = 20-29 orange
position4 = 30-39 red

rainbow_seconds = 2     # how long the rainbow plays after turning the switch
rainbow_speed = 1       # rainbow turns per second

switch_pins = 5 6 13 19 # GPIO numbers for positions 1-4
color_order = GRB       # WS2812B is GRB; try RGB if red and green are swapped
```

Colors can be a name (`white green orange red blue yellow purple cyan pink off`) or
`R,G,B` numbers from 0 to 255, for example `position3 = 20-29 255,80,0`.

Save the file and the strip updates within a second. If the file has a mistake, the
previous settings stay active and the error appears in the log.

### Finding the LED numbers

Set `led_count` higher than the real number of LEDs, then:

```sh
sudo systemctl stop leds
python3 ~/leds/leds.py identify
```

LEDs 0, 10, 20, … light **red**, LEDs 5, 15, 25, … light **green**, and the rest
dim blue. Count along the strip to pick your ranges. The last LED that lights up
gives you `led_count`. Press Ctrl+C, then:

```sh
sudo systemctl start leds
```

## Useful commands

```sh
journalctl -u leds -f          # live log (shows switch positions and config errors)
sudo systemctl restart leds    # restart
sudo systemctl stop leds       # stop (LEDs turn off)
sudo systemctl disable leds    # don't start at boot
```

Before the switch is wired, you can test a position by briefly connecting GPIO5, GPIO6,
GPIO13 or GPIO19 (pins 29, 31, 33, 35) to a GND pin with a jumper wire.

## Troubleshooting

| Problem | Fix |
|---|---|
| Nothing lights up | Check `journalctl -u leds -f`. Make sure the strip's GND is connected to the Pi's GND, and that DIN goes to the **input** end of the strip (arrows on the strip point away from it). |
| Random colors or flicker | The Pi sends a 3.3V signal while the strip expects 5V. Put a 74AHCT125 level shifter between GPIO10 (pin 19) and DIN, keep the data wire short, and add a ~330 Ω resistor in series with DIN. |
| Red and green swapped | Set `color_order = RGB`. |
| Wrong position lights up | Swap the switch wires, or reorder `switch_pins`. |
| Colors go brownish or LEDs at the far end look dim | The power supply is too weak or the strip needs 5V fed in at more points. Lower `brightness`. |
| SSH says "SSH may not work until a valid user has been set up" | The Pi is still running its first-boot user wizard. Set the username in Raspberry Pi Imager when flashing, or finish the wizard on a screen and keyboard. The LED service works either way. |
| Log says `spidev.bufsiz` is too small | Run `install.sh` again; it adds `spidev.bufsiz=65536` to the kernel command line. |

## How it works

`leds.py` drives the strip through the Pi's SPI port instead of PWM. Each data bit
for the LEDs becomes 3 SPI bits at 2.4 MHz (`100` = 0, `110` = 1), which matches
the WS2812B timing. This needs no root access and doesn't conflict with audio.
`core_freq=250` keeps the SPI clock steady, since the Pi otherwise changes it with
CPU load. The switch is read 50 times per second and has to stay in the same
position for 50 ms before it counts, so contact bounce is ignored.

## Files

| File | Purpose |
|---|---|
| `leds.py` | The program |
| `leds.conf.example` | Default settings, copied to `leds.conf` on first install |
| `switch_scan.py` | Helper to find which switch terminals connect in each position |
| `install.sh` | Run on the Pi: packages, boot settings, systemd service |
| `deploy.sh` | Run on your computer: copies files to a Pi and runs `install.sh` |

## License

[MIT](LICENSE)
