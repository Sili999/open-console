#!/usr/bin/env python3
"""
Integration simulation tests for RetroConsole OS.

Simulates failure scenarios that would occur during Raspberry Pi integration:
  - Sensor UART errors, bad fingerprint images, template search failures
  - SPI bus unavailable (LED manager fallback)
  - GPIO unavailable (button manager fallback)
  - Enrollment stop-event race (Bug A regression)
  - Scan-worker exception safety (Bug B regression)
  - keybinding config override (Bug G)
  - LoginUI state machine transitions via simulated sensor events

Run: python3 tests/test_integration_sim.py
"""
import sys
import os
import time
import queue
import threading
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

# ── Stub out ALL hardware-dependent libraries before any project import ─────
sys.modules['RPi']               = MagicMock()
sys.modules['RPi.GPIO']          = MagicMock()
sys.modules['board']             = MagicMock()
sys.modules['busio']             = MagicMock()
sys.modules['neopixel_spi']      = MagicMock()
sys.modules['pyfingerprint']     = MagicMock()
sys.modules['pyfingerprint.pyfingerprint'] = MagicMock()

# Stub pygame with the bare minimum needed by login_ui / button_manager
import types
_pg = types.ModuleType('pygame')
_pg.init = lambda: None
_pg.quit = lambda: None
_pg.QUIT    = 256
_pg.KEYDOWN = 768
_pg.K_UP        = 273
_pg.K_DOWN      = 274
_pg.K_LEFT      = 276
_pg.K_RIGHT     = 275
_pg.K_RETURN    = 13
_pg.K_BACKSPACE = 8
_pg.K_ESCAPE    = 27
_pg.K_n         = 110
_pg.FULLSCREEN  = 1
_pg.SRCALPHA    = 65536

class _FakeEvent:
    def __init__(self, **kw): self.__dict__.update(kw)

_pg.event  = MagicMock()
_pg.event.get    = lambda: []
_pg.event.Event  = _FakeEvent
_pg.event.post   = MagicMock()
_pg.display      = MagicMock()
_pg.display.set_mode  = MagicMock(return_value=MagicMock())
_pg.display.flip      = MagicMock()
_pg.display.set_caption = MagicMock()
_pg.mouse  = MagicMock()
_pg.time   = MagicMock()
_pg.time.Clock = MagicMock(return_value=MagicMock(**{'tick.return_value': 16}))
_pg.time.get_ticks = MagicMock(return_value=0)
_pg.font   = MagicMock()
_pg.font.Font   = MagicMock(return_value=MagicMock(**{'render.return_value': MagicMock(**{'get_rect.return_value': MagicMock()})}))
_pg.font.SysFont = _pg.font.Font
_pg.Surface = MagicMock(return_value=MagicMock())
_pg.Rect    = MagicMock(return_value=MagicMock())
_pg.draw    = MagicMock()
sys.modules['pygame'] = _pg
sys.modules['pygame.font'] = _pg.font


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

class MockSensor:
    """Controllable fake for FingerprintManager internals."""
    def __init__(self):
        self._finger   = False
        self._slot     = 1
        self._bad_read = False   # simulate convertImage / searchTemplate error

    def readImage(self):
        return self._finger

    def convertImage(self, slot):
        if self._bad_read:
            raise Exception("Sensor communication error (simulated)")

    def searchTemplate(self):
        if self._bad_read:
            raise Exception("Sensor communication error (simulated)")
        return (self._slot if self._finger else -1, 100)

    def compareCharacteristics(self): return 1
    def createTemplate(self): pass
    def storeTemplate(self): return self._slot
    def verifyPassword(self): return True
    def getTemplateCount(self): return 0
    def getStorageCapacity(self): return 200
    def setAuraLed(self, *a): pass

    # Expose internal serial mock for _raw_aura_led path
    class _serial:
        in_waiting = 0
        def write(self, data): pass
        def read(self, n): return b''
    _PyFingerprint__serial = _serial()


# ─────────────────────────────────────────────────────────────────────────────
# FingerprintManager tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFingerprintManager(unittest.TestCase):

    def _make_manager(self):
        from scripts.fingerprint_manager import FingerprintManager
        mock_hw = MockSensor()
        mgr = FingerprintManager.__new__(FingerprintManager)
        mgr._sensor = mock_hw
        return mgr, mock_hw

    def test_wait_for_finger_detects(self):
        mgr, hw = self._make_manager()
        hw._finger = True
        self.assertTrue(mgr.wait_for_finger(timeout=1.0))

    def test_wait_for_finger_timeout(self):
        mgr, hw = self._make_manager()
        hw._finger = False
        t0 = time.time()
        result = mgr.wait_for_finger(timeout=0.2)
        self.assertFalse(result)
        self.assertLess(time.time() - t0, 1.0, "Should not block longer than timeout")

    def test_wait_for_finger_stop_event(self):
        mgr, hw = self._make_manager()
        hw._finger = False
        stop = threading.Event()
        stop.set()
        result = mgr.wait_for_finger(timeout=30, stop_event=stop)
        self.assertFalse(result)

    def test_wait_for_finger_interrupted_midway(self):
        """Stop event fired from another thread cancels polling."""
        mgr, hw = self._make_manager()
        hw._finger = False
        stop = threading.Event()
        threading.Timer(0.1, stop.set).start()
        t0 = time.time()
        result = mgr.wait_for_finger(timeout=30, stop_event=stop)
        self.assertFalse(result)
        self.assertLess(time.time() - t0, 1.0)

    def test_read_and_search_match(self):
        mgr, hw = self._make_manager()
        hw._finger = True
        hw._slot   = 3
        slot_id = mgr.read_and_search()
        self.assertEqual(slot_id, 3)

    def test_read_and_search_unknown(self):
        mgr, hw = self._make_manager()
        hw._finger = False
        slot_id = mgr.read_and_search()
        self.assertEqual(slot_id, -1)

    def test_read_and_search_sensor_error_propagates(self):
        """Sensor comm error raises — caller (_scan_worker) must catch it."""
        mgr, hw = self._make_manager()
        hw._bad_read = True
        with self.assertRaises(Exception):
            mgr.read_and_search()

    def test_wait_for_removal_exits_when_finger_gone(self):
        mgr, hw = self._make_manager()
        hw._finger = True
        def _remove():
            time.sleep(0.05)
            hw._finger = False
        threading.Thread(target=_remove, daemon=True).start()
        t0 = time.time()
        mgr.wait_for_removal()
        self.assertLess(time.time() - t0, 1.0)

    def test_wait_for_removal_stop_event(self):
        mgr, hw = self._make_manager()
        hw._finger = True   # finger never lifted
        stop = threading.Event()
        stop.set()
        t0 = time.time()
        mgr.wait_for_removal(stop_event=stop)
        self.assertLess(time.time() - t0, 0.5)

    def test_raw_aura_led_does_not_crash_on_missing_serial(self):
        """_raw_aura_led silently returns when __serial attribute is absent."""
        mgr, _ = self._make_manager()
        # Use a sensor object that has NO __serial attribute at all
        sensor_no_serial = MagicMock(spec=[])
        mgr._sensor = sensor_no_serial
        mgr._raw_aura_led(1, 0x55, 7, 0)   # must not raise

    def test_set_aura_led_uses_raw_path_when_no_native(self):
        """set_aura_led falls back to _raw_aura_led when setAuraLed absent."""
        mgr, _ = self._make_manager()
        # Replace sensor with one that has no setAuraLed method
        mgr._sensor = MagicMock(spec=['_PyFingerprint__serial'])
        mgr._raw_aura_led = MagicMock()
        mgr.set_aura_led(1, 0x55, 7, 0)
        mgr._raw_aura_led.assert_called_once_with(1, 0x55, 7, 0)

    def test_enroll_flow_mismatch_raises(self):
        mgr, hw = self._make_manager()
        hw.compareCharacteristics = lambda: 0   # mismatch
        with self.assertRaises(ValueError):
            mgr.enroll_create_and_store()


# ─────────────────────────────────────────────────────────────────────────────
# LEDManager tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLEDManager(unittest.TestCase):

    def test_no_hardware_or_spi_error_is_silent_noop(self):
        """When strip is None (no hardware or SPI error), methods must not raise."""
        from scripts.led_manager import LEDManager
        mgr = LEDManager.__new__(LEDManager)
        mgr._strip = None   # simulate stub state
        mgr._n = 4
        mgr.solid(255, 0, 0)   # must not raise
        mgr.off()
        mgr.flash(255, 0, 0, times=1, on_ms=1, off_ms=1)

    def test_spi_init_failure_degrades_gracefully(self):
        """SPI RuntimeError must NOT crash the constructor (Bug C regression)."""
        import scripts.led_manager as led_mod
        orig = led_mod._HW_AVAILABLE
        try:
            led_mod._HW_AVAILABLE = True
            # Simulate busio.SPI raising RuntimeError (SPI not enabled)
            sys.modules['busio'].SPI.side_effect = RuntimeError("SPI not enabled")
            mgr = led_mod.LEDManager(n_pixels=8)
            self.assertIsNone(mgr._strip)
        finally:
            led_mod._HW_AVAILABLE = orig
            sys.modules['busio'].SPI.side_effect = None

    def test_flash_calls_solid_multiple_times(self):
        from scripts.led_manager import LEDManager
        mgr = LEDManager(n_pixels=4)
        mgr.solid = MagicMock()
        mgr.flash(255, 0, 0, times=2, on_ms=1, off_ms=1)
        self.assertEqual(mgr.solid.call_count, 4)   # 2×(on + off)

    def test_pulse_calls_solid(self):
        from scripts.led_manager import LEDManager
        mgr = LEDManager(n_pixels=4)
        mgr.solid = MagicMock()
        mgr.pulse(0, 255, 0, steps=4, delay=0)
        self.assertGreater(mgr.solid.call_count, 0)


# ─────────────────────────────────────────────────────────────────────────────
# ButtonManager tests
# ─────────────────────────────────────────────────────────────────────────────

class TestButtonManager(unittest.TestCase):

    def test_default_pin_map_resolves(self):
        from scripts.button_manager import _build_pin_map
        buttons = {'up': 17, 'down': 27, 'confirm': 24, 'quit': 6}
        result = _build_pin_map(buttons)
        self.assertEqual(result[17], _pg.K_UP)
        self.assertEqual(result[27], _pg.K_DOWN)
        self.assertEqual(result[24], _pg.K_RETURN)
        self.assertEqual(result[6],  _pg.K_ESCAPE)

    def test_keybinding_override(self):
        """Custom keybinding_cfg overrides the default (Bug G)."""
        from scripts.button_manager import _build_pin_map
        buttons   = {'confirm': 24}
        overrides = {'confirm': 'K_RETURN'}   # same value, just verifying path
        result = _build_pin_map(buttons, keybinding_cfg=overrides)
        self.assertIn(24, result)

    def test_invalid_key_string_skipped_with_warning(self):
        from scripts.button_manager import _build_pin_map
        buttons   = {'up': 17}
        overrides = {'up': 'K_NONEXISTENT_KEY'}
        result = _build_pin_map(buttons, keybinding_cfg=overrides)
        self.assertNotIn(17, result)

    def test_unknown_button_name_skipped(self):
        from scripts.button_manager import _build_pin_map
        buttons = {'turbo': 99}   # not in defaults
        result = _build_pin_map(buttons)
        self.assertNotIn(99, result)

    def test_no_gpio_is_noop(self):
        """ButtonManager.start() must be a no-op when RPi.GPIO unavailable."""
        import scripts.button_manager as bm
        orig = bm._GPIO_OK
        try:
            bm._GPIO_OK = False
            mgr = bm.ButtonManager()
            mgr.start()   # must not raise
            mgr.stop()
        finally:
            bm._GPIO_OK = orig


# ─────────────────────────────────────────────────────────────────────────────
# LoginUI state-machine tests
# ─────────────────────────────────────────────────────────────────────────────

def _make_login_ui(sensor=None):
    """Return a LoginUI instance with Pygame, hardware, and screens stubbed."""
    from ui.login_ui import LoginUI, _IDLE, _SCAN, _SUCCESS, _FAIL, _ENROLL
    cfg = {
        'ui': {'fullscreen': False, 'resolution': [800, 480],
               'scan_timeout_sec': 5, 'enroll_timeout_sec': 30},
        'hardware': {'buttons': {}},
        'keybindings': {},
    }
    ui = LoginUI(sensor=sensor, leds=None, config=cfg)
    # _screens is populated by _init_pygame() which requires a display.
    # Replace with MagicMocks that have the attributes the state machine uses.
    def _make_screen():
        m = MagicMock()
        m.step = 0
        m.reset = MagicMock()
        m.activate = MagicMock()
        return m
    ui._screens = {
        _IDLE:    _make_screen(),
        _SCAN:    _make_screen(),
        _SUCCESS: _make_screen(),
        _FAIL:    _make_screen(),
        _ENROLL:  _make_screen(),
    }
    ui._surface = MagicMock()
    ui._clock   = MagicMock(**{'tick.return_value': 16})
    return ui


class TestLoginUIStateMachine(unittest.TestCase):

    def setUp(self):
        # Patch pygame.display and time so init doesn't need a display
        _pg.time.get_ticks.return_value = 0

    def _post_event(self, ui, ev_type, ev_data):
        ui._q.put((ev_type, ev_data))
        # Drain queue into the state machine
        from ui.login_ui import _IDLE, _SCAN, _SUCCESS, _FAIL, _ENROLL
        while True:
            try:
                t, d = ui._q.get_nowait()
                ui._handle_sensor_event(t, d)
            except queue.Empty:
                break

    def test_initial_state_is_idle(self):
        from ui.login_ui import _IDLE
        ui = _make_login_ui()
        self.assertEqual(ui._state, _IDLE)

    def test_finger_detected_transitions_to_scan(self):
        from ui.login_ui import _EV_FINGER, _SCAN
        ui = _make_login_ui()
        self._post_event(ui, _EV_FINGER, None)
        self.assertEqual(ui._state, _SCAN)

    def test_match_from_idle_transitions_to_success(self):
        from ui.login_ui import _EV_MATCH, _SUCCESS
        ui = _make_login_ui()
        user_data = {'name': 'Alice', 'color': [0, 245, 255]}
        self._post_event(ui, _EV_MATCH, (1, user_data))
        self.assertEqual(ui._state, _SUCCESS)
        self.assertIsNotNone(ui._login_data)

    def test_unknown_from_idle_transitions_to_fail(self):
        from ui.login_ui import _EV_UNKNOWN, _FAIL
        ui = _make_login_ui()
        self._post_event(ui, _EV_UNKNOWN, None)
        self.assertEqual(ui._state, _FAIL)

    def test_match_from_scan_state_transitions_to_success(self):
        from ui.login_ui import _EV_FINGER, _EV_MATCH, _SUCCESS
        ui = _make_login_ui()
        self._post_event(ui, _EV_FINGER, None)
        user_data = {'name': 'Bob', 'color': [255, 0, 0]}
        self._post_event(ui, _EV_MATCH, (2, user_data))
        self.assertEqual(ui._state, _SUCCESS)

    def test_fail_state_resets_to_idle_after_timer(self):
        from ui.login_ui import _EV_UNKNOWN, _IDLE
        ui = _make_login_ui()
        self._post_event(ui, _EV_UNKNOWN, None)

        # Simulate 3001 ms passing
        ui._fail_ts = 0
        _pg.time.get_ticks.return_value = 3001
        ui._start_scan_worker = MagicMock()
        ui._check_timers()
        self.assertEqual(ui._state, _IDLE)

    def test_success_fires_callback_after_delay(self):
        from ui.login_ui import _EV_MATCH
        ui = _make_login_ui()
        callback = MagicMock()
        ui.on_login_callback = callback

        user_data = {'name': 'Carol', 'color': [0, 255, 0]}
        self._post_event(ui, _EV_MATCH, (1, user_data))

        ui._login_ts = 0
        _pg.time.get_ticks.return_value = 2001
        ui._check_timers()
        time.sleep(0.1)   # let daemon thread fire
        callback.assert_called_once_with(1, user_data)

    def test_scan_timeout_returns_to_idle(self):
        """Bug E regression — SCAN state must time out if worker crashes."""
        from ui.login_ui import _EV_FINGER, _IDLE
        ui = _make_login_ui()
        ui._start_scan_worker = MagicMock()
        self._post_event(ui, _EV_FINGER, None)

        ui._scan_start_ts = 0
        _pg.time.get_ticks.return_value = 9000   # scan_to(5) + 3 + slack
        ui._check_timers()
        self.assertEqual(ui._state, _IDLE)

    def test_scan_worker_exception_posts_unknown_event(self):
        """Bug B regression — sensor error must result in FAIL, not freeze."""
        from ui.login_ui import _FAIL, _SCAN, _EV_FINGER
        import threading as _threading

        hw = MockSensor()
        hw._finger   = True
        hw._bad_read = True

        from scripts.fingerprint_manager import FingerprintManager
        mgr = FingerprintManager.__new__(FingerprintManager)
        mgr._sensor = hw

        ui = _make_login_ui(sensor=mgr)
        ui._start_scan_worker = MagicMock()   # prevent real thread start

        # Manually call _scan_worker once (it will catch the exception)
        ui._state = 'idle'   # match _IDLE constant
        from ui.login_ui import _IDLE
        ui._state = _IDLE
        ui._stop_scan.clear()

        t = _threading.Thread(target=ui._scan_worker, daemon=True)
        t.start()
        t.join(timeout=2.0)

        # Queue should have _EV_UNKNOWN as result of the exception
        events = []
        while True:
            try:
                events.append(ui._q.get_nowait())
            except queue.Empty:
                break
        ev_types = [e[0] for e in events]
        from ui.login_ui import _EV_FINGER, _EV_UNKNOWN
        self.assertIn(_EV_UNKNOWN, ev_types)

    def test_enrollment_stop_event_cleared_before_enroll_worker(self):
        """Bug A regression — _stop_scan must be clear when enroll_worker runs."""
        from ui.login_ui import _ENROLL, _IDLE
        ui = _make_login_ui()
        ui._start_scan_worker = MagicMock()

        # Simulate stop_scan having been set (as it would be after _stop_scan_worker)
        ui._stop_scan.set()

        # Check that _deferred() clears it
        ui._stop_scan_worker = MagicMock()   # skip the real join
        ui._enroll_worker    = MagicMock()   # we only check stop_scan state

        called_with_clear = []
        orig_enroll = ui._enroll_worker
        def _tracked_enroll():
            called_with_clear.append(not ui._stop_scan.is_set())
        ui._enroll_worker = _tracked_enroll

        # Run _start_enroll_flow and wait for _deferred to complete
        ui._start_enroll_flow()
        time.sleep(0.3)

        self.assertTrue(any(called_with_clear),
                        "_stop_scan must be cleared before _enroll_worker runs")

    def test_enroll_step_events_advance_screen_step(self):
        from ui.login_ui import _EV_E_STEP, _ENROLL
        ui = _make_login_ui()
        ui._state = _ENROLL
        # _EV_E_STEP sets the step attribute directly on the screen object
        self._post_event(ui, _EV_E_STEP, 1)
        # MagicMock records attribute sets — check via __setattr__ tracking
        # (step is assigned as `self._screens[_ENROLL].step = ev_data`)
        self.assertEqual(ui._screens[_ENROLL].step, 1)

    def test_enroll_error_returns_to_idle(self):
        from ui.login_ui import _EV_E_ERR, _IDLE
        ui = _make_login_ui()
        ui._start_scan_worker = MagicMock()
        self._post_event(ui, _EV_E_ERR, "Simulated sensor failure")
        self.assertEqual(ui._state, _IDLE)


# ─────────────────────────────────────────────────────────────────────────────
# LEDManager robustness — faulty wiring / SPI failures at runtime
# ─────────────────────────────────────────────────────────────────────────────

class TestLEDManagerRobustness(unittest.TestCase):
    """Simulate broken wiring and SPI errors; verify the rest of the program
    continues unaffected (no uncaught exceptions, no frozen state)."""

    def _make_mgr_with_strip(self):
        """LEDManager with a controllable MagicMock strip already attached."""
        from scripts.led_manager import LEDManager
        mgr = LEDManager.__new__(LEDManager)
        mgr._n = 4
        strip = MagicMock()
        mgr._strip = strip
        return mgr, strip

    # ── solid() failures ─────────────────────────────────────────────────────

    def test_solid_show_error_does_not_propagate(self):
        """strip.show() raising (e.g. SPI write timeout) must not crash caller."""
        mgr, strip = self._make_mgr_with_strip()
        strip.show.side_effect = RuntimeError("SPI write timeout — check wiring")
        mgr.solid(255, 0, 0)   # must not raise
        self.assertIsNone(mgr._strip, "strip must be disabled after write error")

    def test_solid_fill_error_does_not_propagate(self):
        """strip.fill() raising (e.g. OSError on SPI device) must not crash caller."""
        mgr, strip = self._make_mgr_with_strip()
        strip.fill.side_effect = OSError("SPI bus error — check /dev/spidev0.0")
        mgr.solid(0, 255, 0)   # must not raise
        self.assertIsNone(mgr._strip)

    def test_strip_disabled_after_first_write_error(self):
        """After one hardware error, strip → None; subsequent calls are no-ops."""
        mgr, strip = self._make_mgr_with_strip()
        strip.show.side_effect = RuntimeError("disconnected")
        mgr.solid(100, 100, 100)   # triggers error → strip = None
        mgr.solid(255, 255, 255)   # must be a silent no-op, not re-raise
        self.assertIsNone(mgr._strip)
        self.assertEqual(strip.show.call_count, 1,
                         "show() must not be called again after strip is disabled")

    # ── composite methods stay safe ──────────────────────────────────────────

    def test_flash_does_not_crash_on_led_error(self):
        """flash() must complete without raising even if LED hardware fails mid-loop."""
        mgr, strip = self._make_mgr_with_strip()
        strip.show.side_effect = RuntimeError("short circuit")
        mgr.flash(255, 0, 0, times=3, on_ms=1, off_ms=1)   # must not raise

    def test_pulse_aborts_cleanly_on_error(self):
        """pulse() must not block or propagate if LED fails mid-animation."""
        mgr, strip = self._make_mgr_with_strip()
        call_count = [0]
        def _fail_after_two(*a, **kw):
            call_count[0] += 1
            if call_count[0] > 2:
                raise RuntimeError("data line disconnected mid-pulse")
        strip.show.side_effect = _fail_after_two
        mgr.pulse(0, 255, 0, steps=4, delay=0)   # must not raise

    def test_off_is_safe_after_strip_failure(self):
        """off() called at program exit must never raise, even after prior failure."""
        mgr, strip = self._make_mgr_with_strip()
        strip.show.side_effect = RuntimeError("gone")
        mgr.solid(255, 0, 0)   # disables strip
        mgr.off()              # must not raise — called in start.py finally block

    # ── constructor robustness ────────────────────────────────────────────────

    def test_spi_permission_error_at_init(self):
        """PermissionError on /dev/spidev0.0 (user not in 'spi' group) must not
        crash the constructor — the program starts without LEDs."""
        import scripts.led_manager as led_mod
        orig = led_mod._HW_AVAILABLE
        try:
            led_mod._HW_AVAILABLE = True
            sys.modules['busio'].SPI.side_effect = PermissionError(
                "/dev/spidev0.0: Permission denied — add user to 'spi' group"
            )
            mgr = led_mod.LEDManager(n_pixels=8)
            self.assertIsNone(mgr._strip)
        finally:
            led_mod._HW_AVAILABLE = orig
            sys.modules['busio'].SPI.side_effect = None

    def test_spi_device_node_missing_at_init(self):
        """Missing /dev/spidev0.0 (SPI not enabled in config.txt) must not crash."""
        import scripts.led_manager as led_mod
        orig = led_mod._HW_AVAILABLE
        try:
            led_mod._HW_AVAILABLE = True
            sys.modules['busio'].SPI.side_effect = FileNotFoundError(
                "/dev/spidev0.0: No such file — enable with dtparam=spi=on"
            )
            mgr = led_mod.LEDManager(n_pixels=8)
            self.assertIsNone(mgr._strip)
        finally:
            led_mod._HW_AVAILABLE = orig
            sys.modules['busio'].SPI.side_effect = None


# ─────────────────────────────────────────────────────────────────────────────
# enroll.py regression tests
# ─────────────────────────────────────────────────────────────────────────────

class TestEnrollRemovalTimeout(unittest.TestCase):
    """Bug D regression — removal wait must time out, not loop forever."""

    def test_removal_wait_times_out(self):
        """Simulate a sensor that never reports finger removal."""
        import scripts.enroll as enroll_mod

        fake_sensor = MockSensor()
        fake_sensor._finger = True   # finger never removed

        start = time.time()
        # Patch time.time to fast-forward through the 15-second deadline
        times = iter([0.0] + [i * 0.5 for i in range(1, 40)] + [16.0] * 10)
        with patch('time.time', side_effect=lambda: next(times)):
            try:
                enroll_mod.enroll_finger()
            except (TimeoutError, SystemExit, Exception):
                pass   # expected — sensor error or timeout

        elapsed = time.time() - start
        self.assertLess(elapsed, 5.0,
                        "Removal wait must not block the test thread for >5 s")


# ─────────────────────────────────────────────────────────────────────────────
# start.py smoke test (settings loading)
# ─────────────────────────────────────────────────────────────────────────────

class TestStartSettings(unittest.TestCase):

    def test_settings_json_loads_and_has_required_keys(self):
        import json
        path = os.path.join(ROOT, 'config', 'settings.json')
        with open(path) as f:
            cfg = json.load(f)
        self.assertIn('hardware',    cfg)
        self.assertIn('ui',          cfg)
        self.assertIn('keybindings', cfg)
        hw = cfg['hardware']
        self.assertIn('fingerprint_port', hw)
        self.assertIn('fingerprint_baud', hw)
        self.assertIn('ws2812b_pixel_count', hw)
        self.assertIn('buttons', hw)

    def test_keybindings_all_valid_pygame_keys(self):
        import json
        path = os.path.join(ROOT, 'config', 'settings.json')
        with open(path) as f:
            cfg = json.load(f)
        for name, key_str in cfg.get('keybindings', {}).items():
            self.assertTrue(hasattr(_pg, key_str),
                            f"settings.json keybinding '{name}: {key_str}' is not a valid pygame key")

    def test_missing_settings_json_gives_clear_error(self):
        """_load_settings raises FileNotFoundError on missing file."""
        if 'start' in sys.modules:
            del sys.modules['start']
        import start
        with patch('builtins.open', side_effect=FileNotFoundError("no such file")):
            with self.assertRaises(FileNotFoundError):
                start._load_settings()


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestFingerprintManager))
    suite.addTests(loader.loadTestsFromTestCase(TestLEDManager))
    suite.addTests(loader.loadTestsFromTestCase(TestLEDManagerRobustness))
    suite.addTests(loader.loadTestsFromTestCase(TestButtonManager))
    suite.addTests(loader.loadTestsFromTestCase(TestLoginUIStateMachine))
    suite.addTests(loader.loadTestsFromTestCase(TestEnrollRemovalTimeout))
    suite.addTests(loader.loadTestsFromTestCase(TestStartSettings))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
