#!/usr/bin/env python3
"""WS2812B LED manager using neopixel_spi — compatible with Raspberry Pi 5.

rpi_ws281x (DMA-based) is NOT supported on Pi 5 (RP1 chip).
adafruit-circuitpython-neopixel-spi uses the SPI bus and works correctly.

Install on Pi:
    sudo pip3 install adafruit-circuitpython-neopixel-spi adafruit-blinka
"""
import time

try:
    import board
    import busio
    import neopixel_spi as _neopixel_spi
    _HW_AVAILABLE = True
except (ImportError, NotImplementedError):
    _HW_AVAILABLE = False


class LEDManager:
    """
    Controls a WS2812B strip via SPI (GPIO 10 / MOSI).

    Falls back to a silent no-op stub when running outside Pi hardware so
    the rest of the system remains testable on a development machine.
    """

    def __init__(self, n_pixels=16):
        self._n = n_pixels
        self._strip = None
        if _HW_AVAILABLE:
            try:
                spi = busio.SPI(board.SCK, MOSI=board.MOSI)
                self._strip = _neopixel_spi.NeoPixel_SPI(
                    spi, n_pixels,
                    pixel_order=_neopixel_spi.GRB,
                    auto_write=False,
                    brightness=1.0,
                )
            except Exception as exc:
                print(f"[LEDManager] SPI init failed ({exc}) — LEDs disabled. "
                      "Check dtparam=spi=on in /boot/firmware/config.txt.")

    def solid(self, r, g, b):
        if self._strip is None:
            return
        try:
            self._strip.fill((int(r), int(g), int(b)))
            self._strip.show()
        except Exception as exc:
            print(f"[LEDManager] LED write failed ({exc}) — disabling strip.")
            self._strip = None

    def flash(self, r, g, b, times=3, on_ms=200, off_ms=200):
        for _ in range(times):
            self.solid(r, g, b)
            time.sleep(on_ms / 1000.0)
            self.solid(0, 0, 0)
            time.sleep(off_ms / 1000.0)

    def pulse(self, r, g, b, steps=50, delay=0.02):
        """One breathing cycle — fade in then fade out."""
        for i in range(steps + 1):
            f = i / steps
            self.solid(r * f, g * f, b * f)
            time.sleep(delay)
        for i in range(steps, -1, -1):
            f = i / steps
            self.solid(r * f, g * f, b * f)
            time.sleep(delay)

    def off(self):
        self.solid(0, 0, 0)
