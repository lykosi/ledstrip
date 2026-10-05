#!/usr/bin/env python3
"""WS2812B strip on a Raspberry Pi, driven over SPI (GPIO10).

A 4-position switch selects which section of the strip is lit (nothing
selected: all LEDs off). A rotary encoder toggles a rainbow mode when pressed
and changes the rainbow speed when turned. Every change of what is shown
plays a transition: glitch, steampunk, rainbow or none.

The display can also be set from the command line (for example over SSH).
A command stays active until the switch or the encoder is used: manual
changes always take over.

Based on https://github.com/0x0SegFault/ledstrip (MIT).
"""
import colorsys
import os
import queue
import random
import signal
import socket
import sys
import time

# lgpio creates helper files in the working directory, which is / under systemd
os.environ.setdefault("LG_WD", "/tmp")

import spidev
from gpiozero import Button, Device, DigitalInputDevice, RotaryEncoder

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(HERE, "leds.conf")
SOCK = os.path.join(HERE, "leds.sock")  # commands sent with the leds CLI

COLORS = {
    # Official TLP 2.0 colors (FIRST / CISA)
    "tlp:red": (255, 0, 51),
    "tlp:amber": (255, 192, 0),
    "tlp:green": (51, 255, 0),
    "tlp:clear": (255, 255, 255),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "amber": (255, 191, 0),
    "orange": (255, 70, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 160, 0),
    "purple": (160, 0, 255),
    "cyan": (0, 255, 255),
    "pink": (255, 30, 90),
    "off": (0, 0, 0),
}
BLACK = (0, 0, 0)

TRANSITIONS = ("glitch", "steampunk", "rainbow", "none")
SPI_PINS = {7, 8, 9, 10, 11}  # SPI0, used by the strip

FRAME_TIME = 0.02  # 50 fps
REFRESH = 0.2  # re-send a still image this often
SETTLE = 0.05  # switch must be stable this long to count as a new position
OFF_SETTLE = 0.2  # no contact closed for this long -> all LEDs off
SPEED_MIN = 0.05  # rainbow turns per second
SPEED_MAX = 3.0

GLITCH_NOISE = ((150, 0, 110), (0, 150, 130), (120, 120, 120))
EMBER = (255, 50, 0)
COPPER = (255, 110, 25)

# SPI at 2.4 MHz: every WS2812 bit becomes 3 SPI bits, 0 -> 100, 1 -> 110
SPI_HZ = 2_400_000
ENCODE = []
for _byte in range(256):
    _bits = 0
    for _i in range(7, -1, -1):
        _bits = (_bits << 3) | (0b110 if _byte >> _i & 1 else 0b100)
    ENCODE.append(_bits.to_bytes(3, "big"))
RESET = bytes(100)  # >300 us low = latch


def log(*args):
    print(*args, flush=True)


# --- Configuration ---

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

    def pins(key, default):
        try:
            return [int(p) for p in raw.get(key, default).split()]
        except ValueError:
            raise ConfigError(f"{key} must be GPIO numbers separated by spaces")

    def choice(key, default, allowed):
        value = raw.get(key, default).lower()
        if value not in allowed:
            raise ConfigError(f"{key} must be one of: {', '.join(allowed)}")
        return value

    cfg = {
        "led_count": num("led_count", 16),
        "brightness": max(0, min(100, num("brightness", 50))) / 100,
        "gamma": num("gamma", 2.2, float),
        "color_order": raw.get("color_order", "GRB").upper(),
        "switch_pins": pins("switch_pins", "5 6 13 19"),
        "switch_active": choice("switch_active", "high", ("high", "low")),
        "encoder_pins": pins("encoder_pins", "20 21 26"),
        "encoder_invert": choice("encoder_invert", "no", ("yes", "no")) == "yes",
        "rainbow_speed": max(SPEED_MIN, min(SPEED_MAX, num("rainbow_speed", 0.4, float))),
        "rainbow_step": num("rainbow_step", 0.1, float),
        "rainbow_brightness": max(0, min(100, num("rainbow_brightness", 40))) / 100,
        "transition": choice("transition", "glitch", TRANSITIONS),
        "transition_ms": max(0, num("transition_ms", 600)),
        "segments": [],
    }

    if cfg["led_count"] < 1:
        raise ConfigError("led_count must be at least 1")
    if not 1.0 <= cfg["gamma"] <= 3.0:
        raise ConfigError("gamma must be between 1.0 (off) and 3.0")
    if sorted(cfg["color_order"]) != ["B", "G", "R"]:
        raise ConfigError("color_order must be a mix of R, G, B, e.g. GRB")
    if len(cfg["encoder_pins"]) not in (0, 3):
        raise ConfigError("encoder_pins must be 3 GPIO numbers (CLK DT SW), or empty for no encoder")

    all_pins = cfg["switch_pins"] + cfg["encoder_pins"]
    if len(set(all_pins)) != len(all_pins):
        raise ConfigError("the same GPIO is used twice in switch_pins / encoder_pins")
    if SPI_PINS & set(all_pins):
        raise ConfigError(f"GPIO {sorted(SPI_PINS & set(all_pins))} belongs to SPI, used by the strip")

    for i in range(1, len(cfg["switch_pins"]) + 1):
        value = raw.get(f"position{i}", "").split(None, 1)
        if not value:
            cfg["segments"].append(None)
            continue
        try:
            first, last = (int(x) for x in value[0].split("-"))
        except ValueError:
            raise ConfigError(f"position{i}: range must look like 10-19")
        if first > last:
            raise ConfigError(f"position{i}: first LED is after the last one")
        label = value[1].strip() if len(value) > 1 else "white"
        cfg["segments"].append((first, last, parse_color(label), label.upper() if label.lower().startswith("tlp:") else label))
    return cfg


# --- Hardware ---

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
        self.lut, self.lut_key = None, None

    def show(self, pixels, cfg):
        # Gamma correction makes LED colors look like the same RGB values on a screen,
        # then brightness scales the result linearly
        key = (cfg["brightness"], cfg["gamma"])
        if key != self.lut_key:
            k, g = key
            self.lut = [round((v / 255) ** g * 255 * k) for v in range(256)]
            self.lut_key = key
        order = ["RGB".index(c) for c in cfg["color_order"]]
        out = bytearray(RESET)
        for px in pixels:
            for c in order:
                out += ENCODE[self.lut[min(255, max(0, int(px[c])))]]
        out += RESET
        if len(out) > self.bufsiz and not self.warned:
            log(f"WARNING: {len(pixels)} LEDs need {len(out)} bytes but spidev.bufsiz is "
                f"{self.bufsiz}; add spidev.bufsiz=65536 to /boot/firmware/cmdline.txt")
            self.warned = True
        self.spi.writebytes2(out)

    def close(self, cfg):
        if cfg:
            self.show([BLACK] * cfg["led_count"], cfg)
        self.spi.close()


class Controls:
    """Rotary switch and rotary encoder. Encoder actions are put in `events`:
    "press" for a button press, +1 / -1 for a click clockwise / counter-clockwise."""

    def __init__(self, cfg, events):
        self.key = self.config_key(cfg)
        self.pins = cfg["switch_pins"]
        pull_up = cfg["switch_active"] == "low"
        self.inputs = [DigitalInputDevice(p, pull_up=pull_up) for p in self.pins]

        self.encoder = self.button = None
        if cfg["encoder_pins"]:
            clk, dt, sw = cfg["encoder_pins"]
            sign = -1 if cfg["encoder_invert"] else 1
            self.encoder = RotaryEncoder(clk, dt, max_steps=0)
            self.encoder.when_rotated_clockwise = lambda: events.put(sign)
            self.encoder.when_rotated_counter_clockwise = lambda: events.put(-sign)
            self.button = Button(sw, pull_up=True, bounce_time=0.05)
            self.button.when_pressed = lambda: events.put("press")

    @staticmethod
    def config_key(cfg):
        return (tuple(cfg["switch_pins"]), cfg["switch_active"], tuple(cfg["encoder_pins"]), cfg["encoder_invert"])

    def matches(self, cfg):
        return self.key == self.config_key(cfg)

    def read_switch(self):
        """GPIO numbers whose switch contact is currently closed."""
        return tuple(p for p, d in zip(self.pins, self.inputs) if d.value)

    def position(self, closed):
        """1-based position of the first closed contact, or None."""
        return self.pins.index(closed[0]) + 1 if closed else None

    def close(self):
        for d in self.inputs + [self.encoder, self.button]:
            if d:
                d.close()


# --- Frames ---

def fit(frame, n):
    return (list(frame) + [BLACK] * n)[:n]


def static_frame(cfg, state):
    pixels = [BLACK] * cfg["led_count"]
    seg = cfg["segments"][state - 1] if isinstance(state, int) else None
    if seg:
        first, last, color, _ = seg
        for i in range(max(first, 0), min(last, cfg["led_count"] - 1) + 1):
            pixels[i] = color
    return pixels


def rainbow_frame(n, phase, level):
    return [tuple(int(c * 255 * level) for c in colorsys.hsv_to_rgb((i / n + phase) % 1, 1, 1))
            for i in range(n)]


def lerp(a, b, w):
    return a + (b - a) * w


def glitch_frame(prev, target, p):
    """Retro glitch: signal dropouts, white flashes, neon noise and a shaking
    old image. The new image locks in pixel by pixel as p goes from 0 to 1."""
    n = len(target)
    if p < 0.9:
        roll = random.random()
        if roll < 0.10:
            return [BLACK] * n
        if roll < 0.14:
            return [(90, 90, 90)] * n

    shift = random.randint(-2, 2)
    out = []
    for i in range(n):
        roll = random.random()
        if roll < p:
            out.append(target[i])
        elif roll < p + 0.18:
            out.append(random.choice(GLITCH_NOISE))
        else:
            out.append(prev[(i + shift) % n])
    return out


def steampunk_frame(prev, target, p):
    """Steampunk: the old image cools down to an ember glow, then the new one
    ignites pixel by pixel in flickering copper before settling on its color."""
    if p < 0.4:
        q = p / 0.4
        out = []
        for px in prev:
            lum = max(px) / 255
            bright = (1 - q) * random.uniform(0.78, 1.0)
            out.append(tuple(int(lerp(c, e * lum, q) * bright) for c, e in zip(px, EMBER)))
        return out

    q = (p - 0.4) / 0.6
    n = len(target)
    out = []
    for i, px in enumerate(target):
        lum = max(px) / 255
        if lum == 0:
            out.append(BLACK)
            continue
        local = min(1.0, max(0.0, (q - i / n * 0.6) / 0.4))
        bright = min(1.0, local * 2) * (1 - random.random() * (1 - local) * 0.6)
        out.append(tuple(int(lerp(cu * lum, c, local) * bright) for cu, c in zip(COPPER, px)))
    return out


def transition_frame(cfg, prev, target, p, elapsed):
    if cfg["transition"] == "glitch":
        return glitch_frame(prev, target, p)
    if cfg["transition"] == "steampunk":
        return steampunk_frame(prev, target, p)
    return rainbow_frame(len(target), elapsed * cfg["rainbow_speed"], cfg["rainbow_brightness"])


def describe(cfg, state):
    """Human readable name of a display state: "off", "rainbow" or a position 1-4."""
    if not isinstance(state, int):
        return state
    seg = cfg["segments"][state - 1]
    return f"position {state} ({seg[3]}, LEDs {seg[0]}-{seg[1]})" if seg else f"position {state} (nothing set)"


# --- Command line over SSH ---

class CommandServer:
    """Unix socket the leds CLI talks to. One command per connection, one reply."""

    def __init__(self, path):
        self.path = path
        if os.path.exists(path):
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.connect(path)
                raise RuntimeError("another leds controller is already running (is the service started?)")
            except (ConnectionRefusedError, FileNotFoundError):
                os.unlink(path)  # left over from a crash
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        os.chmod(path, 0o660)
        self.sock.listen(4)
        self.sock.setblocking(False)

    def poll(self, handler):
        """Answer every waiting command with handler(command) -> reply."""
        while True:
            try:
                conn, _ = self.sock.accept()
            except BlockingIOError:
                return
            with conn:
                try:
                    conn.settimeout(0.5)
                    data = b""
                    while b"\n" not in data and len(data) < 1024:
                        chunk = conn.recv(256)
                        if not chunk:
                            break
                        data += chunk
                    conn.sendall((handler(data.decode().strip()) + "\n").encode())
                except (OSError, UnicodeDecodeError):
                    pass

    def close(self):
        self.sock.close()
        try:
            os.unlink(self.path)
        except OSError:
            pass


def send_command(args):
    """CLI side: send one command to the running controller and print the reply."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            s.connect(SOCK)
            s.sendall((" ".join(args) + "\n").encode())
            reply = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                reply += chunk
    except (FileNotFoundError, ConnectionRefusedError):
        print("The leds service is not running. Start it with: sudo systemctl start leds")
        return 1
    except PermissionError:
        print("Permission denied: run this as the user the leds service runs as.")
        return 1
    except socket.timeout:
        print("No answer from the leds service.")
        return 1
    text = reply.decode().strip()
    print(text)
    return 1 if text.startswith("error") else 0


# --- Controller ---

class App:
    def __init__(self):
        self.server = CommandServer(SOCK)
        self.strip = Strip()
        self.events = queue.SimpleQueue()
        self.cfg, self.controls, self.mtime, self.next_check = None, None, None, 0

        now = time.monotonic()
        self.closed, self.candidate, self.since = (), (), now
        self.position = "off"  # set by the switch
        self.rainbow_mode = False  # set by the encoder button
        self.speed, self.phase = 0.0, 0.0
        self.override = None  # state set from the command line, None = manual control
        self.history = []  # previous command line states, for "reset"
        self.display = "off"
        self.prev, self.trans_start = [], None
        self.last_frame, self.sent_at, self.last_time = [], 0.0, now
        self.running = True

    # Configuration

    def reload_config(self, now):
        if now < self.next_check:
            return
        self.next_check = now + 1
        try:
            m = os.stat(CONF).st_mtime
            if m == self.mtime:
                return
            self.mtime = m
            new = load_config(CONF)
            if not self.controls or not self.controls.matches(new):
                if self.controls:
                    self.controls.close()
                    self.controls = None
                self.controls = Controls(new, self.events)
                log(f"GPIO backend: {type(Device.pin_factory).__name__}")
            if self.cfg and self.cfg["led_count"] > new["led_count"]:
                self.strip.show([BLACK] * self.cfg["led_count"], self.cfg)  # clear the old tail
            if not self.cfg or new["rainbow_speed"] != self.cfg["rainbow_speed"]:
                self.speed = new["rainbow_speed"]
            if isinstance(self.override, int) and self.override > len(new["segments"]):
                self.override, self.history = None, []
            self.cfg, self.last_frame = new, []
            log(f"Config loaded: {new['led_count']} LEDs, brightness {int(new['brightness'] * 100)}%, "
                f"gamma {new['gamma']:g}, switch pins {new['switch_pins']} (active {new['switch_active']}), "
                f"encoder pins {new['encoder_pins'] or 'none'}, transition {new['transition']}")
        except ConfigError as e:
            log(f"Config error in {CONF}: {e}" + (" (keeping previous settings)" if self.cfg else ""))
        except Exception as e:  # file or GPIO problem
            log(f"Error: {e} (retrying)")
            self.mtime = None
            self.next_check = now + 5

    # Manual controls

    def take_over(self, reason):
        """A manual action cancels the command line state."""
        if self.override is not None:
            log(f"{reason}: manual control again, command line state released")
        self.override, self.history = None, []

    def set_speed(self, speed):
        self.speed = round(min(SPEED_MAX, max(SPEED_MIN, speed)), 2)
        log(f"Rainbow speed: {self.speed:g} turns/s")

    def handle_encoder(self):
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return
            if event == "press":
                # Toggle relative to what is shown, so a press always visibly does something
                self.rainbow_mode = self.display != "rainbow"
                self.take_over("Encoder pressed")
                log(f"Rainbow mode {'ON' if self.rainbow_mode else 'OFF'}")
            elif self.display == "rainbow":
                if self.override is not None:
                    self.rainbow_mode = True
                    self.take_over("Encoder turned")
                self.set_speed(self.speed + event * self.cfg["rainbow_step"])

    def read_switch(self, now):
        raw = self.controls.read_switch()
        if raw != self.candidate:
            self.candidate, self.since = raw, now
        elif raw != self.closed and now - self.since >= (SETTLE if raw else OFF_SETTLE):
            self.closed = raw
            self.position = self.controls.position(raw) or "off"
            log(f"Switch position: {describe(self.cfg, self.position)}  (closed: "
                f"{' '.join(f'GPIO{p}' for p in raw) or 'nothing'})")
            self.take_over("Switch turned")

    # Command line

    def parse_state(self, text):
        t = text.lower()
        if t in ("off", "rainbow"):
            return t
        if t.startswith("position"):
            t = t[len("position"):]
        segments = self.cfg["segments"]
        if t.isdigit() and 1 <= int(t) <= len(segments):
            return int(t)
        for i, seg in enumerate(segments, 1):
            if seg:
                label = seg[3].lower()
                if t in (label, "tlp:" + label) or (label.startswith("tlp:") and t == label[4:]):
                    return i
        return None

    def status(self):
        if self.override is None:
            control = "manual (switch and encoder)"
        else:
            control = f"command line, {len(self.history)} step(s) to reset back"
        return "\n".join([
            f"display: {describe(self.cfg, self.display)}",
            f"control: {control}",
            f"switch: {describe(self.cfg, self.position)}",
            f"rainbow mode (encoder): {'on' if self.rainbow_mode else 'off'}, speed {self.speed:g} turns/s",
            f"transition: {self.cfg['transition']}",
        ])

    def handle_command(self, line):
        args = line.split()
        if not args:
            return "error: empty command"
        cmd, rest = args[0].lower(), args[1:]

        if cmd == "status":
            return self.status()

        if cmd == "set":
            state = self.parse_state(rest[0]) if len(rest) == 1 else None
            if state is None:
                names = [seg[3] for seg in self.cfg["segments"] if seg]
                return ("error: usage: leds set STATE, with STATE one of: off, rainbow, "
                        f"1-{len(self.cfg['segments'])}, {', '.join(names)}")
            self.history.append(self.override)
            self.override = state
            log(f"Command line: set {describe(self.cfg, state)}")
            return f"ok: showing {describe(self.cfg, state)} until the switch or encoder is used"

        if cmd in ("reset", "undo"):
            if self.override is None:
                return "nothing to reset: manual control is active"
            self.override = self.history.pop() if self.history else None
            if self.override is None:
                log("Command line: reset, back to manual control")
                return f"ok: back to manual control, showing {describe(self.cfg, self.manual_state())}"
            log(f"Command line: reset to {describe(self.cfg, self.override)}")
            return f"ok: back to {describe(self.cfg, self.override)}"

        if cmd == "release":
            self.override, self.history = None, []
            log("Command line: release, back to manual control")
            return f"ok: manual control, showing {describe(self.cfg, self.manual_state())}"

        if cmd == "speed":
            try:
                self.set_speed(float(rest[0]))
            except (IndexError, ValueError):
                return f"error: usage: leds speed TURNS_PER_SECOND ({SPEED_MIN:g} to {SPEED_MAX:g})"
            return f"ok: rainbow speed {self.speed:g} turns/s"

        return f"error: unknown command '{cmd}' (try: leds help)"

    # Display

    def manual_state(self):
        return "rainbow" if self.rainbow_mode else self.position

    def render(self, now, dt):
        wanted = self.override if self.override is not None else self.manual_state()
        if wanted != self.display:
            self.display = wanted
            log(f"Display: {describe(self.cfg, wanted)}")
            self.prev, self.trans_start = self.last_frame, now

        cfg = self.cfg
        n = cfg["led_count"]
        if self.display == "rainbow":
            self.phase = (self.phase + self.speed * dt) % 1
            target = rainbow_frame(n, self.phase, cfg["rainbow_brightness"])
        else:
            target = static_frame(cfg, self.display)

        frame = target
        if self.trans_start is not None:
            duration = cfg["transition_ms"] / 1000
            elapsed = now - self.trans_start
            if cfg["transition"] == "none" or elapsed >= duration:
                self.trans_start = None
            else:
                frame = transition_frame(cfg, fit(self.prev, n), target, elapsed / duration, elapsed)

        # Re-sent regularly so a frame garbled on the data line doesn't stick
        animated = self.trans_start is not None or self.display == "rainbow"
        if animated or frame != self.last_frame or now - self.sent_at >= REFRESH:
            self.strip.show(frame, cfg)
            self.last_frame, self.sent_at = frame, now

    # Main loop

    def stop(self, *_):
        self.running = False

    def run(self):
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        try:
            while self.running:
                now = time.monotonic()
                dt, self.last_time = now - self.last_time, now
                self.reload_config(now)
                if not self.cfg or not self.controls:
                    time.sleep(1)
                    continue
                # Commands first, then manual controls, so a manual action in the
                # same instant always wins
                self.server.poll(self.handle_command)
                self.handle_encoder()
                self.read_switch(now)
                self.render(now, dt)
                time.sleep(FRAME_TIME)
        finally:
            self.strip.close(self.cfg)
            if self.controls:
                self.controls.close()
            self.server.close()


# --- Commands ---

USAGE = """Usage: leds COMMAND

  leds status            what is shown, and whether the switch/encoder or a command controls it
  leds set STATE         show STATE until the switch or encoder is used
                         STATE: off, rainbow, 1-4, or a position color (red, tlp:amber, ...)
  leds reset             go back to the previous command (after the first one: manual control)
  leds release           give control back to the switch and encoder right away
  leds speed TURNS       rainbow speed in turns per second
  leds identify          every 10th LED red, every 5th green (stop the service first)
  leds run               run the controller (used by the leds service)

Over SSH:  ssh pi@raspberrypi.local leds set tlp:amber"""


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


def main(args):
    if not args or args[0] in ("help", "-h", "--help"):
        print(USAGE)
        return 0
    if args == ["run"]:
        try:
            App().run()
        except RuntimeError as e:
            log(f"Error: {e}")
            return 1
        return 0
    if args == ["identify"]:
        identify()
        return 0
    return send_command(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
