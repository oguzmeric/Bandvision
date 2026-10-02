"""iOS uçtan uca testi için dik (720×1280) kısa bant klibi + beklenen sonuçlar.

Kullanım: python tools/make_ui_test_clip.py   (gerekli: pip install imageio-ffmpeg pillow, services/edge kurulu)

Üretir: apps/ios/BantSayacUITests/ui_test_clip.mp4 ve ui_test_clip.json
  {"count": N, "expectedArea": A, ...}
Klip önce Python referans çekirdeğiyle sayılır; sayı doğru adetle aynı değilse dosya yazılmaz.
iOS testi aynı klibi yumurta profili + bu `expectedArea` ile sayar ve aynı sayıyı bekler (Swift ↔ Python eşdeğerliği).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import pathlib
import random
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "apps" / "ios" / "BantSayacUITests"

_spec = importlib.util.spec_from_file_location("make_test_video", ROOT / "tools" / "make_test_video.py")
assert _spec and _spec.loader
mtv = importlib.util.module_from_spec(_spec)
sys.modules["make_test_video"] = mtv
_spec.loader.exec_module(mtv)

# Dik kare: uygulamadaki kamera görüntüsü portredir; yumurta profili ROI'si (0.05, 0.1, 0.9, 0.8) içinde akış aşağı
mtv.W, mtv.H = 720, 1280
mtv.BELT_X0, mtv.BELT_X1 = 30, 690
mtv.SPEED = 640.0

SEED = 5
EMPTY_SECONDS = 4.0   # ağ testinde RTSP başlangıç gecikmesi + ~1 sn boş bant öğrenmesi için pay


def main() -> int:
    rng = random.Random(SEED)
    eggs = mtv.layout(16, 4, 2, rng, lead_px=mtv.SPEED * EMPTY_SECONDS, gap_lengths=(0.9, 1.5))   # 28 yumurta
    seconds = mtv.leave_time(eggs) + 0.5
    truth = len(eggs)

    with tempfile.TemporaryDirectory() as tmp:
        clip = pathlib.Path(tmp) / "ui_test_clip.mp4"
        mtv.render(clip, eggs, seconds, lambda t: ([], []), SEED)

        sys.path.insert(0, str(ROOT / "services" / "edge"))
        from bantvision import video

        out = pathlib.Path(tmp) / "analiz"
        with contextlib.redirect_stdout(io.StringIO()):
            video.main([str(clip), "--out", str(out), "--no-video", "--preset", "egg", "--direction", "down",
                        "--roi", "0.05,0.1,0.9,0.8", "--bg-range", f"0,{EMPTY_SECONDS - 0.3}"])
        summary = json.loads((out / "ozet.json").read_text(encoding="utf-8"))
        count, area = summary["count"], summary["calibration"]["expectedArea"]
        print(f"klip: {truth} yumurta, {seconds:.1f} sn; Python sayımı {count}, tek ürün alanı {area:.5f}")
        if count != truth:
            print("HATA: Python referansı doğru sayamadı; klip yazılmadı.")
            return 1

        OUT.mkdir(parents=True, exist_ok=True)
        shutil.copy(clip, OUT / "ui_test_clip.mp4")
    meta = {
        "count": truth,
        "expectedArea": area,
        "profile": "egg",
        "roi": [0.05, 0.1, 0.9, 0.8],
        "emptySeconds": EMPTY_SECONDS,
        "seed": SEED,
        "groups": {k: sum(1 for e in eggs if e.kind == k) for k in ("single", "pair_vertical", "pair_side")},
    }
    (OUT / "ui_test_clip.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    size = (OUT / "ui_test_clip.mp4").stat().st_size / 1e6
    print(f"yazıldı: {OUT / 'ui_test_clip.mp4'} ({size:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
