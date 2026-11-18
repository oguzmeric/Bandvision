from __future__ import annotations

import importlib.util
import io
import pathlib
import sys
import wave

import pytest

# numpy'li araç: CI'da edge bağımlılıklarıyla koşar, yalnız jsonschema kurulu contracts işinde atlanır
np = pytest.importorskip("numpy")

TOOLS = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("make_alarm_sounds", TOOLS / "make_alarm_sounds.py")
mas = importlib.util.module_from_spec(spec)                     # type: ignore[arg-type]
sys.modules["make_alarm_sounds"] = mas                          # dataclass modülü sys.modules'ta arar
spec.loader.exec_module(mas)                                    # type: ignore[union-attr]

NAMES = ["Klasik bip", "Siren", "Hızlı siren", "Çan", "Uyarı düdüğü", "Nabız", "Yükselen ton", "İkili korna",
         "Sonar", "Yumuşak gong"]


def test_catalog_has_ten_sounds_in_spec_order() -> None:
    assert [s.id for s in mas.SOUNDS] == [f"alarm-{i:02d}" for i in range(1, 11)]
    assert [s.name for s in mas.SOUNDS] == NAMES


def test_writes_ten_valid_wav_files(tmp_path: pathlib.Path) -> None:
    paths = mas.write_all(tmp_path)
    assert sorted(p.name for p in paths) == [f"alarm-{i:02d}.wav" for i in range(1, 11)]
    for p in paths:
        data = p.read_bytes()
        assert data[:4] == b"RIFF" and data[8:12] == b"WAVE", p.name
        with wave.open(io.BytesIO(data)) as w:
            assert w.getframerate() == 22050, p.name
            assert w.getnchannels() == 1, p.name
            assert w.getsampwidth() == 2, p.name
            seconds = w.getnframes() / w.getframerate()
            assert 1.0 <= seconds <= 2.0, (p.name, seconds)
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32767
        peak = float(np.abs(pcm).max())
        assert 10 ** (-1.5 / 20) <= peak <= 10 ** (-0.5 / 20), (p.name, peak)      # ≈ −1 dBFS
        # yumuşak giriş/çıkış: ilk ve son örnek sessize yakın (tık sesi yok)
        assert abs(pcm[0]) < 0.01 and abs(pcm[-1]) < 0.01, p.name


def test_two_runs_give_identical_bytes(tmp_path: pathlib.Path) -> None:
    a = {p.name: p.read_bytes() for p in mas.write_all(tmp_path / "a")}
    b = {p.name: p.read_bytes() for p in mas.write_all(tmp_path / "b")}
    assert a == b


def test_sounds_are_distinct() -> None:
    """Her ses ötekilerden açıkça ayrı: uzunluk ya da tayf (baskın frekans) farklı"""
    spectra = []
    for s in mas.SOUNDS:
        x = mas.synth(s.id)
        mag = np.abs(np.fft.rfft(x, n=1 << 16))
        spectra.append(mag / np.linalg.norm(mag))
    for i in range(len(spectra)):
        for j in range(i + 1, len(spectra)):
            similarity = float(spectra[i] @ spectra[j])
            assert similarity < 0.9, (mas.SOUNDS[i].name, mas.SOUNDS[j].name, similarity)


def test_committed_files_match_generator() -> None:
    """Panelle gelen WAV'lar betiğin bugünkü çıktısıdır (betik değişip dosyalar unutulmasın)"""
    out = TOOLS.parent / "apps" / "dashboard" / "public" / "sounds"
    for s in mas.SOUNDS:
        assert (out / f"{s.id}.wav").read_bytes() == mas.wav_bytes(mas.synth(s.id)), s.id
