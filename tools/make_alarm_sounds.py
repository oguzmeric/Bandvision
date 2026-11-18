"""Panelin 10 alarm sesini sentezler: apps/dashboard/public/sounds/alarm-01.wav … alarm-10.wav.

Sesler tamamen matematikle üretilir (kayıt ya da örnek yok: lisans sorunu yok, rastgelelik yok, aynı girdiyle aynı baytlar).
Biçim: 22 050 Hz, tek kanal, 16 bit PCM, 1–2 sn; tepe ≈ −1 dBFS, başta ve sonda kısa yumuşak giriş/çıkış (tık sesi yok).

Kullanım:  python tools/make_alarm_sounds.py [çıktı klasörü]
"""
from __future__ import annotations

import io
import pathlib
import sys
import wave
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

RATE = 22050
PEAK = 10 ** (-1 / 20)            # −1 dBFS
FADE_IN_S = 0.005
FADE_OUT_S = 0.02
OUT_DIR = pathlib.Path(__file__).resolve().parents[1] / "apps" / "dashboard" / "public" / "sounds"

Signal = npt.NDArray[np.float64]


def _t(seconds: float) -> Signal:
    return np.arange(round(seconds * RATE), dtype=np.float64) / RATE


def _phase(freq: Signal) -> Signal:
    """Değişen frekanstan (Hz, örnek başına) sürekli faz: süpürmede kırılma olmaz"""
    return 2 * np.pi * np.cumsum(freq) / RATE


def _ramp(n: int, attack_s: float, release_s: float) -> Signal:
    """Kısa doğrusal giriş/çıkış zarfı (parçanın kenarında tık olmasın)"""
    env = np.ones(n)
    a = max(1, round(attack_s * RATE))
    r = max(1, round(release_s * RATE))
    env[:a] *= np.linspace(0, 1, a)
    env[n - r:] *= np.linspace(1, 0, r)
    return env


def _harmonic(phase: Signal, weights: list[float]) -> Signal:
    """Fazdan sınırlı harmonikli dalga (kare/testere benzeri, sert örtüşme yok)"""
    return sum((w * np.sin((k + 1) * phase) for k, w in enumerate(weights)), np.zeros_like(phase))


def _place(total_s: float, parts: list[tuple[float, Signal]]) -> Signal:
    out = np.zeros(round(total_s * RATE))
    for start, x in parts:
        i = round(start * RATE)
        out[i:i + len(x)] += x[: len(out) - i]
    return out


def _tone(freq: float, seconds: float, weights: list[float] | None = None, attack: float = 0.005,
          release: float = 0.02) -> Signal:
    t = _t(seconds)
    ph = 2 * np.pi * freq * t
    x = _harmonic(ph, weights) if weights else np.sin(ph)
    return x * _ramp(len(t), attack, release)


def classic_beep() -> Signal:
    """Klasik bip: 1 kHz'lik üç kısa bip"""
    beep = _tone(1000, 0.14, [1.0, 0, 0.12])
    return _place(1.0, [(0.0, beep), (0.25, beep), (0.5, beep)])


def siren() -> Signal:
    """Siren: yavaş inip çıkan (600 → 1200 → 600 Hz) tek uluma"""
    t = _t(1.6)
    freq = 900 - 300 * np.cos(2 * np.pi * t / 1.6)
    return _harmonic(_phase(freq), [1.0, 0.35, 0.18, 0.08])


def fast_siren() -> Signal:
    """Hızlı siren: saniyede 6 kez 700 ↔ 1500 Hz çırpınan (yelp) siren"""
    t = _t(1.5)
    freq = 1100 + 400 * np.sin(2 * np.pi * 6 * t)
    return _harmonic(_phase(freq), [1.0, 0.3, 0.15])


def _struck(t: Signal, partials: list[tuple[float, float, float]]) -> Signal:
    """Vurmalı ses: (frekans, genlik, sönüm süresi sn) kısmileri"""
    return sum((a * np.sin(2 * np.pi * f * t) * np.exp(-t / d) for f, a, d in partials), np.zeros_like(t))


def bell() -> Signal:
    """Çan: harmonik olmayan kısmilerle iki vuruş"""
    partials = [(660, 1.0, 0.6), (1320, 0.5, 0.4), (1822, 0.35, 0.3), (3564, 0.2, 0.15), (5874, 0.1, 0.08)]
    strike = _struck(_t(1.0), partials) * _ramp(round(1.0 * RATE), 0.002, 0.05)
    return _place(1.8, [(0.0, strike), (0.8, strike)])


def whistle() -> Signal:
    """Uyarı düdüğü: titreşimli (vibrato) tiz düdük, iki öttürme"""
    def blast(seconds: float) -> Signal:
        t = _t(seconds)
        freq = 2800 + 60 * np.sin(2 * np.pi * 7 * t)
        return np.sin(_phase(freq)) * _ramp(len(t), 0.02, 0.04)
    return _place(1.4, [(0.0, blast(0.45)), (0.6, blast(0.75))])


def pulse() -> Signal:
    """Nabız: alçak tonda saniyede dört yumuşak darbe"""
    t = _t(1.5)
    tone = np.sin(2 * np.pi * 520 * t) + 0.25 * np.sin(2 * np.pi * 1040 * t)
    env = np.sin(np.pi * ((t * 4) % 1.0)) ** 2
    return tone * env


def rising_tone() -> Signal:
    """Yükselen ton: 300 → 1800 Hz üstel süpürme"""
    t = _t(1.6)
    freq = 300 * (1800 / 300) ** (t / 1.6)
    return _harmonic(_phase(freq), [1.0, 0.2])


def dual_horn() -> Signal:
    """İkili korna: iki tonlu (370 + 466 Hz) kalın korna, iki kez"""
    weights = [1.0, 0.6, 0.45, 0.3, 0.2, 0.12, 0.08]
    honk = _tone(370, 0.5, weights, 0.015, 0.04) + _tone(466, 0.5, weights, 0.015, 0.04)
    return _place(1.3, [(0.0, honk), (0.7, honk)])


def sonar() -> Signal:
    """Sonar: uzun sönümlü 1,2 kHz ping ve daha sessiz yankısı"""
    ping = _struck(_t(1.0), [(1200, 1.0, 0.25), (2400, 0.08, 0.1)]) * _ramp(round(1.0 * RATE), 0.003, 0.05)
    return _place(1.8, [(0.0, ping), (0.75, 0.35 * ping)])


def soft_gong() -> Signal:
    """Yumuşak gong: alçak (110 Hz), yavaş açılan, hafif dalgalanan uzun sönüm"""
    t = _t(2.0)
    partials = [(110, 1.0, 0.9), (111.5, 0.6, 0.9), (163, 0.5, 0.6), (220, 0.4, 0.5), (278, 0.3, 0.4), (341, 0.2, 0.3)]
    attack = 1 - np.exp(-t / 0.03)
    return _struck(t, partials) * attack


@dataclass(frozen=True)
class Sound:
    id: str
    name: str
    make: Callable[[], Signal]


SOUNDS: list[Sound] = [
    Sound("alarm-01", "Klasik bip", classic_beep),
    Sound("alarm-02", "Siren", siren),
    Sound("alarm-03", "Hızlı siren", fast_siren),
    Sound("alarm-04", "Çan", bell),
    Sound("alarm-05", "Uyarı düdüğü", whistle),
    Sound("alarm-06", "Nabız", pulse),
    Sound("alarm-07", "Yükselen ton", rising_tone),
    Sound("alarm-08", "İkili korna", dual_horn),
    Sound("alarm-09", "Sonar", sonar),
    Sound("alarm-10", "Yumuşak gong", soft_gong),
]


def synth(sound_id: str) -> Signal:
    """Sesin örnekleri (−1…1): tepe ≈ −1 dBFS, baştan ve sondan yumuşak giriş/çıkış"""
    sound = next(s for s in SOUNDS if s.id == sound_id)
    x = sound.make().astype(np.float64)
    x = x * _ramp(len(x), FADE_IN_S, FADE_OUT_S)
    return x * (PEAK / float(np.abs(x).max()))


def wav_bytes(x: Signal) -> bytes:
    pcm = np.round(np.clip(x, -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def write_all(out_dir: pathlib.Path = OUT_DIR) -> list[pathlib.Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for s in SOUNDS:
        p = out_dir / f"{s.id}.wav"
        p.write_bytes(wav_bytes(synth(s.id)))
        paths.append(p)
    return paths


def main(argv: list[str]) -> int:
    out = pathlib.Path(argv[0]) if argv else OUT_DIR
    for p in write_all(out):
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
