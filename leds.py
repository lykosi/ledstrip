#!/usr/bin/env python3
"""WS2812B strip driven over SPI (GPIO10). A 4-position switch picks which
segment is lit; turning the switch plays a moving rainbow first.

Usage:
  leds.py            run (normally started by systemd: leds.service)
  leds.py identify   help find LED numbers: every 10th LED red, every 5th green
"""
import colorsys
import os
import signal
import sys
import time

# lgpio creates helper files in the working directory, which is / under systemd
os.environ.setdefault("LG_WD", "/tmp")
os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

import spidev
from gpiozero import DigitalInputDevice

CONF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leds.conf")

COLORS = {
    "white": (255, 255, 255),
    "green": (0, 255, 0),
    "orange": (255, 70, 0),
    "red": (255, 0, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 160, 0),
    "purple": (160, 0, 255),
    "cyan": (0, 255, 255),
    "pink": (255, 30, 90),
    "off": (0, 0, 0),
}

FRAME_TIME = 0.02     # 50 fps
REFRESH = 0.2         # re-send a still image this often
SETTLE = 0.05         # switch must be stable this long to count as a new position
OFF_SETTLE = 0.5      # no contact closed for this long -> all LEDs off

# SPI at 2.4 MHz: every WS2812 bit becomes 3 SPI bits, 0 -> 100, 1 -> 110
SPI_HZ = 2_400_000
ENCODE = []
for _byte in range(256):
    _bits = 0
    for _i in range(7, -1, -1):
        _bits = (_bits << 3) | (0b110 if _byte >> _i & 1 else 0b100)
    ENCODE.append(_bits.to_bytes(3, "big"))
RESET = bytes(100)    # >300 us low = latch


def log(*args):
    print(*args, flush=True)


class ConfigError(Exception):
    pass


def parse_color(text):
    text = text.strip().lower()
    if text in COLORS:
        return COLORS[text]
    parts = text.split(",")
    if len(parts) == 3 and all(p.strip().isdigit() and int(p) <= 255 for p in parts):
        return tuple(int(p) for p in parts)
    raise ConfigError(f"unknown color '{text}'")


def load_config(path):
    raw = {}
    with open(path) as f:
        for n, line in enumerate(f, 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if "=" not in line:
                raise ConfigError(f"line {n}: expected 'name = value'")
            key, value = line.split("=", 1)
            raw[key.strip().lower()] = value.strip()

    def num(key, default, cast=int):
        try:
            return cast(raw.get(key, default))
        except ValueError:
            raise ConfigError(f"{key}: '{raw[key]}' is not a number")

    cfg = {
        "led_count": num("led_count", 60),
        "brightness": max(0, min(100, num("brightness", 50))) / 100,
        "rainbow_seconds": num("rainbow_seconds", 2, float),
        "rainbow_speed": num("rainbow_speed", 1, float),
        "color_order": raw.get("color_order", "GRB").upper(),
        "segments": [],
    }
    if cfg["led_count"] < 1:
        raise ConfigError("led_count must be at least 1")
    if sorted(cfg["color_order"]) != ["B", "G", "R"]:
        raise ConfigError("color_order must be a mix of R, G, B, e.g. GRB")
    try:
        cfg["switch_pins"] = [int(p) for p in raw.get("switch_pins", "5 6 13 19").split()]
    except ValueError:
        raise ConfigError("switch_pins must be GPIO numbers separated by spaces")

    for i in range(1, len(cfg["switch_pins"]) + 1):
        value = raw.get(f"position{i}", "").split(None, 1)
        if not value:
            cfg["segments"].append(None)
            continue
        try:
            first, last = (int(x) for x in value[0].split("-"))
        except ValueError:
            raise ConfigError(f"position{i}: range must look like 10-19")
        color = parse_color(value[1]) if len(value) > 1 else COLORS["white"]
        cfg["segments"].append((first, last, color))
    return cfg


class Strip:
    def __init__(self):
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = SPI_HZ
        self.spi.mode = 0
        try:
            with open("/sys/module/spidev/parameters/bufsiz") as f:
                self.bufsiz = int(f.read())
        except OSError:
            self.bufsiz = 4096
        self.warned = False

    def show(self, pixels, cfg):
        order = ["RGB".index(c) for c in cfg["color_order"]]
        k = cfg["brightness"]
        out = bytearray(RESET)
        for px in pixels:
            for c in order:
                out += ENCODE[int(px[c] * k)]
        out += RESET
        if len(out) > self.bufsiz and not self.warned:
            log(f"WARNING: {len(pixels)} LEDs need {len(out)} bytes but spidev.bufsiz is "
                f"{self.bufsiz}; add spidev.bufsiz=65536 to /boot/firmware/cmdline.txt")
            self.warned = True
        self.spi.writebytes2(out)

    def close(self, cfg):
        if cfg:
            self.show([(0, 0, 0)] * cfg["led_count"], cfg)
        self.spi.close()


class Switch:
    def __init__(self, pins):
        self.pins = pins
        self.inputs = [DigitalInputDevice(p, pull_up=True) for p in pins]

    def read(self):
        """GPIO numbers currently connected to GND."""
        return tuple(p for p, d in zip(self.pins, self.inputs) if d.value)

    def position(self, closed):
        """1-based position of the first closed contact, or None."""
        return self.pins.index(closed[0]) + 1 if closed else None

    def close(self):
        for d in self.inputs:
            d.close()


def static_frame(cfg, position):
    pixels = [(0, 0, 0)] * cfg["led_count"]
    seg = cfg["segments"][position - 1] if position else None
    if seg:
        first, last, color = seg
        for i in range(max(first, 0), min(last, cfg["led_count"] - 1) + 1):
            pixels[i] = color
    return pixels


def rainbow_frame(cfg, t):
    n = cfg["led_count"]
    shift = t * cfg["rainbow_speed"]
    return [tuple(int(c * 255) for c in colorsys.hsv_to_rgb((i / n - shift) % 1, 1, 1))
            for i in range(n)]


def identify():
    cfg = load_config(CONF)
    strip = Strip()
    pixels = []
    for i in range(cfg["led_count"]):
        pixels.append((255, 0, 0) if i % 10 == 0 else (0, 255, 0) if i % 5 == 0 else (0, 0, 40))
    strip.show(pixels, cfg)
    log(f"Showing {cfg['led_count']} LEDs: red = 0, 10, 20 ...  green = 5, 15, 25 ...  "
        "Press Ctrl+C to stop.")
    try:
        signal.pause()
    except KeyboardInterrupt:
        pass
    strip.close(cfg)


def main():
    running = True

    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    strip = Strip()
    cfg, switch, mtime, next_check = None, None, None, 0
    position, closed, candidate, since = None, (), (), time.monotonic()
    rainbow_start = rainbow_end = time.monotonic()
    drawn, drawn_at = None, 0

    while running:
        now = time.monotonic()

        # Reload the config file when it changes
        if now >= next_check:
            next_check = now + 1
            try:
                m = os.stat(CONF).st_mtime
                if m != mtime:
                    mtime = m
                    new = load_config(CONF)
                    if cfg and cfg["led_count"] > new["led_count"]:
                        strip.show([(0, 0, 0)] * cfg["led_count"], cfg)  # clear the old tail
                    if not switch or new["switch_pins"] != switch.pins:
                        if switch:
                            switch.close()
                        switch = Switch(new["switch_pins"])
                    cfg, drawn = new, None
                    log(f"Config loaded: {cfg['led_count']} LEDs, brightness "
                        f"{int(cfg['brightness'] * 100)}%, switch pins {cfg['switch_pins']}")
            except ConfigError as e:
                log(f"Config error in {CONF}: {e}" + (" (keeping previous settings)" if cfg else ""))
            except OSError as e:
                log(f"Error: {e} (retrying)")
                mtime = None
                next_check = now + 5
        if not cfg:
            time.sleep(1)
            continue

        # Debounced switch reading
        raw = switch.read()
        if raw != candidate:
            candidate, since = raw, now
        elif raw != closed and now - since >= (SETTLE if raw else OFF_SETTLE):
            closed = raw
            new = switch.position(closed)
            log(f"Switch position: {new or 'none'}  (closed: "
                f"{' '.join(f'GPIO{p}' for p in closed) or 'nothing'})")
            if new != position:
                position = new
                if position:
                    rainbow_start, rainbow_end = now, now + cfg["rainbow_seconds"]
                drawn = None

        if now < rainbow_end:
            strip.show(rainbow_frame(cfg, now - rainbow_start), cfg)
            drawn = "rainbow"
        elif drawn != position or now - drawn_at >= REFRESH:
            # Re-sent regularly so a frame garbled on the data line doesn't stick
            strip.show(static_frame(cfg, position), cfg)
            drawn, drawn_at = position, now
        time.sleep(FRAME_TIME)

    strip.close(cfg)
    if switch:
        switch.close()


if __name__ == "__main__":
    if sys.argv[1:] == ["identify"]:
        identify()
    else:
        main()
