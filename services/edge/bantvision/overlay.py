"""Tanıma tabanlı sayım (§4.10) için video bindirmesi: Giriş · Çıkış paneli, giriş oku, kişi kutuları.

Türkçe karakterler (ı, ş, ç, ğ, İ) OpenCV yazısında çıkmaz; Pillow ve sistem yazı tipiyle çizilir. Pillow ya da
yazı tipi yoksa ASCII'ye çevrilip OpenCV ile yazılır (çıktı yine okunur).
"""
from __future__ import annotations

import functools
import math
import os
import pathlib
from typing import Any

import cv2
import numpy as np

from .core.detect_count import DetectResult, side_function
from .core.profile import Profile
from .core.safety import SafetyResult

# BGR
GREEN, RED, ORANGE, WHITE, DARK = (80, 200, 60), (60, 60, 230), (0, 140, 255), (255, 255, 255), (30, 30, 30)
GRAY = (170, 170, 170)
CYAN = (255, 255, 0)                            # poz güvenlik: iskelet çizgileri

_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
)
_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


@functools.lru_cache(maxsize=16)
def _font(size: int) -> Any:
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    for path in (os.environ.get("BANTVISION_FONT"), *_FONTS):
        if path and pathlib.Path(path).exists():
            return ImageFont.truetype(path, size)
    return None


def text_size(text: str, size: int) -> tuple[int, int]:
    f = _font(size)
    if f is None:
        (w, h), _ = cv2.getTextSize(text.translate(_ASCII), cv2.FONT_HERSHEY_SIMPLEX, size / 30, max(1, size // 14))
        return w, h
    _, _, x1, y1 = f.getbbox(text)
    return x1, y1


def put_text(img: np.ndarray, text: str, org: tuple[int, int], size: int, color: tuple[int, int, int]) -> None:
    """`org`: yazının sol üst köşesi (piksel)."""
    f = _font(size)
    x, y = org
    if f is None:
        cv2.putText(img, text.translate(_ASCII), (x, y + size), cv2.FONT_HERSHEY_SIMPLEX, size / 30, color,
                    max(1, size // 14), cv2.LINE_AA)
        return
    from PIL import Image, ImageDraw

    tw, th = text_size(text, size)
    h, w = img.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + tw + 2), min(h, y + th + 4)
    if x1 <= x0 or y1 <= y0:
        return
    crop = Image.fromarray(np.ascontiguousarray(img[y0:y1, x0:x1, ::-1]))
    ImageDraw.Draw(crop).text((x - x0, y - y0), text, font=f, fill=(color[2], color[1], color[0]))
    img[y0:y1, x0:x1] = np.asarray(crop)[..., ::-1]


def entry_arrow(profile: Profile, w: int, h: int, line: tuple[tuple[float, float], tuple[float, float]]
                ) -> tuple[tuple[int, int], tuple[int, int]]:
    """Çizginin ortasından giriş tarafına bakan ok (piksel)."""
    side_of, _ = side_function(profile, w, h)
    (ax, ay), (bx, by) = line
    mx, my = (ax + bx) / 2, (ay + by) / 2
    dx, dy = (bx - ax) * w, (by - ay) * h
    ln = max(1e-6, math.hypot(dx, dy))
    nx, ny = -dy / ln, dx / ln                          # piksel uzayında çizgiye dik birim
    eps = 0.02
    if side_of(mx + nx * eps * ln / w, my + ny * eps * ln / h) < 0:
        nx, ny = -nx, -ny
    mid = (int(mx * w), int(my * h))
    size = 0.08 * min(w, h)
    return mid, (int(mid[0] + nx * size), int(mid[1] + ny * size))


def draw_detect(frame: np.ndarray, profile: Profile, det: DetectResult | None, entries: int, exits: int,
                ts: float, flash: float, flash_in: bool, labels: dict[int, str], panel: bool = True) -> np.ndarray:
    """`panel=False`: sayaç kutusu çizilmez (canlı panelde sayılar yan tarafta)."""
    h, w = frame.shape[:2]
    s = max(0.6, w / 960)                       # yazı ve çizgiler görüntüyle orantılı (alt akış 640 px'te küçülür)
    th = max(1, round(2 * s))
    if det is not None:
        (ax, ay), (bx, by) = det.line
        pa, pb = (int(ax * w), int(ay * h)), (int(bx * w), int(by * h))
        cv2.line(frame, pa, pb, ORANGE, th * 2, cv2.LINE_AA)
        mid, tip = entry_arrow(profile, w, h, det.line)
        cv2.arrowedLine(frame, mid, tip, ORANGE, th * 2, cv2.LINE_AA, tipLength=0.3)
        put_text(frame, "GİRİŞ", (tip[0] + int(6 * s), tip[1] - int(10 * s)), int(18 * s), ORANGE)
        for t in det.tracks:
            x1, y1, x2, y2 = (int(t.box[0] * w), int(t.box[1] * h), int(t.box[2] * w), int(t.box[3] * h))
            lab = labels.get(t.id)
            col = GRAY if lab == "P" else (GREEN if lab and lab.startswith("G") else (RED if lab else WHITE))
            cv2.rectangle(frame, (x1, y1), (x2, y2), col, th, cv2.LINE_AA)
            if len(t.trail) > 1:
                pts = np.array([[int(px * w), int(py * h)] for px, py in t.trail], np.int32)
                cv2.polylines(frame, [pts], False, col, max(1, th - 1), cv2.LINE_AA)
            tag = lab or f"#{t.id}"
            size = int((22 if lab else 15) * s)
            tw, tht = text_size(tag, size)
            ty = max(0, y1 - tht - int(8 * s))
            cv2.rectangle(frame, (x1, ty), (x1 + tw + int(8 * s), ty + tht + int(8 * s)), col, -1)
            put_text(frame, tag, (x1 + int(4 * s), ty + int(2 * s)), size, DARK)
    if not panel:
        return frame
    # panel: yeni girişte kısa süre yeşil, çıkışta turuncu yanar
    bg = (GREEN if flash_in else ORANGE) if flash > 0 else DARK
    pw, ph = int(380 * s), int(84 * s)
    roi = frame[0:ph, 0:pw]
    roi[:] = (0.25 * roi + 0.75 * np.array(bg, np.float32)).astype(np.uint8)
    put_text(frame, f"Giriş {entries}", (int(14 * s), int(8 * s)), int(36 * s), WHITE)
    put_text(frame, f"Çıkış {exits}", (int(200 * s), int(8 * s)), int(36 * s), WHITE)
    put_text(frame, f"{int(ts // 60):02d}:{ts % 60:04.1f}", (int(14 * s), int(56 * s)), int(15 * s), GRAY)
    return frame


_SKELETON = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14),
             (14, 16), (0, 5), (0, 6)]
_SAFETY_LABELS = {"hands_up": "ELLER YUKARI", "lying": "YERDE"}


def draw_safety(frame: np.ndarray, profile: Profile, r: SafetyResult | None) -> np.ndarray:
    """Poz güvenlik: iskeletler; alarm vermiş (aktif) izin kutusu kırmızı ve etiketli."""
    if r is None:
        return frame
    h, w = frame.shape[:2]
    s = max(0.6, w / 960)
    th = max(1, round(2 * s))
    alarming = {(tid, kind) for tid, kind, _sec, fired in r.active if fired}
    for t in r.tracks:
        kp = r.poses.get(t.id)
        if kp is not None:
            for a, b in _SKELETON:
                if kp[a, 2] >= 0.3 and kp[b, 2] >= 0.3:
                    cv2.line(frame, (int(kp[a, 0]), int(kp[a, 1])), (int(kp[b, 0]), int(kp[b, 1])), CYAN, th,
                             cv2.LINE_AA)
        kinds = sorted(k for (tid, k) in alarming if tid == t.id)
        if kinds:
            x1, y1, x2, y2 = (int(t.box[0] * w), int(t.box[1] * h), int(t.box[2] * w), int(t.box[3] * h))
            cv2.rectangle(frame, (x1, y1), (x2, y2), RED, th * 2, cv2.LINE_AA)
            put_text(frame, " · ".join(_SAFETY_LABELS[k] for k in kinds), (x1, max(0, y1 - int(26 * s))),
                     int(20 * s), RED)
    return frame
