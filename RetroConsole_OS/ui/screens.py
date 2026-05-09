"""Screen state classes for RetroConsole login UI.

All layout values are derived from self.w / self.h so every screen scales
correctly from 800×480 up to 1920×1080 without any manual changes.

Button navigation (8 buttons):
  UP / DOWN   — cycle character in name-entry picker
  LEFT / RIGHT — navigate color picker
  CONFIRM (K_RETURN)    — accept / advance
  BACK    (K_BACKSPACE) — delete character / go back
  NEW_USER (K_n)        — start enrollment from IDLE / FAIL screens
  QUIT    (K_ESCAPE)    — exit UI
"""
import math
import os
import pygame

try:
    from ui.animations import (StarField, FingerprintIcon, ScanLine,
                                ProgressBar, CRTOverlay, GlowBurst,
                                draw_glow_circle, CYAN, BG)
except ImportError:
    from animations import (StarField, FingerprintIcon, ScanLine,
                             ProgressBar, CRTOverlay, GlowBurst,
                             draw_glow_circle, CYAN, BG)

WHITE = (255, 255, 255)
GRAY  = (160, 175, 200)
RED   = (255,  55,  55)
GREEN = (0,   215,  95)
DARK  = (16,   16,  30)

# Character set for button-driven name picker
# '✓' at position 0 means "confirm / finish entry"
CHAR_SET = (
    ['✓', ' ']
    + [chr(65 + i) for i in range(26)]   # A-Z
    + [str(i) for i in range(10)]         # 0-9
    + ['-', '_']
)

PRESET_COLORS = [
    (0,   245, 255),   # cyan (default)
    (0,   102, 255),   # blue
    (255,   0, 110),   # magenta
    (0,   215,  95),   # green
    (255, 200,   0),   # yellow
    (255, 100,   0),   # orange
    (180,   0, 255),   # purple
    (255, 255, 255),   # white
]


# ── Font loader ───────────────────────────────────────────────────────────────

def _load_font(size, bold=False):
    """Try ui/assets/fonts/, fall back to SysFont → default."""
    fonts_dir = os.path.join(os.path.dirname(__file__), 'assets', 'fonts')
    candidates = (
        ['Orbitron-Bold.ttf', 'Orbitron-Regular.ttf'] if bold
        else ['Orbitron-Regular.ttf', 'ShareTechMono-Regular.ttf']
    )
    for fname in candidates:
        path = os.path.join(fonts_dir, fname)
        if os.path.exists(path):
            try:
                return pygame.font.Font(path, size)
            except Exception:
                pass
    for family in ('consolas', 'courier new', 'monospace'):
        try:
            return pygame.font.SysFont(family, size, bold=bold)
        except Exception:
            pass
    return pygame.font.Font(None, size)


# ── Base screen ───────────────────────────────────────────────────────────────

class BaseScreen:
    """
    Common rendering for all screens:
      • dark background  • scrolling star field  • title bar  • CRT overlay

    Scaling helpers
    ---------------
    _hs(px)  — scale a vertical pixel value relative to 720 p reference
    _ws(px)  — scale a horizontal pixel value relative to 1280 p reference
    _fs(pt)  — scale a font size relative to 720 p reference
    """

    def __init__(self, width, height):
        self.w, self.h   = width, height
        self.cx, self.cy = width // 2, height // 2

        self._stars = StarField(width, height, count=max(40, width * height // 5000))
        self._crt   = CRTOverlay(width, height)

        self._font_title = _load_font(self._fs(30), bold=True)
        self._font_body  = _load_font(self._fs(19))
        self._font_small = _load_font(self._fs(14))

    # ── Scaling helpers ───────────────────────────────────────────────────────

    def _hs(self, px):
        """Scale px relative to 720 p height reference."""
        return max(1, int(px * self.h / 720))

    def _ws(self, px):
        """Scale px relative to 1280 p width reference."""
        return max(1, int(px * self.w / 1280))

    def _fs(self, pt):
        """Scale font size (uses height as reference)."""
        return max(10, int(pt * self.h / 720))

    # ── Common drawing ────────────────────────────────────────────────────────

    def _draw_base(self, surface):
        surface.fill(BG)
        self._stars.draw(surface)

    def _draw_title(self, surface):
        t = self._font_title.render("RETRO CONSOLE OS", True, CYAN)
        surface.blit(t, t.get_rect(centerx=self.cx, top=self._hs(20)))
        line_y = self._hs(56)
        pygame.draw.line(surface, (0, 65, 85),
                         (self.cx - self._ws(190), line_y),
                         (self.cx + self._ws(190), line_y), 1)

    def _draw_hint(self, surface, text, color=(60, 95, 120)):
        t = self._font_small.render(text, True, color)
        surface.blit(t, t.get_rect(centerx=self.cx,
                                    bottom=self.h - self._hs(12)))

    # ── Subclass interface ────────────────────────────────────────────────────

    def update(self, dt):
        self._stars.update(dt)

    def draw(self, surface):
        self._draw_base(surface)
        self._draw_title(surface)
        self._crt.draw(surface)

    def on_event(self, event):
        pass

    def reset(self):
        pass


# ── Idle screen ───────────────────────────────────────────────────────────────

class IdleScreen(BaseScreen):
    """Waiting for fingerprint. Fingerprint icon pulses in cyan."""

    def __init__(self, width, height):
        super().__init__(width, height)
        fp_r         = min(60, max(32, self._hs(68)))
        self._fp     = FingerprintIcon((self.cx, self.cy + self._hs(10)),
                                        base_radius=fp_r)
        self._t      = 0.0

    def update(self, dt):
        super().update(dt)
        self._fp.update(dt, CYAN)
        self._t += dt

    def draw(self, surface):
        self._draw_base(surface)
        self._draw_title(surface)
        self._fp.draw(surface)

        pulse = 0.5 + 0.5 * math.sin(self._t * 0.0018)
        c     = (0, int(170 * pulse), int(210 * pulse + 45))
        label = self._font_body.render("PLACE FINGER TO AUTHENTICATE", True, c)
        surface.blit(label, label.get_rect(centerx=self.cx,
                                            top=self.cy + self._hs(95)))

        hint = self._font_small.render("[NEW USER]  Register new user",
                                       True, (65, 95, 115))
        surface.blit(hint, hint.get_rect(centerx=self.cx,
                                          bottom=self.h - self._hs(42)))

        self._draw_hint(surface, "RetroConsole OS  v2.0")
        self._crt.draw(surface)


# ── Scan screen ───────────────────────────────────────────────────────────────

class ScanScreen(BaseScreen):
    """Shows scanning animation and a timeout progress bar."""

    def __init__(self, width, height, timeout_sec=5):
        super().__init__(width, height)
        fp_r         = min(60, max(32, self._hs(68)))
        fp_y         = self.cy + self._hs(8)
        scan_half    = fp_r + self._hs(10)
        bar_w        = self._ws(280)
        bar_h        = max(5, self._hs(8))

        self._fp       = FingerprintIcon((self.cx, fp_y), base_radius=fp_r)
        self._scanline = ScanLine(self.cx,
                                   fp_y - scan_half, fp_y + scan_half,
                                   width=fp_r * 2 + self._ws(20))
        self._bar      = ProgressBar(
            (self.cx - bar_w // 2, fp_y + scan_half + self._hs(14),
             bar_w, bar_h), CYAN
        )
        self._timeout_ms = timeout_sec * 1000
        self._elapsed    = 0.0

    def reset(self):
        self._elapsed = 0.0
        self._scanline.reset()
        self._bar.progress = 1.0

    def update(self, dt):
        super().update(dt)
        self._fp.update(dt, CYAN)
        self._scanline.update(dt)
        self._elapsed += dt
        self._bar.progress = max(0.0, 1.0 - self._elapsed / self._timeout_ms)

    def draw(self, surface):
        self._draw_base(surface)
        self._draw_title(surface)
        self._fp.draw(surface)
        self._scanline.draw(surface)
        self._bar.draw(surface)

        label = self._font_body.render("SCANNING...", True, CYAN)
        bar_bottom = self._bar.rect.bottom
        surface.blit(label, label.get_rect(centerx=self.cx,
                                            top=bar_bottom + self._hs(10)))
        self._crt.draw(surface)


# ── Success screen ────────────────────────────────────────────────────────────

class SuccessScreen(BaseScreen):

    def __init__(self, width, height):
        super().__init__(width, height)
        self._font_big = _load_font(self._fs(40), bold=True)
        burst_r        = min(self.cx, self.cy) + self._hs(60)
        self._burst    = None
        self._burst_r  = burst_r
        self._name     = ""
        self._color    = CYAN

    def activate(self, name, color):
        self._name  = name.upper()
        self._color = tuple(color) if isinstance(color, list) else color
        self._burst = GlowBurst((self.cx, self.cy), self._color,
                                 max_radius=self._burst_r)

    def reset(self):
        self._burst = None

    def update(self, dt):
        super().update(dt)
        if self._burst:
            self._burst.update(dt)

    def draw(self, surface):
        self._draw_base(surface)
        if self._burst:
            self._burst.draw(surface)
        self._draw_title(surface)

        welcome = self._font_big.render(f"WELCOME, {self._name}!", True, self._color)
        surface.blit(welcome, welcome.get_rect(centerx=self.cx,
                                                centery=self.cy - self._hs(12)))

        sub = self._font_body.render("Starting EmulationStation...", True, GRAY)
        surface.blit(sub, sub.get_rect(centerx=self.cx,
                                        top=self.cy + self._hs(38)))
        self._crt.draw(surface)


# ── Fail screen ───────────────────────────────────────────────────────────────

class FailScreen(BaseScreen):

    def __init__(self, width, height):
        super().__init__(width, height)
        self._font_err = _load_font(self._fs(26), bold=True)
        self._t        = 0.0

    def reset(self):
        self._t = 0.0

    def update(self, dt):
        super().update(dt)
        self._t += dt

    def draw(self, surface):
        self._draw_base(surface)
        self._draw_title(surface)

        flash = abs(math.sin(self._t * 0.005))
        warn  = self._font_err.render("UNKNOWN FINGERPRINT",
                                       True, (int(255 * flash), 0, 0))
        surface.blit(warn, warn.get_rect(centerx=self.cx,
                                          centery=self.cy - self._hs(18)))

        msg = self._font_body.render(
            "Try again or register a new user.", True, GRAY
        )
        surface.blit(msg, msg.get_rect(centerx=self.cx,
                                        top=self.cy + self._hs(20)))

        hint = self._font_small.render("[NEW USER]  Register new user",
                                       True, (65, 95, 115))
        surface.blit(hint, hint.get_rect(centerx=self.cx,
                                          bottom=self.h - self._hs(42)))
        self._crt.draw(surface)


# ── Enroll screen ─────────────────────────────────────────────────────────────

class EnrollScreen(BaseScreen):
    """
    5-step enrollment wizard.

    Steps
    -----
    0  Place finger        (sensor thread)
    1  Remove finger       (sensor thread)
    2  Place finger again  (sensor thread)
    3  Enter name          → button-driven character picker (UP/DN cycle, CONFIRM add, BACK delete)
    4  Choose color        → LEFT/RIGHT cycle, CONFIRM finish
    5  Done                → signals LoginUI to save & return to IDLE

    Character picker
    ----------------
    The picker shows three characters in a vertical wheel:
      • previous  (dimmer, smaller — above)
      • CURRENT   (bright, large — centre)
      • next      (dimmer, smaller — below)
    '✓' (position 0) means "confirm name and advance to color step".
    """

    _SENSOR_LABELS = [
        "Place your finger on the sensor",
        "Remove your finger",
        "Place your finger again",
    ]

    def __init__(self, width, height):
        super().__init__(width, height)
        self._font_step  = _load_font(self._fs(22), bold=True)
        self._font_input = _load_font(self._fs(20))
        self._font_pick  = _load_font(self._fs(34), bold=True)
        self._font_pick_s= _load_font(self._fs(20))
        fp_r             = min(52, max(28, self._hs(58)))
        self._fp         = FingerprintIcon((self.cx, self.cy + self._hs(5)),
                                            base_radius=fp_r)
        self.step        = 0
        self.name_input  = ""
        self.color_idx   = 0
        self._char_idx   = 0   # index into CHAR_SET

    def reset(self):
        self.step       = 0
        self.name_input = ""
        self.color_idx  = 0
        self._char_idx  = 0
        fp_r = min(52, max(28, self._hs(58)))
        self._fp = FingerprintIcon((self.cx, self.cy + self._hs(5)),
                                    base_radius=fp_r)

    def get_name(self):
        return self.name_input.strip() or "Player"

    def get_color(self):
        return PRESET_COLORS[self.color_idx]

    def update(self, dt):
        super().update(dt)
        col = PRESET_COLORS[self.color_idx] if self.step >= 4 else CYAN
        self._fp.update(dt, col)

    def on_event(self, event):
        if event.type != pygame.KEYDOWN:
            return
        key = event.key

        if self.step == 3:
            # ── Character picker ──────────────────────────────────────────
            if key == pygame.K_UP:
                self._char_idx = (self._char_idx + 1) % len(CHAR_SET)
            elif key == pygame.K_DOWN:
                self._char_idx = (self._char_idx - 1) % len(CHAR_SET)
            elif key == pygame.K_RETURN:
                ch = CHAR_SET[self._char_idx]
                if ch == '✓':
                    if self.name_input.strip():
                        self.step = 4
                elif len(self.name_input) < 14:
                    self.name_input += ch
            elif key == pygame.K_BACKSPACE:
                self.name_input = self.name_input[:-1]
            # Also allow keyboard typing for convenience on desktop
            elif event.unicode and event.unicode.isprintable():
                ch = event.unicode.upper()
                if ch in ''.join(CHAR_SET) and len(self.name_input) < 14:
                    self.name_input += ch

        elif self.step == 4:
            # ── Color picker ──────────────────────────────────────────────
            if key in (pygame.K_LEFT, pygame.K_DOWN):
                self.color_idx = (self.color_idx - 1) % len(PRESET_COLORS)
            elif key in (pygame.K_RIGHT, pygame.K_UP):
                self.color_idx = (self.color_idx + 1) % len(PRESET_COLORS)
            elif key == pygame.K_RETURN:
                self.step = 5   # signals completion to LoginUI

    def draw(self, surface):
        self._draw_base(surface)
        self._draw_title(surface)

        # Step indicator
        step_t = self._font_small.render(
            f"Step {min(self.step + 1, 5)} of 5", True, (75, 110, 135)
        )
        surface.blit(step_t, step_t.get_rect(centerx=self.cx,
                                               top=self._hs(62)))

        if self.step < 3:
            self._draw_sensor_step(surface)
        elif self.step == 3:
            self._draw_name_picker(surface)
        elif self.step == 4:
            self._draw_color_picker(surface)
        elif self.step >= 5:
            done = self._font_step.render("Account created!", True, GREEN)
            surface.blit(done, done.get_rect(centerx=self.cx, centery=self.cy))

        self._crt.draw(surface)

    # ── Private drawing helpers ───────────────────────────────────────────────

    def _draw_sensor_step(self, surface):
        self._fp.draw(surface)
        label = self._font_step.render(self._SENSOR_LABELS[self.step], True, CYAN)
        surface.blit(label, label.get_rect(centerx=self.cx,
                                            top=self.cy + self._hs(88)))

        nav = self._font_small.render(
            "[NEW USER] cancel", True, (60, 90, 110)
        )
        surface.blit(nav, nav.get_rect(centerx=self.cx,
                                        bottom=self.h - self._hs(14)))

    def _draw_name_picker(self, surface):
        # Name so far
        prompt = self._font_step.render("Enter your name:", True, CYAN)
        surface.blit(prompt, prompt.get_rect(centerx=self.cx,
                                              top=self._hs(72)))

        box_w = self._ws(480)
        box_h = self._hs(36)
        box   = pygame.Rect(self.cx - box_w // 2, self._hs(106),
                             box_w, box_h)
        pygame.draw.rect(surface, DARK, box, border_radius=4)
        pygame.draw.rect(surface, CYAN, box, 1, border_radius=4)

        cursor  = "|" if (pygame.time.get_ticks() % 900 < 450) else " "
        display = (self.name_input + cursor).ljust(15)
        inp     = self._font_input.render(display, True, WHITE)
        surface.blit(inp, inp.get_rect(midleft=(box.x + self._ws(10),
                                                 box.centery)))

        # Character wheel — prev / CURRENT / next
        curr_ch = CHAR_SET[self._char_idx]
        prev_ch = CHAR_SET[(self._char_idx - 1) % len(CHAR_SET)]
        next_ch = CHAR_SET[(self._char_idx + 1) % len(CHAR_SET)]

        wheel_cy = self._hs(290)
        spacing  = self._hs(52)

        # Arrows
        arr_col = (0, 180, 200)
        pygame.draw.polygon(surface, arr_col, [
            (self.cx, wheel_cy - spacing - self._hs(12)),
            (self.cx - self._ws(10), wheel_cy - spacing - self._hs(2)),
            (self.cx + self._ws(10), wheel_cy - spacing - self._hs(2)),
        ])
        pygame.draw.polygon(surface, arr_col, [
            (self.cx, wheel_cy + spacing + self._hs(12)),
            (self.cx - self._ws(10), wheel_cy + spacing + self._hs(2)),
            (self.cx + self._ws(10), wheel_cy + spacing + self._hs(2)),
        ])

        # Previous char (dimmer)
        prev_s = self._font_pick_s.render(prev_ch, True, (0, 130, 155))
        surface.blit(prev_s, prev_s.get_rect(centerx=self.cx,
                                               centery=wheel_cy - spacing))

        # Current char (bright, large)
        curr_is_confirm = (curr_ch == '✓')
        curr_col = GREEN if curr_is_confirm else CYAN
        draw_glow_circle(surface, (self.cx, wheel_cy),
                         self._hs(28), curr_col, alpha_max=55, layers=4)
        curr_s = self._font_pick.render(curr_ch, True, curr_col)
        surface.blit(curr_s, curr_s.get_rect(center=(self.cx, wheel_cy)))

        # Next char (dimmer)
        next_s = self._font_pick_s.render(next_ch, True, (0, 130, 155))
        surface.blit(next_s, next_s.get_rect(centerx=self.cx,
                                               centery=wheel_cy + spacing))

        # Instructions
        if curr_is_confirm:
            hint_txt = "[CONFIRM] finish name"
        else:
            hint_txt = "[CONFIRM] add  [BACK] delete  [UP/DN] cycle"
        hint = self._font_small.render(hint_txt, True, (65, 95, 115))
        surface.blit(hint, hint.get_rect(centerx=self.cx,
                                          bottom=self.h - self._hs(14)))

    def _draw_color_picker(self, surface):
        prompt = self._font_step.render("Choose your color:", True, CYAN)
        surface.blit(prompt, prompt.get_rect(centerx=self.cx,
                                              centery=self.cy - self._hs(80)))

        sw    = max(24, min(50, self._ws(42)))
        gap   = max(6,  self._ws(10))
        total = len(PRESET_COLORS) * (sw + gap) - gap
        ox    = self.cx - total // 2

        for i, col in enumerate(PRESET_COLORS):
            x    = ox + i * (sw + gap)
            rect = pygame.Rect(x, self.cy - sw // 2, sw, sw)
            pygame.draw.rect(surface, col, rect, border_radius=6)
            if i == self.color_idx:
                pygame.draw.rect(surface, WHITE, rect, 2, border_radius=6)
                draw_glow_circle(surface, rect.center, sw // 2 + self._hs(8),
                                 col, alpha_max=65, layers=3)

        # Selected color name
        sel_col  = PRESET_COLORS[self.color_idx]
        preview  = self._font_body.render("●", True, sel_col)
        surface.blit(preview, preview.get_rect(centerx=self.cx,
                                                 top=self.cy + self._hs(40)))

        hint = self._font_small.render(
            "[LEFT/RIGHT] or [UP/DN]  navigate    [CONFIRM] select",
            True, (65, 95, 115)
        )
        surface.blit(hint, hint.get_rect(centerx=self.cx,
                                          bottom=self.h - self._hs(14)))
