#!/usr/bin/env python3
"""
GPIO button input manager — maps 8 physical buttons to Pygame KEYDOWN events.

Buttons are assumed active-low: press connects pin to GND.
Each pin uses the built-in pull-up resistor (no external resistor needed).

Default GPIO→key mapping (BCM numbering, change in settings.json):
  up       → GPIO 17 → K_UP
  down     → GPIO 27 → K_DOWN
  left     → GPIO 22 → K_LEFT
  right    → GPIO 23 → K_RIGHT
  confirm  → GPIO 24 → K_RETURN
  back     → GPIO 25 → K_BACKSPACE
  new_user → GPIO  5 → K_n
  quit     → GPIO  6 → K_ESCAPE

Wiring per button:
  Pin → 220 Ω resistor → button → GND
  (the 220 Ω is optional but protects against accidental shorts)
"""
import pygame

try:
    import RPi.GPIO as GPIO
    _GPIO_OK = True
except ImportError:
    _GPIO_OK = False

# BCM pin → pygame key constant
_DEFAULT_PIN_MAP = {
    17: pygame.K_UP,
    27: pygame.K_DOWN,
    22: pygame.K_LEFT,
    23: pygame.K_RIGHT,
    24: pygame.K_RETURN,
    25: pygame.K_BACKSPACE,
     5: pygame.K_n,
     6: pygame.K_ESCAPE,
}


class ButtonManager:
    """
    Registers GPIO edge-detect callbacks that inject Pygame KEYDOWN events.

    Must be started AFTER pygame.init() because it posts Pygame events.
    Falls back to a silent no-op on non-Pi systems (no RPi.GPIO available).
    """

    def __init__(self, pin_map=None, bouncetime_ms=220):
        """
        pin_map      : dict {bcm_pin: pygame_key} — overrides the default map.
        bouncetime_ms: hardware debounce window in milliseconds.
        """
        self._map        = pin_map if pin_map is not None else _DEFAULT_PIN_MAP
        self._bounce     = bouncetime_ms
        self._registered = []

    def start(self):
        """Set up GPIO and register edge-detect callbacks."""
        if not _GPIO_OK:
            return
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for pin, key in self._map.items():
            try:
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                GPIO.add_event_detect(
                    pin,
                    GPIO.FALLING,
                    callback=self._make_callback(key),
                    bouncetime=self._bounce,
                )
                self._registered.append(pin)
            except Exception as exc:
                print(f"[ButtonManager] Warning: could not register GPIO {pin}: {exc}")

    def stop(self):
        """Remove GPIO event detection and clean up pins."""
        if _GPIO_OK and self._registered:
            try:
                GPIO.cleanup(self._registered)
            except Exception:
                pass
            self._registered.clear()

    @staticmethod
    def _make_callback(key):
        """Return a closure that posts a Pygame KEYDOWN event for `key`."""
        def _cb(_pin):
            try:
                event = pygame.event.Event(
                    pygame.KEYDOWN,
                    key=key, mod=0, unicode='', scancode=0,
                )
                pygame.event.post(event)
            except Exception:
                pass   # Pygame may not be initialised yet during early boot
        return _cb


_DEFAULT_KEYBINDINGS = {
    'up':       'K_UP',
    'down':     'K_DOWN',
    'left':     'K_LEFT',
    'right':    'K_RIGHT',
    'confirm':  'K_RETURN',
    'back':     'K_BACKSPACE',
    'new_user': 'K_n',
    'quit':     'K_ESCAPE',
}


def _build_pin_map(button_cfg, keybinding_cfg=None):
    """
    Convert settings.json button and keybinding dicts to a {pin: pygame_key} map.

    button_cfg     : {"up": 17, "down": 27, ...}   (name → GPIO pin)
    keybinding_cfg : {"up": "K_UP", ...}            (name → pygame key string)
                     Falls back to _DEFAULT_KEYBINDINGS when omitted.
    """
    bindings = dict(_DEFAULT_KEYBINDINGS)
    if keybinding_cfg:
        bindings.update(keybinding_cfg)

    result = {}
    for name, pin in button_cfg.items():
        key_str = bindings.get(name)
        if key_str is None:
            continue
        key = getattr(pygame, key_str, None)
        if key is None:
            print(f"[ButtonManager] Unknown pygame key '{key_str}' for button '{name}' — skipped.")
            continue
        result[pin] = key
    return result


# ── Quick test / standalone demo ────────────────────────────────────────────
if __name__ == '__main__':
    import time
    pygame.init()
    pygame.display.set_mode((320, 240))

    mgr = ButtonManager()
    mgr.start()
    print("ButtonManager running. Press Ctrl-C to stop.")
    print("Active pins:", list(_DEFAULT_PIN_MAP.keys()))

    try:
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.KEYDOWN:
                    name = pygame.key.name(ev.key)
                    print(f"  Button press → key={name!r}")
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        mgr.stop()
        pygame.quit()
