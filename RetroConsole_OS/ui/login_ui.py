"""Pygame-based login UI with fingerprint state machine for RetroConsole OS."""
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

# Sensor event types posted to the queue
_EV_FINGER   = 'finger_detected'
_EV_MATCH    = 'scan_match'       # data: (slot_id, user_data)
_EV_UNKNOWN  = 'scan_unknown'
_EV_TIMEOUT  = 'scan_timeout'
_EV_E_STEP   = 'enroll_step'     # data: int (next step number)
_EV_E_READY  = 'enroll_ready'    # data: slot_id  (sensor done, enter name)
_EV_E_ERR    = 'enroll_error'    # data: str (error message)


class LoginUI:
    """
    Pygame fullscreen login interface.

    Lifecycle
    ---------
    1. Create instance (no Pygame calls yet).
    2. Set `on_login_callback` to a callable(slot_id, user_data).
    3. Call `run()` — blocks until quit (ESC or window close).
    4. After EmulationStation exits, the callback should call `reset_to_idle()`.

    Sensor threading model
    ----------------------
    A background daemon thread (`_scan_worker`) polls the sensor while in IDLE
    state using 1-second bursts, checking `_stop_scan` between each burst so
    it can exit cleanly when the user navigates to ENROLL.  The enrollment
    sensor steps run in a separate `_enroll_worker` thread which is started
    only after the scan worker has exited.
    """

    def __init__(self, sensor=None, leds=None, config=None):
        self.sensor = sensor
        self.leds   = leds
        self.on_login_callback = None

        cfg       = config or {}
        ui_cfg    = cfg.get('ui', {})
        self._fullscreen   = ui_cfg.get('fullscreen', False)
        res                = ui_cfg.get('resolution', [1280, 720])
        self._res          = tuple(res)
        self._scan_to      = ui_cfg.get('scan_timeout_sec', 5)
        self._enroll_to    = ui_cfg.get('enroll_timeout_sec', 30)

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
        self._pending_slot = 0
        self._login_data   = None
        self._login_ts     = 0
        self._fail_ts      = 0

    # ── Pygame setup ──────────────────────────────────────────────────────────

    def _init_pygame(self):
        if not os.environ.get('DISPLAY'):
            os.environ.setdefault('SDL_VIDEODRIVER', 'fbcon')
            os.environ.setdefault('SDL_FBDEV',       '/dev/fb0')
        pygame.init()
        pygame.mouse.set_visible(False)
        flags = pygame.FULLSCREEN if self._fullscreen else 0
        self._surface = pygame.display.set_mode(self._res, flags)
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

    # ── State helpers ─────────────────────────────────────────────────────────

    def _set_state(self, new_state):
        self._state = new_state
        scr = self._screens.get(new_state)
        if scr and hasattr(scr, 'reset'):
            scr.reset()

    def _load_user_map(self):
        try:
            with open(self._user_map_path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_user_map(self, user_map):
        with open(self._user_map_path, 'w') as f:
            json.dump(user_map, f, indent=4)

    # ── Sensor threads ────────────────────────────────────────────────────────

    def _scan_worker(self):
        """
        Runs in background while state == _IDLE.
        Polls for finger in 1-second bursts; posts events on detection.
        Exits when _stop_scan is set or state leaves IDLE.
        """
        if not self.sensor:
            return   # No hardware — UI stays in IDLE indefinitely

        while self._state == _IDLE and not self._stop_scan.is_set():
            self.sensor.set_aura_led(1, 0x55, 7, 0)   # breathing white

            # Short-burst poll so we check cancel flag frequently
            detected = self.sensor.wait_for_finger(timeout=1.0,
                                                    stop_event=self._stop_scan)
            if self._stop_scan.is_set() or self._state != _IDLE:
                break

            if not detected:
                continue   # Timeout — try again

            # Finger placed — post event and process immediately
            self._q.put((_EV_FINGER, None))

            slot_id = self.sensor.read_and_search()

            if slot_id == -1:
                self.sensor.set_aura_led(2, 0x55, 1, 3)   # flashing red
                time.sleep(1.2)
                self.sensor.led_off()
                self._q.put((_EV_UNKNOWN, None))
            else:
                self.sensor.set_aura_led(3, 0x00, 4, 0)   # solid green
                time.sleep(0.5)
                self.sensor.led_off()
                user_map = self._load_user_map()
                user_data = user_map.get(str(slot_id), {
                    'name':  f'User {slot_id}',
                    'color': [0, 245, 255],
                    'home':  f'/home/pi/users/{slot_id}',
                })
                self._q.put((_EV_MATCH, (slot_id, user_data)))
            break   # Worker done — LoginUI restarts it when needed

    def _start_scan_worker(self):
        self._stop_scan.clear()
        t = threading.Thread(target=self._scan_worker, daemon=True)
        t.start()
        self._scan_thread = t

    def _stop_scan_worker(self):
        """Signal the scan worker to exit and wait for it (max 2 s)."""
        self._stop_scan.set()
        if self._scan_thread and self._scan_thread.is_alive():
            self._scan_thread.join(timeout=2.0)

    def _enroll_worker(self):
        """
        Runs the sensor-side of enrollment (steps 0–2).
        Posts EV_E_STEP events to advance the EnrollScreen,
        then EV_E_READY(slot_id) when the finger is stored.
        Posts EV_E_ERR on failure.
        """
        if not self.sensor:
            # Mock mode — simulate sensor steps
            for step in [1, 2]:
                time.sleep(1.5)
                if self._state != _ENROLL:
                    return
                self._q.put((_EV_E_STEP, step))
            time.sleep(1.5)
            if self._state != _ENROLL:
                return
            user_map   = self._load_user_map()
            mock_slot  = max((int(k) for k in user_map), default=0) + 1
            self._q.put((_EV_E_READY, mock_slot))
            return

        try:
            stop = self._stop_scan   # reuse event (already set when entering enroll)

            # Step 0 → 1: first scan
            self.sensor.set_aura_led(1, 0x55, 2, 0)   # breathing blue
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

            self.sensor.set_aura_led(2, 0x55, 4, 3)   # flash green
            time.sleep(1.0)
            self.sensor.led_off()

            self._q.put((_EV_E_READY, slot_id))

        except Exception as exc:
            self._q.put((_EV_E_ERR, str(exc)))

    def _start_enroll_flow(self):
        """Transition to ENROLL: stop the scan worker, then start enroll worker."""
        self._screens[_ENROLL].reset()
        self._set_state(_ENROLL)

        def _deferred():
            self._stop_scan_worker()   # wait for scan thread to exit
            if self._state == _ENROLL:
                self._enroll_worker()

        threading.Thread(target=_deferred, daemon=True).start()

    # ── Event processing ──────────────────────────────────────────────────────

    def _process_events(self):
        """Handle Pygame and sensor events. Returns False to quit."""
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

        # Drain sensor queue
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

        elif ev_type == _EV_TIMEOUT and self._state == _SCAN:
            self._set_state(_IDLE)
            self._start_scan_worker()

        elif ev_type == _EV_E_STEP and self._state == _ENROLL:
            self._screens[_ENROLL].step = ev_data

        elif ev_type == _EV_E_READY and self._state == _ENROLL:
            self._pending_slot = ev_data
            self._screens[_ENROLL].step = 3   # move to name input

        elif ev_type == _EV_E_ERR:
            self._set_state(_IDLE)
            self._start_scan_worker()

    def _finish_enrollment(self, enroll_scr):
        name     = enroll_scr.get_name()
        color    = list(enroll_scr.get_color())
        slot_id  = self._pending_slot
        home_dir = f'/home/pi/users/{slot_id}'

        user_map = self._load_user_map()
        user_map[str(slot_id)] = {'name': name, 'color': color, 'home': home_dir}
        self._save_user_map(user_map)

        try:
            es_dir = os.path.join(home_dir, '.emulationstation')
            os.makedirs(es_dir, exist_ok=True)
        except Exception:
            pass

        self._set_state(_IDLE)
        self._start_scan_worker()

    # ── Auto-transition timers ────────────────────────────────────────────────

    def _check_timers(self):
        now = pygame.time.get_ticks()

        if self._state == _SUCCESS and self._login_data:
            if now - self._login_ts >= 2000:   # 2 s display then launch ES
                slot_id, user_data = self._login_data
                self._login_data = None
                if self.on_login_callback:
                    threading.Thread(
                        target=self.on_login_callback,
                        args=(slot_id, user_data),
                        daemon=True,
                    ).start()

        elif self._state == _FAIL:
            if now - self._fail_ts >= 3000:   # 3 s on fail screen then IDLE
                self._set_state(_IDLE)
                self._start_scan_worker()

    # ── Public API ────────────────────────────────────────────────────────────

    def reset_to_idle(self):
        """Called by on_login_callback after EmulationStation exits."""
        self._set_state(_IDLE)
        self._start_scan_worker()

    def run(self):
        """Start Pygame, enter main loop. Blocks until quit."""
        self._init_pygame()
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
            self._stop_scan.set()   # signal any running thread
            pygame.quit()
