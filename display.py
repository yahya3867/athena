import re
import socket
import sys
import os
import threading
import time
from datetime import datetime

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from PIL import Image, ImageDraw, ImageFont

import config

_WHISPLAY_DRIVER_CANDIDATES = [
    os.path.join(os.path.expanduser("~"), "Whisplay", "Driver"),
    "/home/pi/Whisplay/Driver",
    "/home/athena_pi/Whisplay/Driver",
]

for _driver_path in _WHISPLAY_DRIVER_CANDIDATES:
    if os.path.exists(os.path.join(_driver_path, "WhisPlay.py")):
        sys.path.append(_driver_path)
        break

from WhisPlay import WhisPlayBoard  # pyright: ignore[reportMissingImports]

_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_FONT_PATH_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_EMOJI_FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoEmoji-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    os.path.expanduser("~/.fonts/NotoColorEmoji.ttf"),
    "/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",
]

STATUS_FONT_SIZE = 20
STATUS_SUB_FONT_SIZE = 15
RESPONSE_FONT_SIZE = 21
TITLE_FONT_SIZE = 16
BATTERY_FONT_SIZE = 12
CLOCK_FONT_SIZE = 34
IDLE_BATTERY_FONT_SIZE = 15
IDLE_CLOCK_FONT_SIZE = 42
ACCENT_BAR_HEIGHT = 3
POWER_SUPPLY_SYS = "/sys/class/power_supply"
PISUGAR_SOCKET = "/tmp/pisugar-server.sock"
IDLE_BG_COLOR = (186, 224, 255)
IDLE_PANEL_COLOR = (138, 183, 226)
IDLE_PANEL_DARK = (102, 150, 198)
IDLE_FOOTER_COLOR = (116, 181, 90)
IDLE_PRIMARY_TEXT = (24, 49, 84)
IDLE_SECONDARY_TEXT = (59, 88, 126)
IDLE_FOOTER_TEXT = (36, 83, 28)
SCENE_PANEL_FILL = (220, 236, 248)
SCENE_PANEL_STROKE = (120, 162, 205)
OWL_SCENE_POS = (0, 64)
TOP_PANEL_HEIGHT = 60
FOOTER_HEIGHT = 36


def _load_emoji_font(size: int) -> ImageFont.FreeTypeFont | None:
    for path in _EMOJI_FONT_PATHS:
        if not os.path.exists(path):
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            # e.g. Noto Color Emoji: "invalid pixel size" (fixed-size font)
            continue
    return None


def _is_emoji(c: str) -> bool:
    if not c:
        return False
    cp = ord(c[0])
    return (
        0x2600 <= cp <= 0x26FF  # Misc Symbols
        or 0x2700 <= cp <= 0x27BF  # Dingbats
        or 0x2B50 <= cp <= 0x2B55
        or 0x1F300 <= cp <= 0x1F5FF  # Misc Symbols and Pictographs
        or 0x1F600 <= cp <= 0x1F64F  # Emoticons
        or 0x1F680 <= cp <= 0x1F6FF  # Transport and Map
        or 0x1F900 <= cp <= 0x1F9FF  # Supplemental Symbols
        or 0x1F000 <= cp <= 0x1F02F  # Mahjong etc
        or 0x1F0A0 <= cp <= 0x1F0FF  # Playing cards
        or 0xFE00 <= cp <= 0xFE0F   # Variation selectors
        or cp == 0x200D             # ZWJ
        or 0x1F3FB <= cp <= 0x1F3FF  # Skin tone modifiers
        or 0xE0020 <= cp <= 0xE007F
    )


def _is_emoji_modifier(c: str) -> bool:
    if not c:
        return False
    cp = ord(c[0])
    return cp == 0x200D or 0xFE00 <= cp <= 0xFE0F or 0x1F3FB <= cp <= 0x1F3FF


def _segment_mixed(text: str):
    """Yield (segment, use_emoji_font). Batches consecutive non-emoji chars into one segment."""
    i = 0
    while i < len(text):
        c = text[i]
        if _is_emoji(c):
            start = i
            i += 1
            while i < len(text) and (_is_emoji_modifier(text[i]) or _is_emoji(text[i])):
                i += 1
            yield (text[start:i], True)
        else:
            start = i
            i += 1
            while i < len(text) and not _is_emoji(text[i]):
                i += 1
            yield (text[start:i], False)


_RE_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_RE_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_RE_CODE = re.compile(r"`(.+?)`")
_RE_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_BULLET = re.compile(r"^[\-\*]\s+", re.MULTILINE)
_RE_NUMLIST = re.compile(r"^\d+[.)]\s+", re.MULTILINE)


def _clean_markdown(text: str) -> str:
    """Strip markdown formatting so LLM responses look clean on a small screen."""
    text = _RE_BOLD.sub(lambda m: m.group(1) or m.group(2), text)
    text = _RE_ITALIC.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = _RE_CODE.sub(r"\1", text)
    text = _RE_HEADING.sub("", text)
    text = _RE_BULLET.sub("\u2022 ", text)
    text = _RE_NUMLIST.sub("\u2022 ", text)
    return text


def _wifi_connected() -> bool:
    """Check wlan0 interface state (cheap file read, no subprocess)."""
    try:
        with open("/sys/class/net/wlan0/operstate") as f:
            return f.read().strip() == "up"
    except OSError:
        return False


def _read_pisugar_battery() -> tuple[int | None, str | None]:
    """Read battery from PiSugar server (Unix socket). Returns (pct, status) or (None, None)."""
    if not os.path.exists(PISUGAR_SOCKET):
        return (None, None)
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(PISUGAR_SOCKET)
        sock.sendall(b"get battery\n")
        data = sock.recv(64).decode("utf-8", errors="ignore").strip()
        sock.close()
        # Response: "95" or "battery: 95"
        m = re.search(r"(\d+)", data)
        if not m:
            return (None, None)
        pct = max(0, min(100, int(m.group(1))))
        status = None
        try:
            s2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s2.settimeout(0.5)
            s2.connect(PISUGAR_SOCKET)
            s2.sendall(b"get battery_charging\n")
            ch = s2.recv(64).decode("utf-8", errors="ignore").strip().lower()
            s2.close()
            if "true" in ch:
                status = "Charging"
            elif "false" in ch:
                status = "Discharging"
        except (OSError, socket.error):
            pass
        return (pct, status)
    except (OSError, socket.error, ValueError):
        return (None, None)


def _read_battery() -> tuple[int | None, str | None]:
    """Read battery capacity (0–100) and status. Tries PiSugar first, then sysfs. Returns (pct, status) or (None, None)."""
    result = _read_pisugar_battery()
    if result[0] is not None:
        return result
    if not os.path.isdir(POWER_SUPPLY_SYS):
        return (None, None)

    def is_battery_dir(base: str) -> bool:
        type_path = os.path.join(base, "type")
        if os.path.isfile(type_path):
            try:
                with open(type_path) as f:
                    return f.read().strip().upper() == "BATTERY"
            except OSError:
                pass
        return False

    for name in sorted(os.listdir(POWER_SUPPLY_SYS)):
        base = os.path.join(POWER_SUPPLY_SYS, name)
        if not os.path.isdir(base):
            continue
        # Accept BAT*, "battery", or any dir whose type file says Battery
        if not (name.upper().startswith("BAT") or name.lower() == "battery" or is_battery_dir(base)):
            continue
        cap_path = os.path.join(base, "capacity")
        status_path = os.path.join(base, "status")
        energy_now_path = os.path.join(base, "energy_now")
        energy_full_path = os.path.join(base, "energy_full")

        pct = None
        if os.path.isfile(cap_path):
            try:
                with open(cap_path) as f:
                    pct = int(f.read().strip())
            except (ValueError, OSError):
                pass
        if pct is None and os.path.isfile(energy_now_path) and os.path.isfile(energy_full_path):
            try:
                with open(energy_now_path) as f:
                    now = int(f.read().strip())
                with open(energy_full_path) as f:
                    full = int(f.read().strip())
                if full > 0:
                    pct = int(100 * now / full)
            except (ValueError, OSError):
                pass

        if pct is not None:
            pct = max(0, min(100, pct))
            status = None
            if os.path.isfile(status_path):
                try:
                    with open(status_path) as f:
                        status = f.read().strip()
                except OSError:
                    pass
            return (pct, status)
    return (None, None)


# ── Pixel-art sprite frame generation (Kirby-inspired owl) ───────

_SPX = 8  # each "pixel" is an 8×8 block → 30×30 logical grid on 240×240

_C_BODY = (153, 125, 92)
_C_HIGHLIGHT = (196, 170, 136)
_C_BODY_DARK = (98, 74, 52)
_C_FACE = (226, 212, 186)
_C_BELLY = (212, 197, 172)
_C_OUTLINE = (44, 28, 18)
_C_FOOT = (122, 92, 56)
_C_BEAK = (164, 124, 72)
_C_EYE = (18, 18, 24)
_C_SPARKLE = (255, 255, 255)
_C_MOUTH_INT = (20, 20, 30)
_C_MOUTH_EDGE = (110, 86, 60)

# Round owl body
_MAIN_CELLS: set[tuple[int, int]] = set()
_body_def: dict[int, tuple[int, int]] = {
    4: (12, 17), 5: (10, 19), 6: (9, 20), 7: (8, 21),
    17: (8, 21), 18: (9, 20), 19: (10, 19), 20: (12, 17),
}
for _r in range(8, 17):
    _body_def[_r] = (7, 22)
for _r, (_s, _e) in _body_def.items():
    for _c in range(_s, _e + 1):
        _MAIN_CELLS.add((_c, _r))

# Pointed owl ear tufts
_EAR_CELLS: set[tuple[int, int]] = set()
for _p in [
    (8, 4), (9, 3), (10, 2), (10, 3), (10, 4),
    (19, 2), (19, 3), (19, 4), (20, 3), (21, 4),
]:
    _EAR_CELLS.add(_p)

# Tiny wings
_ARM_CELLS: set[tuple[int, int]] = set()
for _p in [
    (5, 12), (5, 13), (5, 14), (5, 15), (6, 12), (6, 13), (6, 14), (6, 15), (7, 16),
    (24, 12), (24, 13), (24, 14), (24, 15), (23, 12), (23, 13), (23, 14), (23, 15), (22, 16),
    (6, 16), (6, 17), (23, 16), (23, 17),
]:
    _ARM_CELLS.add(_p)

# Owl feet
_FOOT_CELLS: set[tuple[int, int]] = set()
for _p in [
    (10, 20), (11, 20), (12, 20), (11, 21), (10, 22), (11, 22), (12, 22),
    (17, 20), (18, 20), (19, 20), (18, 21), (17, 22), (18, 22), (19, 22),
]:
    _FOOT_CELLS.add(_p)

_BODY_CELLS = _MAIN_CELLS | _EAR_CELLS | _ARM_CELLS | _FOOT_CELLS

_FACE_CELLS: set[tuple[int, int]] = set()
for _r, (_s, _e) in {
    8: (8, 21), 9: (8, 21), 10: (8, 21), 11: (8, 21), 12: (9, 20), 13: (9, 20), 14: (10, 19),
}.items():
    for _c in range(_s, _e + 1):
        _FACE_CELLS.add((_c, _r))

_BELLY_CELLS: set[tuple[int, int]] = set()
for _r, (_s, _e) in {
    14: (10, 19), 15: (9, 20), 16: (9, 20), 17: (10, 19), 18: (11, 18),
}.items():
    for _c in range(_s, _e + 1):
        _BELLY_CELLS.add((_c, _r))

_CHEST_MARKS: set[tuple[int, int]] = {
    (12, 15), (15, 15), (18, 15),
    (13, 16), (16, 16),
    (12, 17), (15, 17), (18, 17),
}


def _body_color(cx: int, cy: int) -> tuple[int, int, int]:
    if (cx, cy) in _FOOT_CELLS and (cx, cy) not in _MAIN_CELLS:
        return _C_FOOT
    if (cx, cy) in _FACE_CELLS:
        return _C_FACE
    if (cx, cy) in _BELLY_CELLS:
        return _C_BELLY
    if (cx, cy) in _CHEST_MARKS:
        return _C_BODY_DARK
    if cx <= 10 or cy >= 18:
        return _C_BODY_DARK
    if (cx, cy) in {
        (10, 8), (11, 8), (12, 8), (9, 9), (10, 9), (11, 9), (12, 9),
        (9, 10), (10, 10), (11, 10),
    }:
        return _C_HIGHLIGHT
    return _C_BODY


def _spx(draw: ImageDraw.ImageDraw, gx: int, gy: int, color: tuple[int, int, int]):
    x0, y0 = gx * _SPX, gy * _SPX
    draw.rectangle((x0, y0, x0 + _SPX - 1, y0 + _SPX - 1), fill=color)


def _sprite_body(draw: ImageDraw.ImageDraw):
    for cx, cy in _BODY_CELLS:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = cx + dx, cy + dy
            if (nx, ny) not in _BODY_CELLS and 0 <= nx < 30 and 0 <= ny < 30:
                _spx(draw, nx, ny, _C_OUTLINE)
    for cx, cy in _BODY_CELLS:
        _spx(draw, cx, cy, _body_color(cx, cy))
    for cx, cy in _FOOT_CELLS:
        _spx(draw, cx, cy, _C_FOOT)
    for gx in range(9, 21):
        if gx in (9, 20):
            _spx(draw, gx, 27, (86, 86, 96))
        else:
            _spx(draw, gx, 27, (120, 120, 132))


def _sprite_eyes_open(
    draw: ImageDraw.ImageDraw, dx: int = 0, dy: int = 0, wide: bool = False,
):
    eye_y = 9 if wide else 10
    left_eye = {
        (9, eye_y), (10, eye_y), (11, eye_y), (12, eye_y),
        (8, eye_y + 1), (9, eye_y + 1), (10, eye_y + 1), (11, eye_y + 1), (12, eye_y + 1), (13, eye_y + 1),
        (8, eye_y + 2), (9, eye_y + 2), (10, eye_y + 2), (11, eye_y + 2), (12, eye_y + 2), (13, eye_y + 2),
        (9, eye_y + 3), (10, eye_y + 3), (11, eye_y + 3), (12, eye_y + 3),
    }
    right_eye = {
        (17, eye_y), (18, eye_y), (19, eye_y), (20, eye_y),
        (16, eye_y + 1), (17, eye_y + 1), (18, eye_y + 1), (19, eye_y + 1), (20, eye_y + 1), (21, eye_y + 1),
        (16, eye_y + 2), (17, eye_y + 2), (18, eye_y + 2), (19, eye_y + 2), (20, eye_y + 2), (21, eye_y + 2),
        (17, eye_y + 3), (18, eye_y + 3), (19, eye_y + 3), (20, eye_y + 3),
    }
    for ex, ey in left_eye | right_eye:
        _spx(draw, ex, ey, _C_EYE)
    sx = max(9, min(11, 10 + dx))
    sy = max(eye_y, min(eye_y + 1, eye_y + dy))
    _spx(draw, sx, sy, _C_SPARKLE)
    _spx(draw, sx, sy + 1, _C_SPARKLE)
    rx = max(17, min(19, 18 + dx))
    _spx(draw, rx, sy, _C_SPARKLE)
    _spx(draw, rx, sy + 1, _C_SPARKLE)
    for bx, by in {(14, 13), (15, 13), (13, 14), (14, 14), (15, 14), (16, 14), (14, 15), (15, 15), (14, 16), (15, 16)}:
        _spx(draw, bx, by, _C_BEAK)


def _sprite_eyes_blink(draw: ImageDraw.ImageDraw):
    for ex in (9, 10, 11, 12, 17, 18, 19, 20):
        _spx(draw, ex, 12, _C_EYE)
    for bx, by in {(14, 13), (15, 13), (14, 14), (15, 14)}:
        _spx(draw, bx, by, _C_BEAK)


def _sprite_eyes_happy(draw: ImageDraw.ImageDraw):
    for col in (9, 10, 11, 12):
        _spx(draw, col, 11, _C_EYE)
    _spx(draw, 9, 12, _C_EYE)
    _spx(draw, 12, 12, _C_EYE)
    for col in (17, 18, 19, 20):
        _spx(draw, col, 11, _C_EYE)
    _spx(draw, 17, 12, _C_EYE)
    _spx(draw, 20, 12, _C_EYE)
    for bx, by in {(14, 13), (15, 13), (14, 14), (15, 14)}:
        _spx(draw, bx, by, _C_BEAK)


def _sprite_mouth_closed(draw: ImageDraw.ImageDraw):
    _spx(draw, 14, 16, _C_MOUTH_EDGE)
    _spx(draw, 15, 16, _C_MOUTH_EDGE)


def _sprite_mouth_smile(draw: ImageDraw.ImageDraw):
    _spx(draw, 13, 16, _C_MOUTH_EDGE)
    _spx(draw, 16, 16, _C_MOUTH_EDGE)
    _spx(draw, 14, 17, _C_MOUTH_EDGE)
    _spx(draw, 15, 17, _C_MOUTH_EDGE)


def _sprite_mouth_small(draw: ImageDraw.ImageDraw):
    _spx(draw, 14, 16, _C_MOUTH_EDGE)
    _spx(draw, 15, 16, _C_MOUTH_EDGE)
    _spx(draw, 14, 17, _C_MOUTH_INT)
    _spx(draw, 15, 17, _C_MOUTH_INT)


def _sprite_mouth_open(draw: ImageDraw.ImageDraw):
    for col in (14, 15):
        _spx(draw, col, 16, _C_MOUTH_EDGE)
        _spx(draw, col, 18, _C_MOUTH_EDGE)
    _spx(draw, 13, 17, _C_MOUTH_EDGE)
    _spx(draw, 16, 17, _C_MOUTH_EDGE)
    _spx(draw, 14, 17, _C_MOUTH_INT)
    _spx(draw, 15, 17, _C_MOUTH_INT)


def _sprite_mouth_wide(draw: ImageDraw.ImageDraw):
    for col in range(13, 17):
        _spx(draw, col, 15, _C_MOUTH_EDGE)
        _spx(draw, col, 19, _C_MOUTH_EDGE)
    for row in (16, 17, 18):
        _spx(draw, 13, row, _C_MOUTH_EDGE)
        _spx(draw, 16, row, _C_MOUTH_EDGE)
        _spx(draw, 14, row, _C_MOUTH_INT)
        _spx(draw, 15, row, _C_MOUTH_INT)


def _make_sprite(eyes_fn, mouth_fn) -> Image.Image:
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    _sprite_body(draw)
    eyes_fn(draw)
    mouth_fn(draw)
    return img


def _apply_blink(sprite: Image.Image) -> Image.Image:
    """Return a copy with closed-eye lines drawn over the eye area."""
    img = sprite.copy()
    draw = ImageDraw.Draw(img)
    for ey in range(7, 15):
        for ex in (10, 11, 12, 17, 18, 19):
            if (ex, ey) in _BODY_CELLS:
                _spx(draw, ex, ey, _body_color(ex, ey))
    _sprite_eyes_blink(draw)
    return img


def _generate_sprite_frames() -> dict[str, Image.Image]:
    bases = {
        "idle": _make_sprite(_sprite_eyes_open, _sprite_mouth_smile),
        "listen": _make_sprite(
            lambda d: _sprite_eyes_open(d, wide=True), _sprite_mouth_small,
        ),
        "think1": _make_sprite(
            lambda d: _sprite_eyes_open(d, dx=1, dy=-1), _sprite_mouth_closed,
        ),
        "think2": _make_sprite(
            lambda d: _sprite_eyes_open(d, dx=-1, dy=-1), _sprite_mouth_closed,
        ),
        "talk0": _make_sprite(_sprite_eyes_open, _sprite_mouth_closed),
        "talk1": _make_sprite(_sprite_eyes_open, _sprite_mouth_small),
        "talk2": _make_sprite(_sprite_eyes_open, _sprite_mouth_open),
        "talk3": _make_sprite(_sprite_eyes_open, _sprite_mouth_wide),
        "happy": _make_sprite(_sprite_eyes_happy, _sprite_mouth_smile),
    }
    frames = dict(bases)
    for key, sprite in bases.items():
        frames[key + "_blink"] = _apply_blink(sprite)
    return frames


class Display:
    def __init__(self, backlight=70):
        self.board = WhisPlayBoard()
        self.board.set_backlight(backlight)

        self._width = self.board.LCD_WIDTH
        self._height = self.board.LCD_HEIGHT

        self._status_font = ImageFont.truetype(_FONT_PATH, STATUS_FONT_SIZE)
        self._status_sub_font = ImageFont.truetype(_FONT_PATH_REGULAR, STATUS_SUB_FONT_SIZE)
        self._response_font = ImageFont.truetype(_FONT_PATH_REGULAR, RESPONSE_FONT_SIZE)
        self._title_font = ImageFont.truetype(_FONT_PATH, TITLE_FONT_SIZE)
        try:
            self._battery_font = ImageFont.truetype(_FONT_PATH_REGULAR, BATTERY_FONT_SIZE)
        except OSError:
            self._battery_font = self._status_sub_font  # fallback so battery corner still draws
        self._clock_font = ImageFont.truetype(_FONT_PATH, CLOCK_FONT_SIZE)
        self._idle_battery_font = ImageFont.truetype(_FONT_PATH, IDLE_BATTERY_FONT_SIZE)
        self._idle_clock_font = ImageFont.truetype(_FONT_PATH, IDLE_CLOCK_FONT_SIZE)
        self._emoji_status = _load_emoji_font(STATUS_FONT_SIZE)
        self._emoji_response = _load_emoji_font(RESPONSE_FONT_SIZE)

        self._response_buf = ""
        self._last_draw_time = 0.0
        fps = max(1, getattr(config, "UI_MAX_FPS", 10))
        self._min_draw_interval = 1.0 / fps

        self._pad_x = 10
        self._pad_y = 8

        self._default_backlight = backlight
        self._sleeping = False
        self._draw_lock = threading.Lock()
        self._transient_lock = threading.Lock()
        self._cached_paragraphs: list[str] = []
        self._cached_wrapped: list[list[str]] = []
        self._sprite_frames = _generate_sprite_frames()
        self._blank_buf = [0] * (self._width * self._height * 2)
        self._image_path: str | None = None
        self._image_cache: Image.Image | None = None
        self._render_generation = 0
        self._active_transient_kind: str | None = None

        self.clear()

    def sleep(self):
        if self._sleeping:
            return
        self._sleeping = True
        self.clear()
        self.board.set_backlight(0)

    def wake(self):
        if not self._sleeping:
            return
        self._sleeping = False
        self.board.set_backlight(self._default_backlight)

    @property
    def is_sleeping(self) -> bool:
        return self._sleeping

    def is_showing_image(self) -> bool:
        return bool(self._image_path)

    def has_active_transient_renderer(self) -> bool:
        with self._transient_lock:
            return self._active_transient_kind is not None

    def _invalidate_transient_renderers(self) -> None:
        with self._transient_lock:
            self._render_generation += 1
            self._active_transient_kind = None

    def _claim_transient_renderer(self, kind: str) -> int:
        with self._transient_lock:
            self._render_generation += 1
            self._active_transient_kind = kind
            return self._render_generation

    def _transient_generation_active(self, generation: int) -> bool:
        with self._transient_lock:
            return generation == self._render_generation

    def _clear_transient_kind_if_current(self, generation: int) -> None:
        with self._transient_lock:
            if generation == self._render_generation:
                self._active_transient_kind = None

    def _draw_mixed(
        self,
        draw: ImageDraw.ImageDraw,
        xy: tuple[int, int],
        text: str,
        text_font: ImageFont.FreeTypeFont,
        emoji_font: ImageFont.FreeTypeFont | None,
        fill: tuple[int, int, int],
        max_x: int = 0,
    ) -> float:
        """Draw text with emoji fallback (by segment/cluster), returns total width drawn.

        When *max_x* > 0, stop drawing before exceeding that x coordinate.
        """
        x, y = xy
        right_limit = max_x if max_x > 0 else self._width
        for segment, use_emoji in _segment_mixed(text):
            if use_emoji and emoji_font:
                font = emoji_font
                draw_seg = segment
            else:
                font = text_font
                draw_seg = "?" if use_emoji else segment
            try:
                seg_w = font.getlength(draw_seg)
                if x + seg_w > right_limit:
                    for ch in draw_seg:
                        ch_w = font.getlength(ch)
                        if x + ch_w > right_limit:
                            break
                        draw.text((x, y), ch, font=font, fill=fill)
                        x += ch_w
                    return x - xy[0]
                draw.text((x, y), draw_seg, font=font, fill=fill)
                x += seg_w
            except Exception:
                try:
                    draw.text((x, y), "?", font=text_font, fill=fill)
                    x += text_font.getlength("?")
                except Exception:
                    x += text_font.getlength("?")
        return x - xy[0]

    def _text_width_mixed(
        self,
        text: str,
        text_font: ImageFont.FreeTypeFont,
        emoji_font: ImageFont.FreeTypeFont | None,
    ) -> float:
        w = 0.0
        for segment, use_emoji in _segment_mixed(text):
            if use_emoji and emoji_font:
                try:
                    w += emoji_font.getlength(segment)
                except Exception:
                    w += text_font.getlength("?")
            else:
                seg = "?" if use_emoji else segment
                w += text_font.getlength(seg)
        return w

    def _truncate_text(
        self,
        text: str,
        font: ImageFont.FreeTypeFont,
        max_w: float,
        emoji_font: ImageFont.FreeTypeFont | None = None,
    ) -> str:
        """Truncate *text* so it fits within *max_w* pixels, adding '…' if shortened."""
        def _measure(s: str) -> float:
            if emoji_font:
                return self._text_width_mixed(s, font, emoji_font)
            return font.getlength(s)

        if _measure(text) <= max_w:
            return text
        ellipsis_w = font.getlength("…")
        while len(text) > 1 and _measure(text) + ellipsis_w > max_w:
            text = text[:-1]
        return text + "…"

    def _wrap_pixels(
        self,
        text: str,
        font: ImageFont.FreeTypeFont,
        max_w: int,
        emoji_font: ImageFont.FreeTypeFont | None = None,
    ) -> list[str]:
        """Word-wrap text to fit within *max_w* pixels, accounting for emoji font widths."""
        def _measure(s: str) -> float:
            if emoji_font:
                return self._text_width_mixed(s, font, emoji_font)
            return font.getlength(s)

        words = text.split(" ")
        lines: list[str] = []
        cur = ""
        for word in words:
            test = f"{cur} {word}" if cur else word
            if _measure(test) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                if _measure(word) > max_w:
                    buf = ""
                    for ch in word:
                        if _measure(buf + ch) > max_w and buf:
                            lines.append(buf)
                            buf = ch
                        else:
                            buf += ch
                    cur = buf
                else:
                    cur = word
        if cur:
            lines.append(cur)
        return lines

    def _image_to_rgb565(self, image: Image.Image) -> list[int]:
        raw = image.tobytes("raw", "RGB")
        if _HAS_NUMPY:
            arr = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
            r = arr[:, 0].astype(np.uint16)
            g = arr[:, 1].astype(np.uint16)
            b = arr[:, 2].astype(np.uint16)
            rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            packed = np.empty(rgb565.shape[0] * 2, dtype=np.uint8)
            packed[0::2] = ((rgb565 >> 8) & 0xFF).astype(np.uint8)
            packed[1::2] = (rgb565 & 0xFF).astype(np.uint8)
            return packed.tolist()
        buf = []
        for i in range(0, len(raw), 3):
            r, g, b = raw[i], raw[i + 1], raw[i + 2]
            rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            buf.append((rgb565 >> 8) & 0xFF)
            buf.append(rgb565 & 0xFF)
        return buf

    def _draw_battery(self, draw: ImageDraw.ImageDraw):
        """Draw battery percentage and status in top-right corner (small). Always draws something."""
        self._draw_battery_text(draw, self._battery_font, (120, 120, 120), self._pad_y)

    def _draw_battery_text(
        self,
        draw: ImageDraw.ImageDraw,
        font: ImageFont.FreeTypeFont,
        fill: tuple[int, int, int],
        y: int,
    ):
        pct, status = _read_battery()
        if pct is not None:
            if status == "Charging":
                label = f"↑{pct}%"
            elif status == "Full":
                label = "100%"
            else:
                label = f"{pct}%"
        else:
            label = "—"  # No battery detected; show placeholder so corner is visible
        tw = font.getlength(label)
        x = self._width - tw - self._pad_x
        draw.text((x, y), label, font=font, fill=fill)

    def _draw(self, image: Image.Image):
        buf = self._image_to_rgb565(image)
        with self._draw_lock:
            self.board.draw_image(0, 0, self._width, self._height, buf)

    def _prepare_fullscreen_image(self, image_path: str) -> Image.Image:
        image = Image.open(image_path).convert("RGB")
        img_w, img_h = image.size
        screen_ratio = self._width / self._height
        img_ratio = img_w / img_h if img_h else screen_ratio
        if img_ratio > screen_ratio:
            new_w = int(img_h * screen_ratio)
            left = max(0, (img_w - new_w) // 2)
            image = image.crop((left, 0, left + new_w, img_h))
        else:
            new_h = int(img_w / screen_ratio) if screen_ratio else img_h
            top = max(0, (img_h - new_h) // 2)
            image = image.crop((0, top, img_w, top + new_h))
        return image.resize((self._width, self._height), Image.LANCZOS)

    def _paste_sprite_overlay(self, base: Image.Image, sprite: Image.Image, xy: tuple[int, int]) -> None:
        overlay = sprite.convert("RGBA")
        overlay.putdata(
            [
                (r, g, b, 0 if (r, g, b) == (0, 0, 0) else 255)
                for (r, g, b, _a) in overlay.getdata()
            ]
        )
        base.paste(overlay, xy, overlay)

    def _contrasting_scene_color(self, color: tuple[int, int, int]) -> tuple[int, int, int]:
        if sum(color) / 3 > 150:
            return tuple(max(0, int(c * 0.45)) for c in color)
        return color

    def _draw_wifi_indicator(self, draw: ImageDraw.ImageDraw) -> None:
        if _wifi_connected():
            draw.text((self._pad_x, 8), "\u25cf", font=self._idle_battery_font, fill=(0, 150, 70))
        else:
            draw.text((self._pad_x, 8), "\u25cb", font=self._idle_battery_font, fill=(180, 60, 60))

    def _draw_footer_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        *,
        fill: tuple[int, int, int] = IDLE_FOOTER_TEXT,
    ) -> None:
        if not text:
            return
        text = self._truncate_text(text, self._status_sub_font, self._width - self._pad_x * 2)
        tw = self._status_sub_font.getlength(text)
        tx = int((self._width - tw) / 2)
        ty = self._height - STATUS_SUB_FONT_SIZE - 8
        draw.text((tx, ty), text, font=self._status_sub_font, fill=fill)

    def _draw_text_panel(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        *,
        font: ImageFont.FreeTypeFont,
        emoji_font: ImageFont.FreeTypeFont | None,
        box: tuple[int, int, int, int],
        text_fill: tuple[int, int, int],
        panel_fill: tuple[int, int, int] = SCENE_PANEL_FILL,
        outline: tuple[int, int, int] = SCENE_PANEL_STROKE,
    ) -> None:
        left, top, right, bottom = box
        draw.rounded_rectangle(box, radius=14, fill=panel_fill, outline=outline, width=2)
        inner_w = right - left - 20
        line_h = int(font.size) + 4
        max_lines = max(1, (bottom - top - 18) // line_h)
        lines = self._wrap_pixels(text, font, inner_w, emoji_font)[:max_lines]
        total_h = len(lines) * line_h
        y = top + max(8, int(((bottom - top) - total_h) / 2))
        for line in lines:
            tw = self._text_width_mixed(line, font, emoji_font) if emoji_font else font.getlength(line)
            x = max(left + 10, int(left + ((right - left) - tw) / 2))
            self._draw_mixed(
                draw,
                (x, y),
                line,
                font,
                emoji_font,
                text_fill,
                max_x=right - 10,
            )
            y += line_h

    def _build_owl_scene(
        self,
        sprite: Image.Image,
        *,
        accent_color: tuple[int, int, int],
        footer_text: str | None = None,
        show_clock: bool = False,
    ) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("RGB", (self._width, self._height), IDLE_BG_COLOR)
        self._paste_sprite_overlay(img, sprite, OWL_SCENE_POS)
        draw = ImageDraw.Draw(img)

        draw.rectangle((0, 0, self._width, ACCENT_BAR_HEIGHT), fill=accent_color)
        draw.rectangle((0, 0, self._width, TOP_PANEL_HEIGHT), fill=IDLE_PANEL_COLOR)
        draw.rectangle((0, self._height - FOOTER_HEIGHT, self._width, self._height), fill=IDLE_FOOTER_COLOR)

        self._draw_battery_text(draw, self._idle_battery_font, IDLE_PRIMARY_TEXT, 6)
        self._draw_wifi_indicator(draw)

        if show_clock:
            now = datetime.now()
            time_str = now.strftime("%H:%M")
            tw = self._idle_clock_font.getlength(time_str)
            tx = int((self._width - tw) / 2)
            ty = 8
            draw.text((tx, ty), time_str, font=self._idle_clock_font, fill=IDLE_PRIMARY_TEXT)

            date_str = now.strftime("%a, %b %d")
            dw = self._status_sub_font.getlength(date_str)
            dx = int((self._width - dw) / 2)
            dy = ty + IDLE_CLOCK_FONT_SIZE + 1
            draw.text((dx, dy), date_str, font=self._status_sub_font, fill=IDLE_SECONDARY_TEXT)

        if footer_text:
            self._draw_footer_text(draw, footer_text)

        return img, draw

    def show_image(self, image_path: str) -> None:
        self.reset_transient_state()
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")
        if self._image_path != image_path or self._image_cache is None:
            self._image_cache = self._prepare_fullscreen_image(image_path)
            self._image_path = image_path
        self._draw(self._image_cache)

    def clear_image(self) -> None:
        self._image_path = None
        self._image_cache = None

    def reset_transient_state(self) -> None:
        """Clear text/image state and stop transient UI animations."""
        had_visual = bool(self._image_path) or bool(self._response_buf)
        self._invalidate_transient_renderers()
        self._stop_animations()
        self.clear_image()
        self._response_buf = ""
        self._cached_paragraphs = []
        self._cached_wrapped = []
        self._last_draw_time = 0.0
        if had_visual and not self._sleeping:
            self.clear()

    def set_status(
        self,
        text: str,
        color: tuple[int, int, int] = (200, 200, 200),
        subtitle: str | None = None,
        accent_color: tuple[int, int, int] | None = None,
    ):
        """Show a status screen: optional accent bar, main text, optional subtitle."""
        self.reset_transient_state()
        img, draw = self._build_owl_scene(
            self._sprite_frames["happy"],
            accent_color=accent_color or IDLE_PANEL_DARK,
            footer_text=subtitle,
        )
        self._draw_text_panel(
            draw,
            text,
            font=self._status_font,
            emoji_font=self._emoji_status,
            box=(16, 92, self._width - 16, 168),
            text_fill=self._contrasting_scene_color(color),
            outline=accent_color or SCENE_PANEL_STROKE,
        )
        self._draw(img)

    def set_idle_screen(self):
        """Draw idle screen with owl mascot, large clock, date, battery, and wifi status."""
        self.reset_transient_state()
        img, _draw = self._build_owl_scene(
            self._sprite_frames["idle"],
            accent_color=IDLE_PANEL_DARK,
            footer_text="Press button to talk",
            show_clock=True,
        )
        self._draw(img)
    # ── Sprite-based animated character ─────────────────────────────

    _ACCENT_COLORS = {
        "listening": (60, 140, 255),
        "thinking": (255, 220, 50),
        "talking": (0, 200, 100),
        "done": (0, 160, 80),
    }

    def start_character(self, state: str = "done", tts_player=None):
        """Start the animated character loop. tts_player is used for RMS mouth sync."""
        self._stop_animations()
        generation = self._claim_transient_renderer("character")
        self._char_state = state
        self._char_tts = tts_player
        self._char_stop = threading.Event()
        t = threading.Thread(target=self._character_loop, args=(generation,), daemon=True)
        t.start()
        self._char_thread = t

    def set_character_state(self, state: str):
        self._char_state = state

    def stop_character(self):
        if hasattr(self, "_char_stop"):
            self._char_stop.set()
        if hasattr(self, "_char_thread"):
            self._char_thread.join(timeout=2)

    def _character_loop(self, generation: int):
        tick = 0
        while not self._char_stop.is_set():
            if not self._transient_generation_active(generation):
                break
            state = self._char_state
            tts = getattr(self, "_char_tts", None)

            # Select sprite frame key
            if state == "talking":
                mouth = tts.get_mouth_shape() if tts else -1
                key = f"talk{mouth}" if mouth >= 0 else "talk0"
            elif state == "listening":
                key = "listen"
            elif state == "thinking":
                key = "think1" if (tick // 15) % 2 == 0 else "think2"
            elif state == "done":
                key = "happy"
            else:
                key = "idle"

            # Blink every ~4 s — skip for listening (attentive) and done (happy eyes)
            if (tick % 40) in (0, 1) and state not in ("listening", "done"):
                key += "_blink"

            sprite = self._sprite_frames.get(key, self._sprite_frames["idle"])
            footer_label = {
                "listening": "Listening…",
                "thinking": "Thinking…",
                "talking": "Speaking…",
                "done": "Ready",
            }.get(state, "")
            img, draw = self._build_owl_scene(
                sprite,
                accent_color=self._ACCENT_COLORS.get(state, IDLE_PANEL_DARK),
                footer_text=footer_label,
            )

            # Subtitle: single line showing the current fragment being spoken
            sub_text = ""
            if tts:
                sub_text = tts.current_text
            if sub_text:
                sub_text = _clean_markdown(sub_text)
                self._draw_text_panel(
                    draw,
                    sub_text,
                    font=self._response_font,
                    emoji_font=self._emoji_response,
                    box=(16, self._height - FOOTER_HEIGHT - 42, self._width - 16, self._height - FOOTER_HEIGHT - 6),
                    text_fill=IDLE_PRIMARY_TEXT,
                )

            if not self._transient_generation_active(generation):
                break
            self._draw(img)

            tick += 1
            self._char_stop.wait(timeout=0.1)
        self._clear_transient_kind_if_current(generation)

    def _stop_animations(self):
        """Stop any running animation (spinner or character)."""
        self.stop_spinner()
        self.stop_character()

    def start_spinner(self, label: str = "Thinking", color: tuple[int, int, int] = (255, 220, 50)):
        self._stop_animations()
        generation = self._claim_transient_renderer("spinner")
        self._spinner_stop = threading.Event()
        t = threading.Thread(target=self._spin_loop, args=(generation, label, color), daemon=True)
        t.start()
        self._spinner_thread = t

    def stop_spinner(self):
        if hasattr(self, "_spinner_stop"):
            self._spinner_stop.set()
        if hasattr(self, "_spinner_thread"):
            self._spinner_thread.join(timeout=2)

    def _spin_loop(self, generation: int, label: str, color: tuple[int, int, int]):
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        i = 0
        while not self._spinner_stop.is_set():
            if not self._transient_generation_active(generation):
                break
            text = f"{frames[i]}  {label}"
            sprite = self._sprite_frames["think1" if (i % 2 == 0) else "think2"]
            img, draw = self._build_owl_scene(
                sprite,
                accent_color=color,
                footer_text="Getting answer…",
            )
            self._draw_text_panel(
                draw,
                text,
                font=self._status_font,
                emoji_font=self._emoji_status,
                box=(18, 96, self._width - 18, 156),
                text_fill=self._contrasting_scene_color(color),
                outline=color,
            )
            if not self._transient_generation_active(generation):
                break
            self._draw(img)
            i = (i + 1) % len(frames)
            self._spinner_stop.wait(timeout=0.12)
        self._clear_transient_kind_if_current(generation)

    def set_response_text(self, text: str):
        """Draw full wrapped response text, scrolled to bottom."""
        self.reset_transient_state()
        self._response_buf = text
        self._render_response(force=True)

    def append_response(self, delta: str):
        """Append a streaming delta and redraw (throttled)."""
        if self.is_showing_image():
            self.clear_image()
        was_empty = not self._response_buf
        self._response_buf += delta
        # First token: show immediately; later tokens throttled by _min_draw_interval
        self._render_response(force=was_empty)

    def _render_response(self, force: bool = False):
        now = time.monotonic()
        if not force and (now - self._last_draw_time) < self._min_draw_interval:
            return
        self._last_draw_time = now

        img = Image.new("RGB", (self._width, self._height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.rectangle((0, 0, self._width, ACCENT_BAR_HEIGHT), fill=(0, 160, 80))

        line_spacing = 4
        usable_w = self._width - self._pad_x * 2
        content_top = self._pad_y + ACCENT_BAR_HEIGHT + 4
        content_bottom = self._height - self._pad_y

        clean = _clean_markdown(self._response_buf)
        paragraphs = clean.split("\n")

        first_changed = len(paragraphs)
        for i, para in enumerate(paragraphs):
            stripped = para.strip() if para.strip() else ""
            if i >= len(self._cached_paragraphs) or self._cached_paragraphs[i] != stripped:
                first_changed = i
                break

        new_cached_paras: list[str] = []
        new_cached_wrapped: list[list[str]] = []
        all_lines: list[str] = []

        for i, para in enumerate(paragraphs):
            stripped = para.strip()
            if i < first_changed:
                new_cached_paras.append(self._cached_paragraphs[i])
                new_cached_wrapped.append(self._cached_wrapped[i])
                all_lines.extend(self._cached_wrapped[i])
            else:
                if not stripped:
                    wrapped = [""]
                else:
                    wrapped = self._wrap_pixels(stripped, self._response_font, usable_w, self._emoji_response)
                new_cached_paras.append(stripped)
                new_cached_wrapped.append(wrapped)
                all_lines.extend(wrapped)

        self._cached_paragraphs = new_cached_paras
        self._cached_wrapped = new_cached_wrapped

        line_h = RESPONSE_FONT_SIZE + line_spacing
        max_visible = (content_bottom - content_top) // line_h
        truncated = len(all_lines) > max_visible

        if truncated:
            all_lines = all_lines[-max_visible:]

        text_color = (230, 235, 240)
        y = content_top
        for line in all_lines:
            if not line:
                y += line_h // 2
                continue
            self._draw_mixed(
                draw, (self._pad_x, y), line,
                self._response_font, self._emoji_response, text_color,
                max_x=self._width - self._pad_x,
            )
            y += line_h

        if truncated:
            indicator = "\u2191"
            iw = self._battery_font.getlength(indicator)
            draw.text(
                (self._width - iw - self._pad_x, content_top),
                indicator, font=self._battery_font, fill=(80, 80, 80),
            )

        self._draw_battery(draw)
        self._draw(img)

    def flush_response(self):
        """Force a final redraw of buffered response text."""
        self._render_response(force=True)

    def update_text(self, text: str):
        """Legacy: draw centred text."""
        self.set_status(text, color=(255, 255, 255))

    def clear(self):
        with self._draw_lock:
            # Use the same full-frame draw path as the rest of the UI so stale
            # pixels from fullscreen images cannot survive in clipped strips.
            self.board.draw_image(0, 0, self._width, self._height, self._blank_buf)

    def set_backlight(self, level: int):
        self.board.set_backlight(level)

    def cleanup(self):
        try:
            self.clear()
            self.board.set_backlight(0)
        except Exception:
            pass
        try:
            self.board.cleanup()
        except Exception:
            pass
