#!/usr/bin/env python3
"""Unified R503 fingerprint sensor manager for RetroConsole OS."""
import time
import threading

try:
    from pyfingerprint.pyfingerprint import PyFingerprint
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class FingerprintManager:
    """
    Manages all R503 sensor interactions: scanning, enrollment, and Aura LED.

    Aura LED command 0x35 is sent as a raw UART packet via pyfingerprint's
    internal serial handle when the library does not expose setAuraLed
    (which is the case with the current PyPI release of pyfingerprint).

    The stop_event parameter on wait_for_finger() lets the caller cancel a
    blocking poll without killing the thread — used by LoginUI to exit the
    idle scan loop when the user navigates to enrollment.
    """

    def __init__(self, port='/dev/ttyAMA0', baud=57600,
                 address=0xFFFFFFFF, password=0x00000000):
        if not _AVAILABLE:
            raise ImportError(
                "pyfingerprint not installed — run: sudo pip3 install pyfingerprint"
            )
        self._sensor = PyFingerprint(port, baud, address, password)
        if not self._sensor.verifyPassword():
            raise ValueError("Fingerprint sensor password verification failed.")

    # ── LED control ──────────────────────────────────────────────────────────

    def set_aura_led(self, control, speed, color, count):
        """
        control : 1=breathing  2=flashing  3=always-on  4=off
        speed   : 0x00–0xFF   (0x55 = medium)
        color   : 1=red 2=blue 3=purple 4=green 5=yellow 6=cyan 7=white
        count   : 0=infinite   N=repeat N times
        """
        if hasattr(self._sensor, 'setAuraLed'):
            try:
                self._sensor.setAuraLed(control, speed, color, count)
                return
            except Exception:
                pass
        self._raw_aura_led(control, speed, color, count)

    def _raw_aura_led(self, control, speed, color, count):
        """Send Aura LED command 0x35 directly via the sensor's serial port."""
        try:
            serial_port = self._sensor._PyFingerprint__serial
        except AttributeError:
            return

        header  = bytes([0xEF, 0x01])
        addr    = bytes([0xFF, 0xFF, 0xFF, 0xFF])
        pid     = bytes([0x01])
        payload = bytes([0x35, control, speed, color, count])
        length  = len(payload) + 2
        cs      = pid[0] + (length >> 8) + (length & 0xFF) + sum(payload)
        packet  = (header + addr + pid
                   + bytes([(length >> 8) & 0xFF, length & 0xFF])
                   + payload
                   + bytes([(cs >> 8) & 0xFF, cs & 0xFF]))
        serial_port.write(packet)
        time.sleep(0.06)
        try:
            pending = serial_port.in_waiting
            if pending:
                serial_port.read(pending)
        except Exception:
            pass

    def led_off(self):
        self.set_aura_led(4, 0x00, 1, 0)

    # ── Scanning ──────────────────────────────────────────────────────────────

    def wait_for_finger(self, timeout=30, stop_event=None):
        """
        Poll until a finger is placed or timeout expires.

        stop_event: optional threading.Event — if set, returns False immediately.
        Returns True if a finger was detected, False on timeout or cancel.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if stop_event and stop_event.is_set():
                return False
            if self._sensor.readImage():
                return True
            time.sleep(0.05)
        return False

    def read_and_search(self):
        """
        Convert the current image and search templates.
        Must be called immediately after readImage() returned True.

        Returns slot_id >= 0 on match, -1 on unknown finger.
        """
        self._sensor.convertImage(0x01)
        return self._sensor.searchTemplate()[0]

    # ── Enrollment helpers ────────────────────────────────────────────────────

    def enroll_convert_first(self):
        """Convert the already-captured first image into characteristic slot 1."""
        self._sensor.convertImage(0x01)

    def wait_for_removal(self, stop_event=None):
        """Block until the finger is lifted from the sensor."""
        while True:
            if stop_event and stop_event.is_set():
                return
            if not self._sensor.readImage():
                return
            time.sleep(0.05)

    def enroll_convert_second(self):
        """Convert the already-captured second image into characteristic slot 2."""
        self._sensor.convertImage(0x02)

    def enroll_create_and_store(self):
        """
        Compare, create, and store the template from slots 1 and 2.

        Returns the assigned slot_id on success.
        Raises ValueError if the two scans don't match.
        """
        if self._sensor.compareCharacteristics() == 0:
            raise ValueError("Fingerprints do not match — please try again.")
        self._sensor.createTemplate()
        return self._sensor.storeTemplate()

    # ── Info ──────────────────────────────────────────────────────────────────

    def get_template_count(self):
        return self._sensor.getTemplateCount()

    def get_storage_capacity(self):
        return self._sensor.getStorageCapacity()
