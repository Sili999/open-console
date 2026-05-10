
import os
import json
import threading
import queue
import time
import pygame

try:
    from ui.screens import (IdleScreen, ScanScreen, SuccessScreen,
                             FailScreen, EnrollScreen)
except ImportError:
    from screens import (IdleScreen, ScanScreen, SuccessScreen,
                         FailScreen, EnrollScreen)

# State identifiers
_IDLE    = 'idle'
_SCAN    = 'scan'
_SUCCESS = 'success'
_FAIL    = 'fail'
_ENROLL  = 'enroll'

# Sensor event types posted to the internal queue
_EV_FINGER  = 'finger_detected'
_EV_MATCH   = 'scan_match'     # data: (slot_id, user_data)
_EV_UNKNOWN = 'scan_unknown'
_EV_E_STEP  = 'enroll_step'   # data: int (next step number)
_EV_E_READY = 'enroll_ready'  # data: slot_id
_EV_E_ERR   = 'enroll_error'  # data: str


class LoginUI:
    """
    Pygame fullscreen login interface with 8-button navigation.

    Button → Pygame key mapping (configured in settings.json):
      up       → K_UP        (char picker: next character)
      down     → K_DOWN      (char picker: previous character)
      left     → K_LEFT      (color picker: previous color)
      right    → K_RIGHT     (color picker: next color)
      confirm  → K_RETURN    (accept / advance)
      back     → K_BACKSPACE (delete char / go back)
      new_user → K_n         (start enrollment from IDLE/FAIL)
      quit     → K_ESCAPE    (exit UI)

    Sensor threading model
    ----------------------
    _scan_worker  — background daemon; polls sensor while in IDLE state using
                    1-second bursts, checks _stop_scan between each burst so
                    it exits cleanly when the user navigates to ENROLL.
    _enroll_worker — started only after scan_worker has exited; drives the
                     3-step sensor enrollment (scan1 → removal → scan2).
    """

    def __init__(self, sensor=None, leds=None, config=None):
        self.sensor = sensor
        self.leds   = leds
        self.on_login_callback = None

        cfg    = config or {}
        ui_cfg = cfg.get('ui', {})
        hw_cfg = cfg.get('hardware', {})

        self._fullscreen = ui_cfg.get('fullscreen', False)
        res              = ui_cfg.get('resolution', [800, 480])
        self._res        = tuple(res)
        self._scan_to    = ui_cfg.get('scan_timeout_sec', 5)
        self._enroll_to  = ui_cfg.get('enroll_timeout_sec', 30)
        self._btn_cfg    = hw_cfg.get('buttons', {})
        self._keybind_cfg = cfg.get('keybindings', {})
        es_cfg = cfg.get('emulationstation', {})
        _raw_base = es_cfg.get('users_base_dir', '/home/pi/users')
        self._users_base = os.path.normpath(os.path.abspath(_raw_base))

        config_path = os.path.join(os.path.dirname(__file__),
                                   '..', 'config', 'user_map.json')
        self._user_map_path = os.path.realpath(config_path)

        self._q            = queue.Queue()
        self._state        = _IDLE
        self._screens      = {}
        self._surface      = None
        self._clock        = None
        self._stop_scan    = threading.Event()
        self._scan_thread  = None
        self._btn_mgr      = None
        self._pending_slot = 0
        self._login_data   = None
        self._login_ts     = 0
        self._fail_ts      = 0
        self._scan_start_ts = 0

    # ── Pygame + hardware setup ───────────────────────────────────────────────

    def _init_pygame(self):
        import sys as _sys
        no_desktop = (not os.environ.get('DISPLAY') and
                      not os.environ.get('WAYLAND_DISPLAY'))
        if _sys.platform.startswith('linux') and no_desktop:
            if os.path.exists('/dev/dri/card0'):
                # Pi OS Bookworm+ — KMS/DRM replaces the old fbcon framebuffer
                os.environ.setdefault('SDL_VIDEODRIVER', 'kmsdrm')
            else:
                # Legacy Pi OS — use the old framebuffer driver
                os.environ.setdefault('SDL_VIDEODRIVER', 'fbcon')
                os.environ.setdefault('SDL_FBDEV',       '/dev/fb0')
        pygame.init()
        flags = pygame.FULLSCREEN if self._fullscreen else 0
        self._surface = pygame.display.set_mode(self._res, flags)
        pygame.mouse.set_visible(False)
        pygame.display.set_caption("RetroConsole Login")
        self._clock = pygame.time.Clock()

        w, h = self._res
        self._screens = {
            _IDLE:    IdleScreen(w, h),
            _SCAN:    ScanScreen(w, h, self._scan_to),
            _SUCCESS: SuccessScreen(w, h),
            _FAIL:    FailScreen(w, h),
            _ENROLL:  EnrollScreen(w, h),
        }

    def _init_buttons(self):
        """Build ButtonManager from settings and start it (after pygame.init)."""
        try:
            from scripts.button_manager import ButtonManager, _build_pin_map
        except ImportError:
            try:
                import sys
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
                from scripts.button_manager import ButtonManager, _build_pin_map
            except ImportError:
                return   # Not available — keyboard-only fallback

        pin_map = _build_pin_map(self._btn_cfg, self._keybind_cfg) if self._btn_cfg else None
        self._btn_mgr = ButtonManager(pin_map=pin_map)
        self._btn_mgr.start()

    # ── State helpers ─────────────────────────────────────────────────────────

    def _set_state(self, new_state):
        self._state = new_state
        scr = self._screens.get(new_state)
        if scr and hasattr(scr, 'reset'):
            scr.reset()

    def _load_user_map(self):
        try:
            with open(self._user_map_path) as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_user_map(self, user_map):
        import tempfile
        dir_ = os.path.dirname(self._user_map_path)
        with tempfile.NamedTemporaryFile('w', dir=dir_, delete=False,
                                         suffix='.tmp') as tmp:
            json.dump(user_map, tmp, indent=4)
            tmp_path = tmp.name
        os.replace(tmp_path, self._user_map_path)   # atomic on all major OSes

    # ── Sensor threads ────────────────────────────────────────────────────────

    def _scan_worker(self):
        """Poll for finger in 1 s bursts while in IDLE; post events on result."""
        if not self.sensor:
            return

        while self._state == _IDLE and not self._stop_scan.is_set():
            self.sensor.set_aura_led(1, 0x55, 7, 0)   # breathing white

            detected = self.sensor.wait_for_finger(timeout=1.0,
                                                    stop_event=self._stop_scan)
            if self._stop_scan.is_set() or self._state != _IDLE:
                break
            if not detected:
                continue

            # Finger placed — signal SCAN state, then process immediately
            self._q.put((_EV_FINGER, None))

            try:
                slot_id = self.sensor.read_and_search()
            except Exception as exc:
                print(f"[scan_worker] Sensor error during read/search: {exc}")
                self._q.put((_EV_UNKNOWN, None))
                break

            if slot_id == -1:
                self.sensor.set_aura_led(2, 0x55, 1, 3)
                time.sleep(1.2)
                self.sensor.led_off()
                self._q.put((_EV_UNKNOWN, None))
            else:
                self.sensor.set_aura_led(3, 0x00, 4, 0)
                time.sleep(0.5)
                self.sensor.led_off()
                user_map = self._load_user_map()
                user_data = user_map.get(str(slot_id), {
                    'name':  f'User {slot_id}',
                    'color': [0, 245, 255],
                    'home':  f'{self._users_base}/{slot_id}',
                })
                self._q.put((_EV_MATCH, (slot_id, user_data)))
            break

    def _start_scan_worker(self):
        self._stop_scan.clear()
        t = threading.Thread(target=self._scan_worker, daemon=True)
        t.start()
        self._scan_thread = t

    def _stop_scan_worker(self):
        self._stop_scan.set()
        if self._scan_thread and self._scan_thread.is_alive():
            self._scan_thread.join(timeout=2.0)

    def _enroll_worker(self):
        """Run sensor-side enrollment (steps 0–2); post events for each stage."""
        if not self.sensor:
            # Mock mode — simulate sensor steps with delays
            for step in [1, 2]:
                time.sleep(1.5)
                if self._state != _ENROLL:
                    return
                self._q.put((_EV_E_STEP, step))
            time.sleep(1.5)
            if self._state != _ENROLL:
                return
            user_map  = self._load_user_map()
            mock_slot = max((int(k) for k in user_map), default=0) + 1
            self._q.put((_EV_E_READY, mock_slot))
            return

        stop = self._stop_scan
        try:
            # Step 0 → 1: first scan
            self.sensor.set_aura_led(1, 0x55, 2, 0)
            if not self.sensor.wait_for_finger(self._enroll_to, stop):
                raise TimeoutError("Timed out waiting for first scan.")
            if self._state != _ENROLL:
                return
            self.sensor.enroll_convert_first()
            self._q.put((_EV_E_STEP, 1))

            # Step 1 → 2: wait for removal
            self.sensor.wait_for_removal(stop)
            if self._state != _ENROLL:
                return
            self._q.put((_EV_E_STEP, 2))

            # Step 2 → ready: second scan
            self.sensor.set_aura_led(1, 0x55, 2, 0)
            if not self.sensor.wait_for_finger(self._enroll_to, stop):
                raise TimeoutError("Timed out waiting for second scan.")
            if self._state != _ENROLL:
                return
            self.sensor.enroll_convert_second()
            slot_id = self.sensor.enroll_create_and_store()

            self.sensor.set_aura_led(2, 0x55, 4, 3)
            time.sleep(1.0)
            self.sensor.led_off()

            self._q.put((_EV_E_READY, slot_id))

        except Exception as exc:
            self._q.put((_EV_E_ERR, str(exc)))

    def _start_enroll_flow(self):
        """Stop scan worker then start enroll worker (non-blocking)."""
        self._screens[_ENROLL].reset()
        self._set_state(_ENROLL)

        def _deferred():
            self._stop_scan_worker()
            self._stop_scan.clear()   # must clear after join so enroll worker can use it
            if self._state == _ENROLL:
                self._enroll_worker()

        threading.Thread(target=_deferred, daemon=True).start()

    # ── Event processing ──────────────────────────────────────────────────────

    def _process_events(self):
        """Handle Pygame + sensor queue events. Returns False to quit."""
        enroll_scr = self._screens[_ENROLL]

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                if self._state in (_IDLE, _FAIL) and event.key == pygame.K_n:
                    self._start_enroll_flow()
                elif self._state == _ENROLL:
                    enroll_scr.on_event(event)
                    if enroll_scr.step >= 5:
                        self._finish_enrollment(enroll_scr)

        while True:
            try:
                ev_type, ev_data = self._q.get_nowait()
            except queue.Empty:
                break
            self._handle_sensor_event(ev_type, ev_data)

        return True

    def _handle_sensor_event(self, ev_type, ev_data):
        if ev_type == _EV_FINGER and self._state == _IDLE:
            self._set_state(_SCAN)
            self._scan_start_ts = pygame.time.get_ticks()

        elif ev_type == _EV_MATCH and self._state in (_IDLE, _SCAN):
            slot_id, user_data = ev_data
            self._screens[_SUCCESS].activate(
                user_data.get('name', 'User'),
                user_data.get('color', [0, 245, 255]),
            )
            self._set_state(_SUCCESS)
            self._login_data = (slot_id, user_data)
            self._login_ts   = pygame.time.get_ticks()

        elif ev_type == _EV_UNKNOWN and self._state in (_IDLE, _SCAN):
            self._set_state(_FAIL)
            self._fail_ts = pygame.time.get_ticks()

        elif ev_type == _EV_E_STEP and self._state == _ENROLL:
            self._screens[_ENROLL].step = ev_data

        elif ev_type == _EV_E_READY and self._state == _ENROLL:
            self._pending_slot = ev_data
            self._screens[_ENROLL].step = 3   # advance to name picker

        elif ev_type == _EV_E_ERR:
            self._set_state(_IDLE)
            self._start_scan_worker()

    def _finish_enrollment(self, enroll_scr):
        name     = enroll_scr.get_name()
        color    = list(enroll_scr.get_color())
        slot_id  = self._pending_slot
        home_dir = f'{self._users_base}/{slot_id}'

        user_map = self._load_user_map()
        user_map[str(slot_id)] = {'name': name, 'color': color, 'home': home_dir}
        self._save_user_map(user_map)

        try:
            os.makedirs(os.path.join(home_dir, '.emulationstation'), exist_ok=True)
        except Exception:
            pass

        self._set_state(_IDLE)
        self._start_scan_worker()

    # ── Timers ────────────────────────────────────────────────────────────────

    def _check_timers(self):
        now = pygame.time.get_ticks()
        if self._state == _SCAN:
            # Safety net: if scan worker died without posting a result, bail to IDLE
            limit_ms = (self._scan_to + 3) * 1000
            if now - self._scan_start_ts >= limit_ms:
                print("[login_ui] SCAN timeout — scan worker may have crashed; returning to IDLE.")
                self._set_state(_IDLE)
                self._start_scan_worker()

        elif self._state == _SUCCESS and self._login_data:
            if now - self._login_ts >= 2000:
                slot_id, user_data = self._login_data
                self._login_data = None
                if self.on_login_callback:
                    threading.Thread(
                        target=self.on_login_callback,
                        args=(slot_id, user_data),
                        daemon=True,
                    ).start()
        elif self._state == _FAIL:
            if now - self._fail_ts >= 3000:
                self._set_state(_IDLE)
                self._start_scan_worker()

    # ── Public API ────────────────────────────────────────────────────────────

    def reset_to_idle(self):
        """Call from on_login_callback after EmulationStation exits."""
        self._set_state(_IDLE)
        self._start_scan_worker()

    def run(self):
        """Initialise Pygame, start hardware, enter main loop. Blocks until quit."""
        self._init_pygame()
        self._init_buttons()
        self._start_scan_worker()

        try:
            while True:
                dt = self._clock.tick(60)
                if not self._process_events():
                    break
                self._check_timers()

                scr = self._screens.get(self._state)
                if scr:
                    scr.update(dt)
                    scr.draw(self._surface)

                pygame.display.flip()
        finally:
            self._stop_scan.set()
            if self._btn_mgr:
                self._btn_mgr.stop()
            pygame.quit()
