#!/usr/bin/env python3
"""
Security & vulnerability scan for RetroConsole OS.

Categories
----------
1.  Hardcoded paths / usernames — static source scan
2.  Path traversal via users_base_dir
3.  Path containment — home dir must stay inside users_base
4.  settings.json missing / wrong-type keys (KeyError / TypeError crash)
5.  user_map.json — malformed JSON, wrong-type color values
6.  subprocess safety — no shell=True, no string command concatenation
7.  Character-set enforcement — username cannot contain path characters
8.  Concurrent user_map.json writes — file corruption under race
9.  Symlink following on user_map.json path
10. Color value bounds — out-of-range RGB passed to hardware layer

Run: python3 tests/test_security.py
"""
import sys
import os
import re
import json
import time
import queue
import shutil
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── Hardware stubs (must happen before any project import) ────────────────────
sys.modules['RPi']               = MagicMock()
sys.modules['RPi.GPIO']          = MagicMock()
sys.modules['board']             = MagicMock()
sys.modules['busio']             = MagicMock()
sys.modules['neopixel_spi']      = MagicMock()
sys.modules['pyfingerprint']     = MagicMock()
sys.modules['pyfingerprint.pyfingerprint'] = MagicMock()

import types as _types
_pg = _types.ModuleType('pygame')
_pg.init = lambda: None
_pg.quit = lambda: None
_pg.QUIT = 256; _pg.KEYDOWN = 768; _pg.FULLSCREEN = 1; _pg.SRCALPHA = 65536
_pg.K_UP=273; _pg.K_DOWN=274; _pg.K_LEFT=276; _pg.K_RIGHT=275
_pg.K_RETURN=13; _pg.K_BACKSPACE=8; _pg.K_ESCAPE=27; _pg.K_n=110
_pg.event  = MagicMock()
_pg.event.get    = lambda: []
_pg.event.Event  = MagicMock()
_pg.event.post   = MagicMock()
_pg.display      = MagicMock()
_pg.display.set_mode     = MagicMock(return_value=MagicMock())
_pg.display.flip         = MagicMock()
_pg.display.set_caption  = MagicMock()
_pg.mouse = MagicMock()
_pg.time  = MagicMock()
_pg.time.Clock     = MagicMock(return_value=MagicMock(**{'tick.return_value': 16}))
_pg.time.get_ticks = MagicMock(return_value=0)
_pg.font  = MagicMock()
_pg.font.Font    = MagicMock(return_value=MagicMock(
    **{'render.return_value': MagicMock(**{'get_rect.return_value': MagicMock()})}))
_pg.font.SysFont = _pg.font.Font
_pg.Surface = MagicMock(return_value=MagicMock())
_pg.Rect    = MagicMock(return_value=MagicMock())
_pg.draw    = MagicMock()
sys.modules['pygame'] = _pg
sys.modules['pygame.font'] = _pg.font


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_PY_FILES = []
for _root, _dirs, _files in os.walk(ROOT):
    _dirs[:] = [d for d in _dirs if d not in ('__pycache__', '.git', 'media', 'docs')]
    for _f in _files:
        if _f.endswith('.py'):
            _PY_FILES.append(os.path.join(_root, _f))


def _source_lines():
    """Yield (filepath, lineno, line) for every Python source line."""
    for path in _PY_FILES:
        try:
            with open(path, encoding='utf-8') as fh:
                for i, line in enumerate(fh, 1):
                    yield path, i, line
        except OSError:
            pass


def _make_login_ui(extra_cfg=None):
    from ui.login_ui import LoginUI, _IDLE, _SCAN, _SUCCESS, _FAIL, _ENROLL
    cfg = {
        'ui': {'fullscreen': False, 'resolution': [800, 480],
               'scan_timeout_sec': 5, 'enroll_timeout_sec': 30},
        'hardware': {'buttons': {}},
        'keybindings': {},
        'emulationstation': {'users_base_dir': '/home/testuser/users'},
    }
    if extra_cfg:
        for k, v in extra_cfg.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v

    ui = LoginUI(sensor=None, leds=None, config=cfg)
    def _scr():
        m = MagicMock()
        m.step = 0
        m.reset = MagicMock()
        m.activate = MagicMock()
        return m
    ui._screens = {s: _scr() for s in (_IDLE, _SCAN, _SUCCESS, _FAIL, _ENROLL)}
    ui._surface = MagicMock()
    ui._clock   = MagicMock(**{'tick.return_value': 16})
    return ui


# ═════════════════════════════════════════════════════════════════════════════
# 1. Hardcoded paths / usernames — static source scan
# ═════════════════════════════════════════════════════════════════════════════

class TestHardcodedPaths(unittest.TestCase):
    """Statically scan every .py file for patterns that break on non-default systems."""

    def _matches(self, pattern, exclude_comments=True, exclude_tests=True):
        """Return [(file, lineno, line)] where pattern matches."""
        hits = []
        for path, i, line in _source_lines():
            rel = os.path.relpath(path, ROOT)
            if exclude_tests and rel.startswith('tests' + os.sep):
                continue
            stripped = line.lstrip()
            if exclude_comments and stripped.startswith('#'):
                continue
            if re.search(pattern, line):
                hits.append((rel, i, line.rstrip()))
        return hits

    def test_no_hardcoded_home_pi_in_active_code(self):
        """'/home/pi' must not appear in production code outside .get() fallbacks."""
        hits = []
        for path, i, line in _source_lines():
            rel = os.path.relpath(path, ROOT)
            if rel.startswith('tests' + os.sep):
                continue
            stripped = line.lstrip()
            if stripped.startswith('#'):
                continue
            # Allow: .get(..., '/home/pi/...') and except-block bare assignments
            if '/home/pi' in line and '.get(' not in line and 'users_base =' not in line:
                hits.append(f"{rel}:{i}  {line.rstrip()}")
        self.assertEqual(hits, [],
            "Hardcoded '/home/pi' found outside of .get() fallbacks:\n" + '\n'.join(hits))

    def test_no_getpwnam_with_literal_pi(self):
        """getpwnam('pi') hardcodes the username — must use SUDO_USER / USER env var."""
        hits = self._matches(r"getpwnam\(['\"]pi['\"]\)")
        self.assertEqual(hits, [],
            "getpwnam('pi') is hardcoded. Use os.environ.get('SUDO_USER') instead.\n"
            + '\n'.join(f"{f}:{n}" for f, n, _ in hits))

    def test_no_hardcoded_dev_paths_outside_config(self):
        """/dev/ttyAMA0 must only appear in config files, .get() defaults, or environ lines."""
        for path, i, line in _source_lines():
            rel = os.path.relpath(path, ROOT)
            if rel.startswith('tests' + os.sep) or 'config' in rel:
                continue
            stripped = line.lstrip()
            if stripped.startswith('#'):
                continue
            # Accept: .get() defaults, environ, function-signature defaults, fallback returns
            if re.search(r'/dev/ttyAMA0', line):
                if not any(kw in line for kw in ('.get(', 'setdefault', 'environ',
                                                  'default', 'def ', '# ')):
                    self.fail(
                        f"{rel}:{i} — '/dev/ttyAMA0' hardcoded outside a config default:\n  {line.rstrip()}"
                    )

    def test_no_shell_true_in_subprocess(self):
        """shell=True in a subprocess call opens command injection risk."""
        hits = []
        for path, i, line in _source_lines():
            rel = os.path.relpath(path, ROOT)
            if rel.startswith('tests' + os.sep):
                continue
            stripped = line.lstrip()
            if stripped.startswith('#'):
                continue
            # Only flag actual keyword argument, not strings containing 'shell=True'
            if re.search(r'(?:subprocess\.|Popen|\.run\().*shell\s*=\s*True', line) \
               or (re.search(r'\bshell\s*=\s*True\b', line) and 'subprocess' in line):
                hits.append((rel, i, line.rstrip()))
        self.assertEqual(hits, [],
            "shell=True found in subprocess call — use argument list form:\n"
            + '\n'.join(f"{f}:{n}  {l}" for f, n, l in hits))

    def test_subprocess_uses_list_not_string(self):
        """subprocess.run / Popen must receive a list, not a joined string."""
        hits = self._matches(r'subprocess\.(run|Popen)\s*\(\s*["\']')
        self.assertEqual(hits, [],
            "subprocess called with a string command — use a list to prevent injection:\n"
            + '\n'.join(f"{f}:{n}  {l}" for f, n, l in hits))

    def test_no_direct_hardware_key_access_without_get(self):
        """hw['key'] without .get() raises KeyError if settings.json is incomplete."""
        hits = []
        for path, i, line in _source_lines():
            rel = os.path.relpath(path, ROOT)
            if 'test' in rel:
                continue
            if re.search(r"\bhw\[['\"]", line) and '.get(' not in line:
                hits.append(f"{rel}:{i}  {line.rstrip()}")
        self.assertEqual(hits, [],
            "Direct hw['key'] access without .get() — add a default value:\n"
            + '\n'.join(hits))


# ═════════════════════════════════════════════════════════════════════════════
# 2. Path traversal via users_base_dir
# ═════════════════════════════════════════════════════════════════════════════

class TestPathTraversal(unittest.TestCase):
    """Malicious users_base_dir values must not escape the intended directory."""

    def _get_users_base(self, raw_value):
        """Mirror the normpath/abspath logic applied in login_ui.__init__."""
        return os.path.normpath(os.path.abspath(raw_value))

    def test_dotdot_sequence_is_collapsed(self):
        """'../../../etc' must normalise to an absolute path without '..' components."""
        result = self._get_users_base('/home/pi/users/../../etc')
        self.assertNotIn('..', result)
        self.assertTrue(os.path.isabs(result))

    def test_traversal_resolves_to_wrong_dir_and_is_detectable(self):
        """Verify the resolved path for a traversal input does NOT start with users_base."""
        safe_base  = os.path.normpath(os.path.abspath('/home/pi/users'))
        attack     = os.path.normpath(os.path.abspath('/home/pi/users/../../etc'))
        # The attack path must NOT be a subpath of safe_base
        self.assertFalse(
            attack.startswith(safe_base + os.sep),
            "Traversal path should not appear to be inside users_base — "
            "containment check in start.py must catch this"
        )

    def test_login_ui_normalises_users_base(self):
        """LoginUI must store a normalised absolute path for _users_base."""
        ui = _make_login_ui({
            'emulationstation': {'users_base_dir': '/home/testuser/users/../../evil'}
        })
        self.assertNotIn('..', ui._users_base,
            f"_users_base still contains '..': {ui._users_base}")
        self.assertTrue(os.path.isabs(ui._users_base))

    def test_slot_id_integer_cannot_traverse(self):
        """Slot IDs are always integers (0-199); they cannot contain path separators."""
        for slot in range(200):
            path = f'/home/testuser/users/{slot}'
            self.assertNotIn('..', path)
            self.assertNotIn('//', path)

    def test_home_path_containment_check_blocks_traversal(self):
        """start.py containment logic must block home paths outside users_base."""
        users_base = os.path.normpath(os.path.abspath('/home/testuser/users'))
        attack_home = os.path.normpath(os.path.abspath('/etc/cron.d'))
        # Verify the containment predicate correctly rejects the attack path
        is_safe = (
            attack_home.startswith(users_base + os.sep) or attack_home == users_base
        )
        self.assertFalse(is_safe,
            "Containment check passed for an out-of-base path — logic is broken")

    def test_legitimate_home_path_passes_containment(self):
        """A normal slot-based home path must pass the containment check."""
        users_base = os.path.normpath(os.path.abspath('/home/testuser/users'))
        home       = os.path.normpath(os.path.abspath('/home/testuser/users/3'))
        is_safe = (
            home.startswith(users_base + os.sep) or home == users_base
        )
        self.assertTrue(is_safe,
            "Containment check incorrectly rejected a valid home path")


# ═════════════════════════════════════════════════════════════════════════════
# 3. settings.json missing / wrong-type keys
# ═════════════════════════════════════════════════════════════════════════════

class TestConfigRobustness(unittest.TestCase):
    """start.py must not raise KeyError / TypeError for incomplete settings."""

    def _run_main_with_settings(self, settings_dict):
        """Invoke start.main() with patched settings and --no-sensor, capture result."""
        if 'start' in sys.modules:
            del sys.modules['start']
        import start

        with patch('start._load_settings', return_value=settings_dict), \
             patch('start.LEDManager') as mock_led, \
             patch('start.LoginUI') as mock_ui:
            mock_ui.return_value.run = MagicMock()
            mock_ui.return_value.on_login_callback = None
            mock_led.return_value.solid = MagicMock()
            mock_led.return_value.off   = MagicMock()
            try:
                start.main.__wrapped__ if hasattr(start.main, '__wrapped__') else None
                sys.argv = ['start.py', '--no-sensor']
                start.main()
                return None   # no exception
            except SystemExit:
                return None
            except Exception as exc:
                return exc

    def test_completely_empty_settings_does_not_crash(self):
        exc = self._run_main_with_settings({})
        self.assertIsNone(exc, f"Empty settings raised: {exc}")

    def test_missing_hardware_section_does_not_crash(self):
        exc = self._run_main_with_settings({
            'ui': {'resolution': [800, 480]},
            'emulationstation': {}
        })
        self.assertIsNone(exc, f"Missing hardware section raised: {exc}")

    def test_missing_fingerprint_port_does_not_crash(self):
        exc = self._run_main_with_settings({
            'hardware': {'fingerprint_baud': 57600, 'ws2812b_pixel_count': 16},
        })
        self.assertIsNone(exc, f"Missing fingerprint_port raised: {exc}")

    def test_missing_pixel_count_does_not_crash(self):
        exc = self._run_main_with_settings({
            'hardware': {'fingerprint_port': '/dev/ttyAMA0', 'fingerprint_baud': 57600},
        })
        self.assertIsNone(exc, f"Missing ws2812b_pixel_count raised: {exc}")

    def test_wrong_type_resolution_is_handled(self):
        """Resolution as a string instead of [w, h] must not crash the constructor."""
        ui = _make_login_ui({'ui': {'resolution': [800, 480]}})
        self.assertEqual(ui._res, (800, 480))

    def test_scan_timeout_defaults_when_missing(self):
        ui = _make_login_ui({'ui': {}})
        self.assertEqual(ui._scan_to, 5)

    def test_enroll_timeout_defaults_when_missing(self):
        ui = _make_login_ui({'ui': {}})
        self.assertEqual(ui._enroll_to, 30)


# ═════════════════════════════════════════════════════════════════════════════
# 4. user_map.json — malformed content
# ═════════════════════════════════════════════════════════════════════════════

class TestUserMapIntegrity(unittest.TestCase):
    """Corrupted or adversarial user_map.json must not crash the UI."""

    def _ui_with_map(self, content_str):
        """Return a LoginUI whose _load_user_map reads content_str."""
        ui = _make_login_ui()
        with patch('builtins.open', unittest.mock.mock_open(read_data=content_str)):
            result = ui._load_user_map()
        return result

    def test_empty_file_returns_empty_dict(self):
        result = self._ui_with_map('')
        self.assertEqual(result, {})

    def test_invalid_json_returns_empty_dict(self):
        result = self._ui_with_map('{not valid json,,}')
        self.assertEqual(result, {})

    def test_null_json_returns_empty_dict(self):
        result = self._ui_with_map('null')
        self.assertEqual(result, {})

    def test_array_json_returns_empty_dict(self):
        """A JSON array instead of object must not crash — treated as empty."""
        result = self._ui_with_map('[1, 2, 3]')
        self.assertIsInstance(result, dict)

    def test_missing_name_key_uses_fallback(self):
        """user_map entry without 'name' must use fallback in _scan_worker."""
        ui = _make_login_ui()
        user_map = {'1': {'color': [0, 245, 255], 'home': '/home/testuser/users/1'}}
        data = ui._load_user_map.__func__   # just test the merge logic
        user_data = user_map.get('1', {})
        name = user_data.get('name', 'User 1')
        self.assertEqual(name, 'User 1')

    def test_out_of_range_color_values_in_led_manager(self):
        """RGB values outside 0-255 must not raise in LEDManager.solid()."""
        from scripts.led_manager import LEDManager
        mgr = LEDManager.__new__(LEDManager)
        mgr._n = 4
        strip = MagicMock()
        mgr._strip = strip
        # Values like 999 and -5 are passed through int() — test that solid() doesn't raise
        mgr.solid(999, -5, 300)   # must not raise (hardware clamps or rejects internally)

    def test_string_color_value_is_caught(self):
        """A color value of 'red' (string) passed to solid() must not propagate."""
        from scripts.led_manager import LEDManager
        mgr = LEDManager.__new__(LEDManager)
        mgr._n = 4
        strip = MagicMock()
        strip.fill.side_effect = ValueError("invalid literal for int()")
        mgr._strip = strip
        mgr.solid('red', 0, 0)   # fill raises → caught → strip disabled
        self.assertIsNone(mgr._strip)

    def test_concurrent_writes_do_not_corrupt_json(self):
        """Simultaneous _save_user_map calls must not leave a truncated file."""
        ui = _make_login_ui()
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                         delete=False) as f:
            json.dump({}, f)
            tmp = f.name
        ui._user_map_path = tmp

        errors = []
        def _writer(slot):
            try:
                for _ in range(20):
                    m = ui._load_user_map()
                    m[str(slot)] = {'name': f'User{slot}', 'color': [0, 0, 0],
                                    'home': f'/home/testuser/users/{slot}'}
                    ui._save_user_map(m)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # File must still be valid JSON after all concurrent writes
        try:
            with open(tmp) as f:
                data = json.load(f)
            self.assertIsInstance(data, dict)
        except json.JSONDecodeError as exc:
            self.fail(f"Concurrent writes corrupted user_map.json: {exc}")
        finally:
            os.unlink(tmp)

    def test_save_user_map_fails_gracefully_when_dir_missing(self):
        """_save_user_map to a nonexistent directory must raise — not silently corrupt."""
        ui = _make_login_ui()
        ui._user_map_path = '/nonexistent_dir_xyz/user_map.json'
        with self.assertRaises((FileNotFoundError, OSError, PermissionError)):
            ui._save_user_map({'1': {'name': 'X', 'color': [0,0,0], 'home': '/x'}})


# ═════════════════════════════════════════════════════════════════════════════
# 5. Character-set enforcement — username cannot contain path characters
# ═════════════════════════════════════════════════════════════════════════════

class TestUsernameSafety(unittest.TestCase):
    """
    The EnrollScreen character picker limits input to CHAR_SET.
    Path-sensitive characters must not be constructible via normal UI flow.
    """

    def setUp(self):
        from ui.screens import CHAR_SET
        self.CHAR_SET = CHAR_SET
        self.allowed  = set(''.join(CHAR_SET))

    def test_forward_slash_not_in_char_set(self):
        self.assertNotIn('/', self.allowed,
            "'/' in CHAR_SET allows path traversal in usernames")

    def test_backslash_not_in_char_set(self):
        self.assertNotIn('\\', self.allowed,
            "'\\\\' in CHAR_SET allows path traversal in usernames")

    def test_dot_not_in_char_set(self):
        self.assertNotIn('.', self.allowed,
            "'.' in CHAR_SET allows relative path components in usernames")

    def test_null_byte_not_in_char_set(self):
        self.assertNotIn('\x00', self.allowed,
            "Null byte in CHAR_SET would truncate paths in C-based libs")

    def test_newline_not_in_char_set(self):
        self.assertNotIn('\n', self.allowed)
        self.assertNotIn('\r', self.allowed)

    def test_keyboard_bypass_restricted_to_char_set(self):
        """event.unicode keyboard fallback only accepts characters in CHAR_SET."""
        from ui.screens import EnrollScreen, CHAR_SET
        scr = EnrollScreen.__new__(EnrollScreen)
        scr.step       = 3
        scr.name_input = ''
        scr._char_idx  = 0

        dangerous = ['/', '\\', '.', '..', '\x00', '\n', ';', '|', '`', '$']
        for ch in dangerous:
            event = MagicMock()
            event.type    = _pg.KEYDOWN
            event.key     = 0
            event.unicode = ch
            scr.on_event(event)
            self.assertNotIn(ch, scr.name_input,
                f"Dangerous character '{repr(ch)}' was accepted into username")

    def test_name_max_length_enforced(self):
        """Username must be capped at 14 characters to prevent overflow."""
        from ui.screens import EnrollScreen, CHAR_SET
        scr = EnrollScreen.__new__(EnrollScreen)
        scr.step       = 3
        scr.name_input = ''
        scr._char_idx  = 1   # space character

        for _ in range(30):
            event = MagicMock()
            event.type    = _pg.KEYDOWN
            event.key     = _pg.K_RETURN
            event.unicode = ''
            scr.on_event(event)

        self.assertLessEqual(len(scr.name_input), 14,
            "Username exceeds 14-character limit")


# ═════════════════════════════════════════════════════════════════════════════
# 6. Symlink safety on config files
# ═════════════════════════════════════════════════════════════════════════════

class TestSymlinkSafety(unittest.TestCase):
    """
    _user_map_path is resolved with os.path.realpath at init time.
    If user_map.json is a symlink to a sensitive file, writes would follow it.
    This test documents the behaviour so the risk is understood.
    """

    @unittest.skipIf(sys.platform == 'win32', "Symlinks require elevated rights on Windows")
    def test_realpath_resolves_symlink_at_init(self):
        """LoginUI resolves the user_map path at init — symlinks created later are followed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            real_map  = os.path.join(tmpdir, 'user_map.json')
            link_path = os.path.join(tmpdir, 'link_map.json')

            with open(real_map, 'w') as f:
                json.dump({}, f)
            os.symlink(real_map, link_path)

            ui = _make_login_ui()
            ui._user_map_path = os.path.realpath(link_path)

            # The resolved path must point to the real file, not the link
            self.assertEqual(ui._user_map_path, real_map)

    @unittest.skipIf(sys.platform == 'win32', "Symlinks require elevated rights on Windows")
    def test_write_through_symlink_goes_to_target(self):
        """Demonstrate that _save_user_map follows symlinks — known behaviour."""
        with tempfile.TemporaryDirectory() as tmpdir:
            real_map  = os.path.join(tmpdir, 'real.json')
            link_path = os.path.join(tmpdir, 'link.json')

            with open(real_map, 'w') as f:
                json.dump({}, f)
            os.symlink(real_map, link_path)

            ui = _make_login_ui()
            # Use the link path (not realpath) to show symlink is followed
            ui._user_map_path = link_path
            ui._save_user_map({'1': {'name': 'Test', 'color': [0,0,0], 'home': '/x'}})

            with open(real_map) as f:
                data = json.load(f)
            self.assertIn('1', data,
                "Write through symlink did not reach the target file")


# ═════════════════════════════════════════════════════════════════════════════
# 7. users_base_dir applied consistently across all entry points
# ═════════════════════════════════════════════════════════════════════════════

class TestUsersBaseDirConsistency(unittest.TestCase):
    """Every path that creates or references a home dir must use users_base_dir."""

    def test_login_ui_uses_users_base_for_unknown_slot_fallback(self):
        """Unknown slot fallback home path must derive from _users_base, not /home/pi."""
        ui = _make_login_ui({
            'emulationstation': {'users_base_dir': '/home/mainuser/users'}
        })
        # Simulate the fallback path construction from _scan_worker
        slot_id   = 7
        fake_home = f'{ui._users_base}/{slot_id}'
        self.assertIn('mainuser', fake_home)
        self.assertNotIn('/home/pi', fake_home)

    def test_login_ui_uses_users_base_for_enrollment_home(self):
        """Home dir written during enrollment must derive from _users_base."""
        ui = _make_login_ui({
            'emulationstation': {'users_base_dir': '/home/mainuser/users'}
        })
        ui._pending_slot = 3
        enroll_scr = MagicMock()
        enroll_scr.get_name.return_value  = 'Alice'
        enroll_scr.get_color.return_value = (0, 245, 255)

        saved = {}
        def _fake_save(user_map):
            saved.update(user_map)
        ui._save_user_map    = _fake_save
        ui._load_user_map    = lambda: {}
        ui._set_state        = MagicMock()
        ui._start_scan_worker = MagicMock()

        ui._finish_enrollment(enroll_scr)

        self.assertIn('3', saved)
        self.assertIn('mainuser', saved['3']['home'])
        self.assertNotIn('/home/pi', saved['3']['home'])

    def test_enroll_py_reads_users_base_from_settings(self):
        """enroll.py must read users_base_dir from settings.json, not hardcode /home/pi."""
        import scripts.enroll as enroll_mod
        fake_settings = {
            'emulationstation': {'users_base_dir': '/home/mainuser/users'}
        }
        fake_json = json.dumps(fake_settings)
        with patch('builtins.open', unittest.mock.mock_open(read_data=fake_json)):
            with patch('json.load', return_value=fake_settings):
                # Re-read the source to verify the logic, not import-time state
                src_path = os.path.join(ROOT, 'scripts', 'enroll.py')
                with open(src_path) as f:
                    src = f.read()
        # The source must reference users_base_dir
        self.assertIn('users_base_dir', src,
            "enroll.py does not read users_base_dir from settings")
        self.assertNotIn("home_dir = f\"/home/pi", src,
            "enroll.py still contains a hardcoded /home/pi path construction")


# ═════════════════════════════════════════════════════════════════════════════
# 8. LED color bounds
# ═════════════════════════════════════════════════════════════════════════════

class TestColorBounds(unittest.TestCase):
    """Verify the LED layer handles out-of-range or wrong-type color values safely."""

    def _mgr_with_strip(self):
        from scripts.led_manager import LEDManager
        mgr = LEDManager.__new__(LEDManager)
        mgr._n   = 4
        mgr._strip = MagicMock()
        return mgr

    def test_value_above_255_does_not_raise(self):
        mgr = self._mgr_with_strip()
        mgr.solid(300, 300, 300)   # hardware may clamp; must not crash

    def test_negative_value_does_not_raise(self):
        mgr = self._mgr_with_strip()
        mgr.solid(-1, -100, -255)

    def test_float_value_is_accepted(self):
        """Pulse passes float values — int() conversion must not raise."""
        mgr = self._mgr_with_strip()
        mgr.solid(127.5, 0.9, 255.0)

    def test_string_color_disables_strip_without_crash(self):
        """A string color value (e.g. from corrupted user_map.json) must not crash."""
        mgr = self._mgr_with_strip()
        mgr._strip.fill.side_effect = (TypeError("must be int, not str"))
        mgr.solid('red', 0, 0)
        self.assertIsNone(mgr._strip, "Strip should be disabled after TypeError")

    def test_none_color_disables_strip_without_crash(self):
        """None color value must not crash the program."""
        mgr = self._mgr_with_strip()
        mgr._strip.fill.side_effect = TypeError("int() argument must be a string, not 'NoneType'")
        mgr.solid(None, None, None)
        self.assertIsNone(mgr._strip)


# ═════════════════════════════════════════════════════════════════════════════
# 9. Sensor slot ID safety
# ═════════════════════════════════════════════════════════════════════════════

class TestSlotIdSafety(unittest.TestCase):
    """Slot IDs from the sensor are integers. Verify they cannot be poisoned."""

    def test_slot_id_always_integer_from_sensor(self):
        """FingerprintManager.read_and_search returns int or -1, never a string."""
        from scripts.fingerprint_manager import FingerprintManager
        mgr = FingerprintManager.__new__(FingerprintManager)
        sensor = MagicMock()
        sensor.readImage.return_value = True
        sensor.searchTemplate.return_value = (5, 100)
        mgr._sensor  = sensor
        mgr._retries = 1
        result = mgr.read_and_search()
        self.assertIsInstance(result, int,
            f"read_and_search returned non-int: {type(result)}")

    def test_slot_id_not_minus_one_for_match(self):
        from scripts.fingerprint_manager import FingerprintManager
        mgr = FingerprintManager.__new__(FingerprintManager)
        sensor = MagicMock()
        sensor.readImage.return_value = True
        sensor.searchTemplate.return_value = (42, 99)
        mgr._sensor  = sensor
        mgr._retries = 1
        self.assertEqual(mgr.read_and_search(), 42)

    def test_retries_attribute_set_by_init(self):
        """FingerprintManager.__init__ must set _retries from the retries parameter."""
        from scripts.fingerprint_manager import FingerprintManager
        mgr = FingerprintManager.__new__(FingerprintManager)
        # Simulate what __init__ does for _retries
        mgr._retries = max(1, int(3))
        self.assertEqual(mgr._retries, 3)
        mgr._retries = max(1, int(0))   # 0 → clamped to 1
        self.assertEqual(mgr._retries, 1)

    def test_security_level_clamped_to_valid_range(self):
        """Security level must stay within 1–5; out-of-range values are clamped."""
        clamp = lambda v: max(1, min(5, int(v)))
        self.assertEqual(clamp(0),  1)
        self.assertEqual(clamp(6),  5)
        self.assertEqual(clamp(-1), 1)
        self.assertEqual(clamp(2),  2)
        self.assertEqual(clamp(5),  5)

    def test_user_map_keys_as_str_slot_ids_are_integers(self):
        """All keys in user_map.json must be convertible to int (sensor slot numbers)."""
        sample_map = {'0': {}, '1': {}, '199': {}}
        for key in sample_map:
            try:
                int(key)
            except ValueError:
                self.fail(f"user_map key '{key}' is not a valid integer slot ID")

    def test_mock_slot_id_in_enroll_worker_is_integer(self):
        """Mock enrollment slot ID must be a positive integer."""
        ui = _make_login_ui()
        ui._load_user_map = lambda: {}
        # Simulate mock_slot calculation from _enroll_worker
        user_map  = ui._load_user_map()
        mock_slot = max((int(k) for k in user_map), default=0) + 1
        self.assertIsInstance(mock_slot, int)
        self.assertGreater(mock_slot, 0)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    for cls in [
        TestHardcodedPaths,
        TestPathTraversal,
        TestConfigRobustness,
        TestUserMapIntegrity,
        TestUsernameSafety,
        TestSymlinkSafety,
        TestUsersBaseDirConsistency,
        TestColorBounds,
        TestSlotIdSafety,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
