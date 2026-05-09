"""Reusable Pygame animation primitives for RetroConsole login UI.

All classes are resolution-independent: sizes are passed as constructor
arguments so the screen classes can scale them to the actual display.
"""
import math
import random
import pygame

# Palette
CYAN    = (0, 245, 255)
BLUE    = (0, 102, 255)
MAGENTA = (255, 0, 110)
BG      = (10, 10, 15)


def draw_glow_circle(surface, center, radius, color, alpha_max=120, layers=6):
    """
    Approximate glow by stacking transparent circles from large to small.
    Uses a per-call SRCALPHA surface — keep calls per frame low.
    """
    if radius < 2:
        return
    pad  = layers * 5
    size = radius * 2 + pad * 2
    glow = pygame.Surface((size, size), pygame.SRCALPHA)
    cx = cy = size // 2
    for i in range(layers, 0, -1):
        r = radius + i * 4
        a = int(alpha_max * (1 - i / (layers + 1)))
        pygame.draw.circle(glow, (*color, a), (cx, cy), r)
    surface.blit(glow, (center[0] - cx, center[1] - cy))


class StarField:
    """Slowly drifting star particles for the background."""

    def __init__(self, width, height, count=80):
        self.w, self.h = width, height
        self._stars = [self._make(width, height) for _ in range(count)]

    @staticmethod
    def _make(w, h, random_y=True):
        return {
            'x':     random.randint(0, w),
            'y':     random.randint(0, h) if random_y else 0,
            'speed': random.uniform(0.03, 0.18),
            'size':  random.choice([1, 1, 1, 2]),
            'alpha': random.randint(70, 210),
        }

    def update(self, dt):
        for s in self._stars:
            s['y'] += s['speed'] * dt * 0.05
            if s['y'] > self.h:
                s.update(self._make(self.w, self.h, random_y=False))

    def draw(self, surface):
        for s in self._stars:
            x, y, a = int(s['x']), int(s['y']), s['alpha']
            if s['size'] == 1:
                surface.set_at((x, y), (a, a, a))
            else:
                pygame.draw.circle(surface, (a, a, a), (x, y), s['size'])


class FingerprintIcon:
    """
    Animated fingerprint icon — concentric arcs with breathing glow.
    base_radius controls the overall size; all internal dimensions derive
    from it so the icon scales correctly at any resolution.
    """

    def __init__(self, center, base_radius=52):
        self.center      = center
        self.base_radius = base_radius
        self.color       = CYAN
        self._t          = 0.0
        # Derived layout — scale with base_radius
        self._arc_count   = max(5, base_radius // 7)
        self._arc_spacing = max(4, base_radius // 9)
        self._line_width  = max(1, base_radius // 26)

    def update(self, dt, color=None):
        self._t += dt * 0.001
        if color is not None:
            self.color = color

    def draw(self, surface):
        cx, cy   = self.center
        pulse    = 0.5 + 0.5 * math.sin(self._t * 1.8)
        glow_r   = self.base_radius + int(self.base_radius * 0.15 * pulse)
        glow_a   = int(45 + 45 * pulse)
        draw_glow_circle(surface, self.center, glow_r, self.color,
                         alpha_max=glow_a, layers=5)

        for i in range(self._arc_count):
            r = self.base_radius - i * self._arc_spacing
            if r < 4:
                break
            margin = math.radians(18 + i * 6)
            start  = margin
            end    = math.pi * 2 - margin
            if end <= start:
                continue
            rect = pygame.Rect(cx - r, cy - r, r * 2, r * 2)
            pygame.draw.arc(surface, self.color, rect, start, end,
                            self._line_width)

        pygame.draw.circle(surface, self.color, (cx, cy),
                           max(2, self._line_width + 1))


class ScanLine:
    """Horizontal cyan scan line sweeping over the fingerprint area."""

    def __init__(self, center_x, top_y, bottom_y, width=100):
        self._cx    = center_x
        self._top   = float(top_y)
        self._bot   = float(bottom_y)
        self._w     = width
        self._y     = float(top_y)
        # Speed: cross the full span in ~1 s
        span        = max(1, bottom_y - top_y)
        self._speed = span / 900.0   # px per ms

    def reset(self):
        self._y = self._top

    def update(self, dt):
        self._y += self._speed * dt
        if self._y > self._bot:
            self._y = self._top

    def draw(self, surface):
        y = int(self._y)
        for dy, h, alpha in [(0, 3, 200), (-3, 2, 60), (-6, 1, 20)]:
            s = pygame.Surface((self._w, h), pygame.SRCALPHA)
            s.fill((0, 245, 255, alpha))
            surface.blit(s, (self._cx - self._w // 2, y + dy))


class ProgressBar:
    """Horizontal bar that depletes from right to left."""

    def __init__(self, rect, color=CYAN, bg=(25, 25, 40)):
        self.rect     = pygame.Rect(rect)
        self.color    = color
        self.bg       = bg
        self.progress = 1.0

    def draw(self, surface):
        pygame.draw.rect(surface, self.bg, self.rect, border_radius=3)
        filled_w = max(0, int(self.rect.w * self.progress))
        if filled_w:
            filled = pygame.Rect(self.rect.x, self.rect.y,
                                 filled_w, self.rect.h)
            pygame.draw.rect(surface, self.color, filled, border_radius=3)
        pygame.draw.rect(surface, self.color, self.rect, 1, border_radius=3)


class CRTOverlay:
    """Subtle horizontal scanline overlay — baked once into a surface."""

    def __init__(self, width, height, spacing=3, alpha=22):
        self._surf = pygame.Surface((width, height), pygame.SRCALPHA)
        for y in range(0, height, spacing):
            pygame.draw.line(self._surf, (0, 0, 0, alpha), (0, y), (width, y))

    def draw(self, surface):
        surface.blit(self._surf, (0, 0))


class GlowBurst:
    """Expanding ring burst for the SUCCESS screen."""

    DURATION_MS = 1400

    def __init__(self, center, color, max_radius=None):
        self.center     = center
        self.color      = color
        self._max_r     = max_radius or 200
        self._t         = 0
        self.done       = False

    def update(self, dt):
        self._t += dt
        if self._t >= self.DURATION_MS:
            self.done = True

    def draw(self, surface):
        if self.done:
            return
        p = self._t / self.DURATION_MS
        for i in range(4):
            r     = int(p * (self._max_r + i * 30))
            alpha = int(180 * (1 - p))
            draw_glow_circle(surface, self.center, r, self.color,
                             alpha_max=alpha, layers=3)
