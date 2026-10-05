# ledstrip

A Raspberry Pi lights part of a WS2812B LED strip in the official TLP 2.0 color
matching the position of a 4-position rotary switch. A rotary encoder switches the
whole strip to a moving rainbow (press) and changes its speed (turn). Every change
plays a short transition: retro glitch, steampunk, rainbow, or none.

The strip can also be controlled from the command line over SSH. A command stays
active until someone uses the switch or the encoder: manual changes always take over.

| Switch position | LEDs lit (example) | Color     |
| --------------- | ------------------ | --------- |
| 1               | 0 – 3              | TLP:RED   |
| 2               | 4 – 7              | TLP:AMBER |
| 3               | 8 – 11             | TLP:GREEN |
| 4               | 12 – 15            | TLP:CLEAR |
| none selected   | –                  | all off   |

LED ranges, colors, brightness, transitions and wiring are set in a plain text file,
`leds.conf`. Changes apply within a second of saving, with no restart needed.

Based on [0x0SegFault/ledstrip](https://github.com/0x0SegFault/ledstrip) (MIT).

In the examples below the Pi user is **`red`** and the Pi is reachable as
`raspberrypi.local`. Replace the address with your Pi's IP address if that name
doesn't resolve on your network.

## Parts

- Raspberry Pi with a 40-pin header. Used here: **Raspberry Pi 2 Model B**. Also works on
  a Pi 3, Pi 4 and Pi Zero 2 W.
- WS2812B / NeoPixel LED strip (3 wires: 5V, GND, DIN)
- 5V power supply for the strip, sized for it (see [Power](#power))
- 4-position rotary switch
- Rotary encoder with push button (for example a KY-040 module), optional
- Optional: 74AHCT125 level shifter (see [Troubleshooting](#troubleshooting))

## Wiring

> Wire everything with the power off.

| From                        | To Pi              | Header pin |
| --------------------------- | ------------------ | ---------- |
| LED strip **DIN**           | GPIO10 (SPI MOSI)  | 19         |
| LED strip **GND**           | GND                | 20         |
| Switch **common**           | **3V3**            | 17         |
| Switch position 1           | GPIO5              | 29         |
| Switch position 2           | GPIO6              | 31         |
| Switch position 3           | GPIO13             | 33         |
| Switch position 4           | GPIO19             | 35         |
| Encoder **SW** (button)     | GPIO26             | 37         |
| Encoder **CLK**             | GPIO20             | 38         |
| Encoder **GND**             | GND                | 39         |
| Encoder **DT**              | GPIO21             | 40         |
| Encoder **+** (KY-040 only) | 3V3                | 1          |
| LED strip **5V**            | external 5V supply **+** | –    |
| External supply **−**       | LED strip GND (and so also Pi GND) | – |

```
                      Raspberry Pi 40-pin header
        (pin 1 is at the end away from the USB ports; run `pinout`
         on the Pi to print this drawing for your exact board)

   Encoder + ─────── 3V3  (1) (2)  5V
                    GPIO2  (3) (4)  5V
                    GPIO3  (5) (6)  GND
                    GPIO4  (7) (8)  GPIO14
                      GND  (9) (10) GPIO15
                   GPIO17 (11) (12) GPIO18
                   GPIO27 (13) (14) GND
                   GPIO22 (15) (16) GPIO23
 Switch common ───── 3V3 (17) (18) GPIO24
 LED strip DIN ── GPIO10 (19) (20) GND ──────── LED strip GND
                    GPIO9 (21) (22) GPIO25
                   GPIO11 (23) (24) GPIO8
                      GND (25) (26) GPIO7
                    GPIO0 (27) (28) GPIO1
 Switch pos. 1 ─── GPIO5 (29) (30) GND
 Switch pos. 2 ─── GPIO6 (31) (32) GPIO12
 Switch pos. 3 ── GPIO13 (33) (34) GND
 Switch pos. 4 ── GPIO19 (35) (36) GPIO16
   Encoder SW ─── GPIO26 (37) (38) GPIO20 ───── Encoder CLK
                      GND (39) (40) GPIO21 ───── Encoder DT
                       └──────────────────────── Encoder GND
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
```

### The switch

The switch common is on **3V3** and the Pi uses its internal pull-down resistors, so
no extra resistors are needed. A position counts as selected when its pin receives
3V3 through the switch. If no position is connected (an "off" position, or between
two positions), all LEDs turn off.

If you prefer to wire the common to **GND** instead (as in the original project), set
`switch_active = low` in `leds.conf`; the Pi then uses pull-ups.

Never connect the switch common to 5V: the Pi's GPIOs only accept 3.3V.

**Not sure which terminal is which?** With a multimeter in continuity (beep) mode, turn
the switch to each position and find which terminal beeps with the common. Or let the
Pi map it: wire each switch terminal to its own GPIO (nothing to 3V3 or GND), for
example to GPIO 17 27 22 23 24 25 12 16 (pins 11 13 15 16 18 22 32 36), then run:

```
python3 ~/leds/switch_scan.py 17 27 22 23 24 25 12 16
```

Turn the switch slowly; it prints which terminals connect in each position. Press
Ctrl+C when done and remove these wires again. (This helper needs the `lgpio` package,
available on current Raspberry Pi OS.)

### The encoder

The encoder's common/GND pin goes to GND and the Pi uses internal pull-ups, so turning
or pressing pulls the pins low. Unlike the switch, **no encoder pin may be wired to
3V3**, except the `+` pin of a KY-040 module, which powers its own pull-up resistors.

The encoder is optional: leave `encoder_pins` empty in `leds.conf` if you don't use one.

### Power

Don't power the strip from the Pi's 5V pin except for a handful of LEDs. Each LED draws
up to about 60 mA at full white, so 100 LEDs can need up to 6 A. The `brightness`
setting scales that down. Always connect the supply's GND to the Pi's GND so the data
signal has a common reference.

## Installation

### 1. Prepare the Pi

1. In [Raspberry Pi Imager](https://www.raspberrypi.com/software/), choose the device
   **Raspberry Pi 2** (or your model), then **Raspberry Pi OS Lite (32-bit)**.
   In the settings, set the username to **`red`**, choose a password, and **enable SSH**.
2. The Pi 2 has no Wi-Fi: connect it to your router with an **Ethernet cable** (or use a
   USB Wi-Fi adapter). On a Pi 3, Pi 4 or Zero 2 W you can set up Wi-Fi in Imager instead.
3. Boot it and check you can reach it:
   ```
   ping raspberrypi.local
   ```
4. Optional, so you don't have to type the password each time:
   ```
   ssh-copy-id red@raspberrypi.local
   ```

### 2. Deploy

From this folder on your computer:

```
sh deploy.sh red@raspberrypi.local
```

This copies the files to `/home/red/leds` on the Pi and runs `install.sh` there
(you'll be asked for red's password for `sudo`). That script:

- installs the needed packages (`python3-spidev`, `python3-gpiozero`, and `python3-lgpio`,
  or `python3-rpi.gpio` on older Raspberry Pi OS releases that don't have lgpio)
- creates `leds.conf` from `leds.conf.example` (only the first time)
- enables SPI and fixes the core clock in the boot config: 250 MHz on a Pi 2 / Pi 3 /
  Zero 2 W, 500 MHz on a Pi 4 (backups saved as `*.bak-leds`)
- installs the `leds` command, so it can be used directly over SSH
- installs and starts the `leds` service, running as `red`, at every boot
- reboots the Pi if the boot config changed (only on the first install)

Run the same command again whenever you update the files. The Pi's `leds.conf` is
never overwritten.

**Manual install without `deploy.sh`:** copy all the files into `/home/red/leds` on the
Pi, then run `sudo sh install.sh` in that folder.

## Configuration

Edit the config on the Pi:

```
ssh red@raspberrypi.local
nano ~/leds/leds.conf
```

```
led_count = 16            # total LEDs on the strip
brightness = 50           # percent, 1-100
gamma = 2.2               # makes LED colors look like on a screen, 1.0 = off

# positionN = FIRST-LAST COLOR   (LED numbers start at 0, both ends included)
position1 = 0-3 tlp:red
position2 = 4-7 tlp:amber
position3 = 8-11 tlp:green
position4 = 12-15 tlp:clear

transition = glitch       # glitch, steampunk, rainbow or none
transition_ms = 600

rainbow_speed = 0.4       # rainbow turns per second at startup
rainbow_step = 0.1        # speed change per encoder click
rainbow_brightness = 40   # percent, on top of brightness

switch_pins = 5 6 13 19   # GPIO numbers for positions 1-4
switch_active = high      # high: switch common on 3V3, low: common on GND
encoder_pins = 20 21 26   # CLK DT SW, empty if no encoder
encoder_invert = no       # yes if turning clockwise slows the rainbow down
color_order = GRB         # WS2812B is GRB; try RGB if red and green are swapped
```

Save the file and the strip updates within a second. If the file has a mistake, the
previous settings stay active and the error appears in the log.

### Colors

The four TLP colors are the official TLP 2.0 values published by
[FIRST](https://www.first.org/tlp/) and
[CISA](https://www.cisa.gov/news-events/news/traffic-light-protocol-tlp-definitions-and-usage),
defined for a black background:

| Name        | R, G, B       |
| ----------- | ------------- |
| `tlp:red`   | 255, 0, 51    |
| `tlp:amber` | 255, 192, 0   |
| `tlp:green` | 51, 255, 0    |
| `tlp:clear` | 255, 255, 255 |

Other names: `white red amber orange green blue yellow purple cyan pink off`, or any
`R,G,B` numbers from 0 to 255, for example `position3 = 8-11 255,80,0`.

LEDs don't show RGB values the way a screen does: without correction, TLP:RED looks
pink and TLP:AMBER looks yellow. `gamma = 2.2` corrects this so the strip matches the
official colors much more closely.

### Transitions

| `transition` | Effect                                                                         |
| ------------ | ------------------------------------------------------------------------------ |
| `glitch`     | Retro signal dropouts, white flashes and neon noise; the new color locks in pixel by pixel |
| `steampunk`  | The old color cools down to an ember glow, the new one ignites in flickering copper |
| `rainbow`    | A moving rainbow over the whole strip, then the new color                      |
| `none`       | Instant change                                                                 |

Glitch looks best around 400–700 ms, steampunk around 800–1200 ms.

### Finding the LED numbers

Set `led_count` higher than the real number of LEDs, then:

```
sudo systemctl stop leds
leds identify
```

LEDs 0, 10, 20, … light **red**, LEDs 5, 15, 25, … light **green**, and the rest dim
blue. Count along the strip to pick your ranges. The last LED that lights up gives you
`led_count`. Press Ctrl+C, then `sudo systemctl start leds`.

## Using it

### Switch and encoder

- **Switch:** each position lights its range in its color. No position: all off.
- **Encoder press:** turns the rainbow on over the whole strip, whatever the switch
  position. Press again to turn it off and go back to the switch.
- **Encoder turn** (while the rainbow is on): clockwise faster, counter-clockwise slower.

### Command line over SSH

```
ssh red@raspberrypi.local leds set tlp:amber
```

| Command              | What it does                                                                 |
| -------------------- | ---------------------------------------------------------------------------- |
| `leds set STATE`     | Show STATE until the switch or encoder is used. STATE is `off`, `rainbow`, a position `1`–`4`, or a position color: `red`, `tlp:amber`, `green`, … |
| `leds reset`         | Go back to the previous command. After the first command: back to manual control |
| `leds release`       | Give control back to the switch and encoder right away                        |
| `leds status`        | What is shown, who controls it, switch position, rainbow state and speed      |
| `leds speed TURNS`   | Rainbow speed in turns per second, for example `leds speed 1.5`               |
| `leds identify`      | LED numbering helper (stop the service first)                                |
| `leds help`          | List the commands                                                            |

Example: the switch is on AMBER, then you send `leds set red`, `leds set rainbow` and
`leds set green`. Three `leds reset` go back to rainbow, then red, then manual control,
where the strip shows AMBER from the switch again.

**Manual changes always take over.** As soon as someone turns the switch, presses the
encoder, or turns it while a rainbow is shown, the command is dropped (with its history)
and the strip follows the physical controls again. A press always toggles what is
actually on the strip: if a command turned the rainbow on, a press turns it off.

Commands are not saved: after a reboot the strip starts under manual control. The
`leds` command talks to the service through a local socket (`~/leds/leds.sock`) that
only the `red` user can use; nothing is opened on the network, SSH provides the remote
access.

## Useful commands

```
leds status                    # what is shown and who controls it
journalctl -u leds -f          # live log: switch positions, encoder, commands, config errors
sudo systemctl restart leds    # restart
sudo systemctl stop leds       # stop (LEDs turn off)
sudo systemctl disable leds    # don't start at boot
```

Before the switch is wired, you can test a position by briefly connecting GPIO5, GPIO6,
GPIO13 or GPIO19 (pins 29, 31, 33, 35) to a 3V3 pin (1 or 17) with a jumper wire.

## Troubleshooting

| Problem | Fix |
| ------- | --- |
| Nothing lights up | Check `journalctl -u leds -f`. Make sure the strip's GND is connected to the Pi's GND, and that DIN goes to the **input** end of the strip (arrows on the strip point away from it). |
| Random colors or flicker | The Pi sends a 3.3V signal while the strip expects 5V. Put a 74AHCT125 level shifter between GPIO10 (pin 19) and DIN, keep the data wire short, and add a ~330 Ω resistor in series with DIN. |
| Red and green swapped | Set `color_order = RGB`. |
| Turning the switch does nothing | Watch the log while turning: each change prints `Switch position` with the GPIO that closed. If nothing appears, check that the common is on 3V3 with `switch_active = high` (or on GND with `switch_active = low`). |
| Wrong position lights up | Swap the switch wires, or reorder `switch_pins`. |
| Rainbow speed goes the wrong way | Set `encoder_invert = yes`, or swap the CLK and DT wires. |
| Encoder press does nothing | Check the encoder's GND wire: the button connects SW to GND. The log prints `Rainbow mode ON/OFF` on each press. |
| `leds` says the service is not running | `sudo systemctl start leds`, then check `journalctl -u leds -f` for the reason. |
| `leds` says permission denied | Run it as `red`, the user the service runs as. |
| `No module named lgpio` | Run `sh deploy.sh red@raspberrypi.local` again: the install refreshes the package lists and falls back to RPi.GPIO when lgpio isn't available. |
| Log says `spidev.bufsiz` is too small | Run the install again; it adds `spidev.bufsiz=65536` to the kernel command line. |
| Colors go brownish or LEDs at the far end look dim | The power supply is too weak or the strip needs 5V fed in at more points. Lower `brightness`. |
| SSH says "SSH may not work until a valid user has been set up" | Set the username `red` in Raspberry Pi Imager when flashing, or finish the first-boot wizard on a screen and keyboard. |

## How it works

`leds.py` drives the strip through the Pi's SPI port instead of PWM. Each data bit for
the LEDs becomes 3 SPI bits at 2.4 MHz (`100` = 0, `110` = 1), which matches the WS2812B
timing. This needs no root access and doesn't conflict with audio. The core clock is
fixed in the boot config because the SPI clock follows it, and the Pi otherwise changes
it with CPU load.

The switch is read 50 times per second and has to stay in the same position for 50 ms
before it counts (200 ms for "no position"), so contact bounce and the moment between
two positions are ignored. The encoder is decoded by gpiozero in the background.

## Files

| File                | Purpose                                                          |
| ------------------- | ---------------------------------------------------------------- |
| `leds.py`           | The program, the `leds` command and the service                  |
| `leds.conf.example` | Default settings, copied to `leds.conf` on first install         |
| `install.sh`        | Run on the Pi: packages, boot settings, `leds` command, service  |
| `deploy.sh`         | Run on your computer: copies files to a Pi and runs `install.sh` |
| `switch_scan.py`    | Helper to find which switch terminals connect in each position   |

## License

[MIT](LICENSE). Based on [0x0SegFault/ledstrip](https://github.com/0x0SegFault/ledstrip).
