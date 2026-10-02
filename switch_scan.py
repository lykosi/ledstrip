#!/usr/bin/env python3
"""Find out which switch terminals connect in each position.

Wire every switch terminal to its own GPIO (nothing to GND), then run:
  python3 switch_scan.py 17 27 22 23 24 25 12 16
The GPIOs are listed in terminal order: the first is terminal 1, the second
terminal 2, and so on. Turn the switch slowly; each time the connections
change, the terminals that are connected together are printed.
Uses its own GPIOs, so the leds service can keep running.
"""
import os
import sys
import time

os.environ.setdefault("LG_WD", "/tmp")
import lgpio


def scan(h, pins):
    """Groups of terminal numbers (1-based) that are connected together."""
    groups, seen = [], set()
    for i, p in enumerate(pins):
        if i in seen:
            continue
        lgpio.gpio_claim_output(h, p, 0)
        time.sleep(0.002)
        group = [i] + [j for j, q in enumerate(pins) if j != i and lgpio.gpio_read(h, q) == 0]
        lgpio.gpio_claim_input(h, p, lgpio.SET_PULL_UP)
        if len(group) > 1:
            groups.append(tuple(t + 1 for t in sorted(group)))
            seen.update(group)
    return groups


def main():
    try:
        pins = [int(p) for p in sys.argv[1:]]
    except ValueError:
        pins = []
    if len(pins) < 2:
        print(__doc__)
        sys.exit(1)

    h = lgpio.gpiochip_open(0)
    for p in pins:
        lgpio.gpio_claim_input(h, p, lgpio.SET_PULL_UP)
    print("Terminals: " + "  ".join(f"{t}=GPIO{p}" for t, p in enumerate(pins, 1)))
    print("Turn the switch slowly through every position. Ctrl+C to stop.\n")

    last, candidate, since = None, None, time.monotonic()
    try:
        while True:
            groups = scan(h, pins)
            now = time.monotonic()
            if groups != candidate:
                candidate, since = groups, now
            elif groups != last and now - since >= 0.1:
                last = groups
                text = "   ".join("-".join(map(str, g)) for g in groups) or "nothing connected"
                print(f"{time.strftime('%H:%M:%S')}  connected: {text}", flush=True)
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        lgpio.gpiochip_close(h)


if __name__ == "__main__":
    main()
