"""Screen state classes for RetroConsole login UI."""
import math
import os
import json
import pygame

try:
    from ui.animations import (StarField, FingerprintIcon, ScanLine,
                                ProgressBar, CRTOverlay, GlowBurst,
                                draw_glow_circle, CYAN, BLUE, MAGENTA, BG)
except ImportError:
    from animations import (StarField, FingerprintIcon, ScanLine,
                             ProgressBar, CRTOverlay, GlowBurst,
                             draw_glow_circle, CYAN, BLUE, MAGENTA, BG)

WHITE = (255, 255, 255)
GRAY  = (170, 180, 200)
RED   = (255, 60,  60)
GREEN = (0,   220, 100)
DARK  = (18,  18,  32)

PRESET_COLORS = [
    (0,   245, 255),   # cyan    (default)
    (0,   102, 255),   # blue
    (255, 0,   110),   # magenta
    (0,   220, 100),   # green
    (255, 200, 0),     # yellow
    (255, 100, 0),     # orange
    (180, 0,   255),   # purple
    (255, 255, 255),   # white
]


def _load_font(name, size, bold=False):
    """Try loading from ui/assets/fonts/, fall back to SysFont."""
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


# ─────────────────────────────────────────────────────────────────────────────
class BaseScreen:
    """Common rendering: dark background, scrolling stars, title bar, CRT overlay."""

    def __init__(self, width, height):
        self.w, self.h = width, height
        self.cx, self.cy = width // 2, height // 2
        self._stars = StarField(width, height)
        self._crt   = CRTOverlay(width, height)
        self._font_title = _load_font(None, 34, bold=True)
        self._font_body  = _load_font(None, 22)
        self._font_small = _load_font(None, 16)

    def _draw_base(self, surface):
        surface.fill(BG)
        self._stars.draw(surface)

    def _draw_title(self, surface):
        t = self._font_title.render("RETRO CONSOLE OS", True, CYAN)
        surface.blit(t, t.get_rect(centerx=self.cx, top=28))
        pygame.draw.line(surface, (0, 70, 90),
                         (self.cx - 220, 72), (self.cx + 220, 72), 1)

    def _draw_hint(self, surface, text):
        t = self._font_small.render(text, True, (70, 105, 130))
        surface.blit(t, t.get_rect(centerx=self.cx, bottom=self.h - 18))

    def update(self, dt):
        self._stars.update(dt)

    def draw(self, surface):
        self._draw_base(surface)
        self._draw_title(surface)
        self._crt.draw(surface)

    def on_event(self, event):
        pass


# ─────────────────────────────────────────────────────────────────────────────
class IdleScreen(BaseScreen):

    def __init__(self, width, height):
        super().__init__(width, height)
        self._fp = FingerprintIcon((self.cx, self.cy + 15), base_radius=70)
        self._t  = 0.0

    def update(self, dt):
        super().update(dt)
        self._fp.update(dt, CYAN)
        self._t += dt

    def draw(self, surface):
        self._draw_base(surface)
        self._draw_title(surface)
        self._fp.draw(surface)

        # Pulsing instruction
        alpha = int(160 + 95 * (0.5 + 0.5 * math.sin(self._t * 0.0018)))
        label = self._font_body.render("PLACE FINGER TO AUTHENTICATE",
                                       True, (0, alpha, min(255, alpha + 40)))
        surface.blit(label, label.get_rect(centerx=self.cx, top=self.cy + 105))

        hint = self._font_small.render("[N]  Register new user",
                                       True, (70, 100, 120))
        surface.blit(hint, hint.get_rect(centerx=self.cx, bottom=self.h - 50))

        self._draw_hint(surface, "RetroConsole OS  v2.0")
        self._crt.draw(surface)


# ─────────────────────────────────────────────────────────────────────────────
class ScanScreen(BaseScreen):

    def __init__(self, width, height, timeout_sec=5):
        super().__init__(width, height)
        fp_y = self.cy + 10
        self._fp       = FingerprintIcon((self.cx, fp_y), base_radius=70)
        self._scanline = ScanLine(self.cx, fp_y - 72, fp_y + 72)
        self._bar      = ProgressBar((self.cx - 160, fp_y + 110, 320, 10), CYAN)
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
        surface.blit(label, label.get_rect(centerx=self.cx,
                                            top=self.cy + 133))
        self._crt.draw(surface)


# ─────────────────────────────────────────────────────────────────────────────
class SuccessScreen(BaseScreen):

    def __init__(self, width, height):
        super().__init__(width, height)
        self._font_big = _load_font(None, 46, bold=True)
        self._burst    = None
        self._name     = ""
        self._color    = CYAN
        self._t        = 0.0

    def activate(self, name, color):
        self._name  = name.upper()
        self._color = tuple(color) if isinstance(color, list) else color
        self._burst = GlowBurst((self.cx, self.cy), self._color)
        self._t     = 0.0

    def update(self, dt):
        super().update(dt)
        self._t += dt
        if self._burst:
            self._burst.update(dt)

    def draw(self, surface):
        self._draw_base(surface)
        if self._burst:
            self._burst.draw(surface)
        self._draw_title(surface)

        welcome = self._font_big.render(f"WELCOME, {self._name}!", True, self._color)
        surface.blit(welcome, welcome.get_rect(centerx=self.cx, centery=self.cy - 15))

        sub = self._font_body.render("Starting EmulationStation...", True, GRAY)
        surface.blit(sub, sub.get_rect(centerx=self.cx, top=self.cy + 46))

        self._crt.draw(surface)


# ─────────────────────────────────────────────────────────────────────────────
class FailScreen(BaseScreen):

    def __init__(self, width, height):
        super().__init__(width, height)
        self._font_err = _load_font(None, 30, bold=True)
        self._t        = 0.0

    def reset(self):
        self._t = 0.0

    def update(self, dt):
        super().update(dt)
        self._t += dt

    def draw(self, surface):
        self._draw_base(surface)
        self._draw_title(surface)

        flash  = abs(math.sin(self._t * 0.005))
        red    = (int(255 * flash), 0, 0)
        warn   = self._font_err.render("UNKNOWN FINGERPRINT", True, red)
        surface.blit(warn, warn.get_rect(centerx=self.cx, centery=self.cy - 20))

        msg = self._font_body.render("Please try again or register a new user.", True, GRAY)
        surface.blit(msg, msg.get_rect(centerx=self.cx, top=self.cy + 25))

        hint = self._font_small.render("[N]  Register new user", True, (70, 100, 120))
        surface.blit(hint, hint.get_rect(centerx=self.cx, bottom=self.h - 50))

        self._crt.draw(surface)


# ─────────────────────────────────────────────────────────────────────────────
class EnrollScreen(BaseScreen):
    """
    5-step enrollment wizard.

    Steps:
        0 — Place finger (sensor thread handling)
        1 — Remove finger (sensor thread handling)
        2 — Place finger again (sensor thread handling)
        3 — Enter name (keyboard)
        4 — Choose color (keyboard ← →, ENTER)
        5 — Done (signals completion to LoginUI)
    """

    _STEP_LABELS = [
        "Place your finger on the sensor",
        "Remove your finger",
        "Place your finger again",
        "Enter your name:",
        "Choose your color:",
    ]

    def __init__(self, width, height):
        super().__init__(width, height)
        self._font_step  = _load_font(None, 26, bold=True)
        self._font_input = _load_font(None, 24)
        self.step        = 0
        self.name_input  = ""
        self.color_idx   = 0
        self._fp = FingerprintIcon((self.cx, self.cy + 5), base_radius=62)

    def reset(self):
        self.step       = 0
        self.name_input = ""
        self.color_idx  = 0
        self._fp        = FingerprintIcon((self.cx, self.cy + 5), base_radius=62)

    def get_name(self):
        return self.name_input.strip() or "Player"

    def get_color(self):
        return PRESET_COLORS[self.color_idx]

    def update(self, dt):
        super().update(dt)
        col = PRESET_COLORS[self.color_idx] if self.step == 4 else CYAN
        self._fp.update(dt, col)

    def on_event(self, event):
        if event.type != pygame.KEYDOWN:
            return
        key = event.key

        if self.step == 3:   # name input
            if key == pygame.K_BACKSPACE:
                self.name_input = self.name_input[:-1]
            elif key == pygame.K_RETURN and self.name_input.strip():
                self.step = 4
            elif event.unicode and event.unicode.isprintable() and len(self.name_input) < 20:
                self.name_input += event.unicode

        elif self.step == 4:  # color picker
            if key == pygame.K_LEFT:
                self.color_idx = (self.color_idx - 1) % len(PRESET_COLORS)
            elif key == pygame.K_RIGHT:
                self.color_idx = (self.color_idx + 1) % len(PRESET_COLORS)
            elif key == pygame.K_RETURN:
                self.step = 5   # signals completion

    def draw(self, surface):
        self._draw_base(surface)
        self._draw_title(surface)

        # Step indicator
        step_text = self._font_small.render(
            f"Step {min(self.step + 1, 5)} of 5", True, (80, 115, 140)
        )
        surface.blit(step_text, step_text.get_rect(centerx=self.cx, top=85))

        if self.step < 3:
            self._fp.draw(surface)
            label = self._font_step.render(self._STEP_LABELS[self.step], True, CYAN)
            surface.blit(label, label.get_rect(centerx=self.cx, top=self.cy + 98))

        elif self.step == 3:
            prompt = self._font_step.render("Enter your name:", True, CYAN)
            surface.blit(prompt, prompt.get_rect(centerx=self.cx, centery=self.cy - 50))

            box = pygame.Rect(self.cx - 190, self.cy - 2, 380, 46)
            pygame.draw.rect(surface, DARK, box, border_radius=6)
            pygame.draw.rect(surface, CYAN, box, 1, border_radius=6)

            cursor = "|" if (pygame.time.get_ticks() % 900 < 450) else " "
            inp    = self._font_input.render(self.name_input + cursor, True, WHITE)
            surface.blit(inp, inp.get_rect(midleft=(box.x + 12, box.centery)))

            hint = self._font_small.render("[ENTER] to confirm", True, (70, 100, 120))
            surface.blit(hint, hint.get_rect(centerx=self.cx, top=self.cy + 60))

        elif self.step == 4:
            prompt = self._font_step.render("Choose your color:", True, CYAN)
            surface.blit(prompt, prompt.get_rect(centerx=self.cx, centery=self.cy - 85))

            sw, gap = 48, 12
            total_w = len(PRESET_COLORS) * (sw + gap) - gap
            ox = self.cx - total_w // 2

            for i, col in enumerate(PRESET_COLORS):
                x    = ox + i * (sw + gap)
                rect = pygame.Rect(x, self.cy - sw // 2, sw, sw)
                pygame.draw.rect(surface, col, rect, border_radius=8)
                if i == self.color_idx:
                    pygame.draw.rect(surface, WHITE, rect, 3, border_radius=8)
                    draw_glow_circle(surface, rect.center, sw // 2 + 8, col,
                                     alpha_max=70, layers=4)

            hint = self._font_small.render(
                "[← →] Select   [ENTER] Confirm", True, (70, 100, 120)
            )
            surface.blit(hint, hint.get_rect(centerx=self.cx, top=self.cy + 58))

        elif self.step >= 5:
            done = self._font_step.render("Account created!", True, GREEN)
            surface.blit(done, done.get_rect(centerx=self.cx, centery=self.cy))

        self._crt.draw(surface)
