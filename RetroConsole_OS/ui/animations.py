"""Reusable Pygame animation primitives for RetroConsole login UI."""
import math
import random
import pygame

# Palette
CYAN    = (0, 245, 255)
BLUE    = (0, 102, 255)
MAGENTA = (255, 0, 110)
BG      = (10, 10, 15)


def draw_glow_circle(surface, center, radius, color, alpha_max=120, layers=8):
    """
    Approximate glow by stacking transparent circles from large to small.
    Uses a per-call SRCALPHA surface — best for occasional calls, not every frame.
    """
    size = radius * 2 + layers * 8 + 4
    glow = pygame.Surface((size, size), pygame.SRCALPHA)
    cx = cy = size // 2
    for i in range(layers, 0, -1):
        r = radius + i * 4
        a = int(alpha_max * (1 - i / (layers + 1)))
        pygame.draw.circle(glow, (*color, a), (cx, cy), r)
    surface.blit(glow, (center[0] - cx, center[1] - cy))


class StarField:
    """Slowly drifting star particles for the background."""

    def __init__(self, width, height, count=140):
        self.w, self.h = width, height
        self._stars = [self._make_star(width, height) for _ in range(count)]

    @staticmethod
    def _make_star(w, h, random_y=True):
        return {
            'x':     random.randint(0, w),
            'y':     random.randint(0, h) if random_y else 0,
            'speed': random.uniform(0.04, 0.25),
            'size':  random.choice([1, 1, 1, 1, 2]),
            'alpha': random.randint(70, 230),
        }

    def update(self, dt):
        for s in self._stars:
            s['y'] += s['speed'] * dt * 0.05
            if s['y'] > self.h:
                s.update(self._make_star(self.w, self.h, random_y=False))

    def draw(self, surface):
        for s in self._stars:
            x, y, a = int(s['x']), int(s['y']), s['alpha']
            col = (a, a, a)
            if s['size'] == 1:
                surface.set_at((x, y), col)
            else:
                pygame.draw.circle(surface, col, (x, y), s['size'])


class FingerprintIcon:
    """Animated fingerprint icon — concentric arcs with breathing glow."""

    _ARC_COUNT = 8
    _ARC_SPACING = 8   # px between arcs
    _LINE_WIDTH = 2

    def __init__(self, center, base_radius=68):
        self.center = center
        self.base_radius = base_radius
        self.color = CYAN
        self._t = 0.0

    def update(self, dt, color=None):
        self._t += dt * 0.001
        if color is not None:
            self.color = color

    def draw(self, surface):
        cx, cy = self.center
        pulse = 0.5 + 0.5 * math.sin(self._t * 1.8)

        # Glow halo
        glow_r = self.base_radius + int(12 * pulse)
        draw_glow_circle(surface, self.center, glow_r, self.color,
                         alpha_max=int(50 + 50 * pulse), layers=6)

        # Concentric arcs — each arc narrows as it approaches centre
        for i in range(self._ARC_COUNT):
            r = self.base_radius - i * self._ARC_SPACING
            if r < 6:
                break
            margin = math.radians(18 + i * 5)
            start  = margin
            end    = math.pi * 2 - margin
            if end <= start:
                continue
            rect = pygame.Rect(cx - r, cy - r, r * 2, r * 2)
            pygame.draw.arc(surface, self.color, rect, start, end,
                            self._LINE_WIDTH)

        # Centre dot
        pygame.draw.circle(surface, self.color, (cx, cy), 3)


class ScanLine:
    """Horizontal cyan scan line sweeping over the fingerprint area."""

    def __init__(self, center_x, top_y, bottom_y, width=130):
        self._cx    = center_x
        self._top   = top_y
        self._bot   = bottom_y
        self._w     = width
        self._y     = float(top_y)
        self._speed = 0.12   # px per ms

    def reset(self):
        self._y = float(self._top)

    def update(self, dt):
        self._y += self._speed * dt
        if self._y > self._bot:
            self._y = float(self._top)

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
        self.progress = 1.0   # 1.0 = full

    def draw(self, surface):
        pygame.draw.rect(surface, self.bg, self.rect, border_radius=4)
        filled_w = max(0, int(self.rect.w * self.progress))
        if filled_w:
            filled = pygame.Rect(self.rect.x, self.rect.y,
                                 filled_w, self.rect.h)
            pygame.draw.rect(surface, self.color, filled, border_radius=4)
        pygame.draw.rect(surface, self.color, self.rect, 1, border_radius=4)


class CRTOverlay:
    """Subtle horizontal scanline overlay — baked into a single surface."""

    def __init__(self, width, height):
        self._surf = pygame.Surface((width, height), pygame.SRCALPHA)
        for y in range(0, height, 3):
            pygame.draw.line(self._surf, (0, 0, 0, 28), (0, y), (width, y))

    def draw(self, surface):
        surface.blit(self._surf, (0, 0))


class GlowBurst:
    """Expanding ring burst for the SUCCESS screen."""

    DURATION_MS = 1400

    def __init__(self, center, color):
        self.center = center
        self.color  = color
        self._t     = 0
        self.done   = False

    def update(self, dt):
        self._t += dt
        if self._t >= self.DURATION_MS:
            self.done = True

    def draw(self, surface):
        if self.done:
            return
        p = self._t / self.DURATION_MS
        for i in range(5):
            r     = int(p * (180 + i * 45))
            alpha = int(190 * (1 - p))
            draw_glow_circle(surface, self.center, r, self.color,
                             alpha_max=alpha, layers=4)
