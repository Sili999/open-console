#!/usr/bin/env python3
"""
RetroConsole OS — entry point.

Replaces login.sh. Starts the Pygame login UI, coordinates hardware,
and launches EmulationStation after a successful fingerprint login.

Usage
-----
    python3 start.py               # normal (uses config/settings.json)
    python3 start.py --no-sensor   # UI-only demo without fingerprint hardware
"""
import sys
import os
import json
import argparse
import subprocess
import shutil

_BASE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, _BASE)

from scripts.led_manager import LEDManager
from ui.login_ui import LoginUI


def _load_settings():
    path = os.path.join(_BASE, 'config', 'settings.json')
    with open(path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description='RetroConsole OS login')
    parser.add_argument('--no-sensor', action='store_true',
                        help='Skip fingerprint hardware (demo / dev mode)')
    args = parser.parse_args()

    cfg = _load_settings()
    hw  = cfg['hardware']

    # ── LEDs ─────────────────────────────────────────────────────────────────
    leds = LEDManager(n_pixels=hw['ws2812b_pixel_count'])
    leds.solid(0, 50, 70)   # dim cyan = system ready

    # ── Fingerprint sensor ────────────────────────────────────────────────────
    sensor = None
    if not args.no_sensor:
        try:
            from scripts.fingerprint_manager import FingerprintManager
            sensor = FingerprintManager(
                port=hw['fingerprint_port'],
                baud=hw['fingerprint_baud'],
            )
            print("[start] Fingerprint sensor initialised.")
        except Exception as exc:
            print(f"[start] Sensor unavailable ({exc}) — running in demo mode.")

    # ── UI ────────────────────────────────────────────────────────────────────
    ui = LoginUI(sensor=sensor, leds=leds, config=cfg)

    def on_login(slot_id, user_data):
        """Called in a daemon thread after the SUCCESS screen display delay."""
        color = user_data.get('color', [255, 255, 255])
        leds.solid(*color)

        es_cfg = cfg.get('emulationstation', {})
        es_bin = es_cfg.get('binary', 'emulationstation')
        home   = user_data.get('home', f'/home/pi/users/{slot_id}')

        if shutil.which(es_bin):
            print(f"[start] Launching {es_bin} --home {home}")
            subprocess.run([es_bin, '--home', home])
        else:
            print(f"[start] '{es_bin}' not found — simulating 5 s session.")
            import time
            time.sleep(5)

        leds.off()
        ui.reset_to_idle()

    ui.on_login_callback = on_login
    ui.run()   # blocks until quit
    leds.off()


if __name__ == '__main__':
    main()
