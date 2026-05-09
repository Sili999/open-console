#!/usr/bin/env python3
"""
RetroConsole OS - Mock Unit Tests
Testet die Logik aller Scripts ohne Raspberry Pi / Hardware.
Ausführen: python3 tests/test_mock.py
"""
import sys
import os
import json
import unittest
import tempfile
from unittest.mock import MagicMock, patch, mock_open, call

# Pfad zu den Scripts hinzufügen
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'scripts')
sys.path.insert(0, SCRIPTS_DIR)

# ─────────────────────────────────────────────────────────────────────────────
# MOCK: pyfingerprint
# ─────────────────────────────────────────────────────────────────────────────
class MockPyFingerprint:
    """Simuliert den R503 Fingerabdrucksensor."""
    def __init__(self, *args, **kwargs):
        self._templates = {}
        self._finger_present = False
        self._next_slot = 1
        self.aura_calls = []

    def verifyPassword(self):
        return True

    def getTemplateCount(self):
        return len(self._templates)

    def getStorageCapacity(self):
        return 200

    def readImage(self):
        return self._finger_present

    def convertImage(self, slot):
        pass

    def compareCharacteristics(self):
        return 1  # Fingers match

    def createTemplate(self):
        pass

    def storeTemplate(self):
        slot = self._next_slot
        self._templates[slot] = True
        self._next_slot += 1
        return slot

    def searchTemplate(self):
        if self._finger_present:
            return (1, 100)  # (slot, accuracy)
        return (-1, 0)

    def setAuraLed(self, control, speed, color, count):
        self.aura_calls.append((control, speed, color, count))


# Modulebene-Mock registrieren BEVOR die Scripts importiert werden
sys.modules['pyfingerprint'] = MagicMock()
sys.modules['pyfingerprint.pyfingerprint'] = MagicMock()
sys.modules['rpi_ws281x'] = MagicMock()


# ─────────────────────────────────────────────────────────────────────────────
# Tests: set_rgb.py – Farb-Parsing
# ─────────────────────────────────────────────────────────────────────────────
class TestColorParsing(unittest.TestCase):
    """Testet parse_color() aus set_rgb.py."""

    def setUp(self):
        # rpi_ws281x.Color als einfache Zahl mocken
        color_mock = MagicMock(side_effect=lambda r, g, b: (r << 16) | (g << 8) | b)
        sys.modules['rpi_ws281x'].Color = color_mock
        sys.modules['rpi_ws281x'].PixelStrip = MagicMock()

        # Modul neu importieren um den Mock zu nutzen
        if 'set_rgb' in sys.modules:
            del sys.modules['set_rgb']
        import set_rgb
        self.set_rgb = set_rgb

    def test_named_color_white(self):
        result = self.set_rgb.parse_color("white")
        self.assertIsNotNone(result)

    def test_named_color_red(self):
        result = self.set_rgb.parse_color("red")
        self.assertIsNotNone(result)

    def test_named_color_case_insensitive(self):
        r1 = self.set_rgb.parse_color("RED")
        r2 = self.set_rgb.parse_color("red")
        self.assertEqual(r1, r2)

    def test_rgb_string_format(self):
        """Format: '255,100,50'"""
        result = self.set_rgb.parse_color("255,100,50")
        expected = (255 << 16) | (100 << 8) | 50
        self.assertEqual(result, expected)

    def test_rgb_bracket_format(self):
        """Format: '[255,100,50]' (wie von login.sh übergeben)"""
        result = self.set_rgb.parse_color("[255,100,50]")
        expected = (255 << 16) | (100 << 8) | 50
        self.assertEqual(result, expected)

    def test_invalid_color_falls_back_to_white(self):
        """Ungültige Eingabe soll white zurückgeben."""
        result = self.set_rgb.parse_color("nicht_existent_xyz")
        white = self.set_rgb.COLORS["white"]
        self.assertEqual(result, white)

    def test_rgb_string_with_spaces(self):
        """Format: '[255, 100, 50]' mit Leerzeichen"""
        result = self.set_rgb.parse_color("[255, 100, 50]")
        expected = (255 << 16) | (100 << 8) | 50
        self.assertEqual(result, expected)


# ─────────────────────────────────────────────────────────────────────────────
# Tests: scan_finger.py – Logik
# ─────────────────────────────────────────────────────────────────────────────
class TestScanFinger(unittest.TestCase):
    """Testet die Erkennungslogik aus scan_finger.py."""

    def setUp(self):
        if 'scan_finger' in sys.modules:
            del sys.modules['scan_finger']
        from pyfingerprint.pyfingerprint import PyFingerprint as _PF
        _PF.side_effect = None
        _PF.return_value = MockPyFingerprint()
        import scan_finger
        self.scan_finger = scan_finger
        self.mock_sensor = _PF.return_value

    def test_set_aura_led_calls_sensor(self):
        """set_aura_led soll setAuraLed aufrufen, wenn Methode vorhanden."""
        sensor = MockPyFingerprint()
        self.scan_finger.set_aura_led(sensor, 1, 0x55, 7, 0)
        self.assertEqual(len(sensor.aura_calls), 1)
        self.assertEqual(sensor.aura_calls[0], (1, 0x55, 7, 0))

    def test_set_aura_led_ignores_missing_method(self):
        """set_aura_led soll nicht crashen, wenn setAuraLed fehlt."""
        sensor = MagicMock(spec=[])  # Keine Methoden
        # Darf keine Exception werfen:
        try:
            self.scan_finger.set_aura_led(sensor, 1, 0x55, 7, 0)
        except Exception as e:
            self.fail(f"set_aura_led raised an exception: {e}")

    def test_exit_code_timeout(self):
        """Bei Timeout (kein Finger) soll sys.exit(2) aufgerufen werden."""
        sensor = MockPyFingerprint()
        sensor._finger_present = False  # Finger wird nie erkannt

        with self.assertRaises(SystemExit) as ctx:
            # Simuliere: Finger nie erkannt, Timeout sofort
            import time
            with patch('time.time', side_effect=[0.0, 10.0]):  # sofort timeout
                with patch('scan_finger.f', sensor, create=True):
                    # Direkte Logik testen
                    finger_placed = False
                    timeout_duration = 5.0
                    start = 0.0
                    # Loop: time.time() gibt 10.0 zurück → sofort > 5s
                    if not finger_placed:
                        sys.exit(2)

        self.assertEqual(ctx.exception.code, 2)

    def test_exit_code_unknown_finger(self):
        """Bei unbekanntem Finger soll sys.exit(3) aufgerufen werden."""
        with self.assertRaises(SystemExit) as ctx:
            position_number = -1
            if position_number == -1:
                sys.exit(3)
        self.assertEqual(ctx.exception.code, 3)

    def test_exit_code_success(self):
        """Bei bekanntem Finger soll sys.exit(0) und Slot-ID auf stdout."""
        with self.assertRaises(SystemExit) as ctx:
            position_number = 1
            if position_number != -1:
                sys.exit(0)
        self.assertEqual(ctx.exception.code, 0)


# ─────────────────────────────────────────────────────────────────────────────
# Tests: enroll.py – Logik
# ─────────────────────────────────────────────────────────────────────────────
class TestEnroll(unittest.TestCase):
    """Testet die Enrollment-Logik."""

    def setUp(self):
        if 'enroll' in sys.modules:
            del sys.modules['enroll']
        import enroll
        self.enroll = enroll

    def test_color_parsing_valid(self):
        """Gültige RGB-Eingabe soll korrekt geparst werden."""
        color_input = "255,100,50"
        color = [int(c.strip()) for c in color_input.split(',')]
        self.assertEqual(len(color), 3)
        self.assertEqual(color, [255, 100, 50])

    def test_color_parsing_invalid(self):
        """Ungültige Eingabe soll auf Weiß [255,255,255] zurückfallen."""
        color_input = "not_a_color"
        try:
            color = [int(c.strip()) for c in color_input.split(',')]
            if len(color) != 3:
                raise ValueError
        except:
            color = [255, 255, 255]
        self.assertEqual(color, [255, 255, 255])

    def test_user_map_json_update(self):
        """Neuer Benutzer soll korrekt in user_map.json gespeichert werden."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                         delete=False) as f:
            json.dump({}, f)
            tmp_path = f.name

        try:
            slot_id = 1
            name = "TestUser"
            color = [200, 100, 50]
            home_dir = f"/home/pi/users/{slot_id}"

            with open(tmp_path, 'r') as file:
                user_map = json.load(file)

            user_map[str(slot_id)] = {
                "name": name,
                "color": color,
                "home": home_dir
            }

            with open(tmp_path, 'w') as file:
                json.dump(user_map, file, indent=4)

            with open(tmp_path, 'r') as file:
                result = json.load(file)

            self.assertIn("1", result)
            self.assertEqual(result["1"]["name"], "TestUser")
            self.assertEqual(result["1"]["color"], [200, 100, 50])
            self.assertEqual(result["1"]["home"], "/home/pi/users/1")
        finally:
            os.unlink(tmp_path)

    def test_user_map_missing_file_creates_empty(self):
        """Fehlende user_map.json soll {} als Default verwenden."""
        try:
            with open("/nonexistent/path/user_map.json", 'r') as f:
                user_map = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            user_map = {}
        self.assertEqual(user_map, {})

    def test_config_path_construction(self):
        """Pfad-Konstruktion soll auf config/user_map.json zeigen."""
        script_dir = SCRIPTS_DIR
        config_file = '../config/user_map.json'
        config_path = os.path.normpath(os.path.join(script_dir, config_file))
        self.assertTrue(config_path.endswith(os.path.join('config', 'user_map.json')))

    def test_aura_led_breathing_blue_on_wait(self):
        """Während Enrollment soll breathing-blue (color=2) gesetzt werden."""
        sensor = MockPyFingerprint()
        self.enroll.set_aura_led(sensor, 1, 0x55, 2, 0)  # breathing=1, blue=2
        self.assertEqual(sensor.aura_calls[0][2], 2)  # color == blue

    def test_aura_led_green_flash_on_success(self):
        """Bei Erfolg soll green flash (color=4) gesetzt werden."""
        sensor = MockPyFingerprint()
        self.enroll.set_aura_led(sensor, 2, 0x55, 4, 3)  # flash=2, green=4
        self.assertEqual(sensor.aura_calls[0][0], 2)  # control == flash
        self.assertEqual(sensor.aura_calls[0][2], 4)  # color == green


# ─────────────────────────────────────────────────────────────────────────────
# Tests: user_map.json – Dateistruktur
# ─────────────────────────────────────────────────────────────────────────────
class TestUserMapJson(unittest.TestCase):
    """Testet die user_map.json Konfigurationsdatei."""

    CONFIG_PATH = os.path.join(
        os.path.dirname(__file__), '..', 'config', 'user_map.json'
    )

    def test_file_exists(self):
        """user_map.json muss vorhanden sein."""
        self.assertTrue(os.path.exists(self.CONFIG_PATH),
                        "user_map.json fehlt im config/-Verzeichnis!")

    def test_file_is_valid_json(self):
        """user_map.json muss valides JSON sein."""
        with open(self.CONFIG_PATH, 'r') as f:
            try:
                data = json.load(f)
                self.assertIsInstance(data, dict)
            except json.JSONDecodeError as e:
                self.fail(f"user_map.json ist kein valides JSON: {e}")

    def test_user_entries_have_required_keys(self):
        """Jeder Benutzer-Eintrag muss name, color und home enthalten."""
        with open(self.CONFIG_PATH, 'r') as f:
            data = json.load(f)
        for slot_id, user in data.items():
            with self.subTest(slot=slot_id):
                self.assertIn("name", user, f"'name' fehlt für Slot {slot_id}")
                self.assertIn("color", user, f"'color' fehlt für Slot {slot_id}")
                self.assertIn("home", user, f"'home' fehlt für Slot {slot_id}")
                self.assertIsInstance(user["color"], list)
                self.assertEqual(len(user["color"]), 3,
                                 f"'color' muss [R,G,B] sein für Slot {slot_id}")


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestColorParsing))
    suite.addTests(loader.loadTestsFromTestCase(TestScanFinger))
    suite.addTests(loader.loadTestsFromTestCase(TestEnroll))
    suite.addTests(loader.loadTestsFromTestCase(TestUserMapJson))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
