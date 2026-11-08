"""Eğitilmiş YOLOX-S yangın/duman modelini ONNX'e çevirir ve uygulamanın beklediği biçimi denetler.

    python tools/fire_train/export.py --yolox YOLOX-KAYNAĞI --ckpt best_ckpt.pth [--out fire_smoke_v1.onnx]

Eğitim ortamında çalışır (PyTorch + YOLOX kaynağı; ana uygulama ortamına kurulmaz). YOLOX'un kendi `tools/export_onnx.py`
betiğini `exps/fire_yolox_s.py` deneyiyle çağırır: opset 11, kod çözme modelin içinde YOK (`--decode_in_inference`
verilmez; ızgara çözme ve NMS uygulamada, core/yolox.py). Sonra onnxruntime ile sıfır girişte bir kez çalıştırır ve
çıktı biçimini denetler: giriş `[1, 3, 640, 640]`, çıkış `[1, 8400, 7]` = (cx, cy, w, h, nesnelik, fire, smoke). En son
SHA-256'yı yazdırır; yayımlanırsa (kullanıcı onayıyla) `core/fire_model.py` `FIRE_MODEL_URL` / `FIRE_MODEL_SHA256` bu
değerle doldurulur. Model dosyası depoya girmez. Çıkış kodu: 0 tamam, 1 denetim başarısız, 2 girdi hatası.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import subprocess
import sys
from collections.abc import Sequence

HERE = pathlib.Path(__file__).resolve().parent
EXP = HERE / "exps" / "fire_yolox_s.py"
MODEL_NAME = "fire_smoke_v1.onnx"
INPUT = 640
NUM_CLASSES = 2
OPSET = 11
ANCHORS = sum((INPUT // s) ** 2 for s in (8, 16, 32))        # 6400 + 1600 + 400 = 8400
EXPECTED_INPUT = (1, 3, INPUT, INPUT)
EXPECTED_OUTPUT = (1, ANCHORS, 5 + NUM_CLASSES)


def export_command(python: str, yolox_dir: pathlib.Path, ckpt: pathlib.Path, out: pathlib.Path,
                   exp: pathlib.Path = EXP) -> list[str]:
    """YOLOX `tools/export_onnx.py` komutu (kod çözmesiz, onnxsim'siz, opset 11, toplu iş 1). Komut `cwd=yolox_dir` ile
    çalıştığından yollar mutlak verilmelidir (`main` çözer)."""
    return [python, str(yolox_dir / "tools" / "export_onnx.py"), "-f", str(exp), "-c", str(ckpt),
            "--output-name", str(out), "-o", str(OPSET), "--batch-size", "1", "--no-onnxsim"]


def check_shapes(inp: Sequence[object], out: Sequence[object]) -> str | None:
    """Giriş/çıkış biçimi uygulamanınkiyle aynı mı? Değilse Türkçe neden."""
    if tuple(inp) != EXPECTED_INPUT:
        return f"Giriş biçimi {list(inp)}, beklenen {list(EXPECTED_INPUT)}"
    if tuple(out) != EXPECTED_OUTPUT:
        return (f"Çıkış biçimi {list(out)}, beklenen {list(EXPECTED_OUTPUT)} (2 sınıf, kod çözmesiz ham ızgara; "
                "--decode_in_inference verilmemeli)")
    return None


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_onnx(path: pathlib.Path) -> tuple[list[object], list[object]]:
    """onnxruntime (işlemci) ile sıfır girişte bir kez çalıştırır; (bildirilen giriş biçimi, gerçek çıkış biçimi)."""
    import numpy as np
    import onnxruntime as ort

    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    i = sess.get_inputs()[0]
    out = sess.run(None, {i.name: np.zeros(EXPECTED_INPUT, np.float32)})[0]
    return list(i.shape), list(out.shape)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="YOLOX-S yangın/duman → ONNX (opset 11, kod çözmesiz) + denetim")
    ap.add_argument("--yolox", help="YOLOX kaynak klasörü (tools/export_onnx.py içerir)")
    ap.add_argument("--ckpt", help="eğitilmiş ağırlık (ör. YOLOX_outputs/fire_yolox_s/best_ckpt.pth)")
    ap.add_argument("--out", default=MODEL_NAME, help=f"çıkış dosyası (varsayılan {MODEL_NAME})")
    ap.add_argument("--check-only", action="store_true", help="çevirme yapma; var olan --out dosyasını denetle")
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out).resolve()                 # YOLOX cwd=yolox_dir ile çalışır: göreli yollar buraya göre
    if not a.check_only:
        if not a.yolox or not a.ckpt:
            print("Hata: --yolox ve --ckpt gerekli (ya da --check-only)", file=sys.stderr)
            return 2
        yolox_dir, ckpt = pathlib.Path(a.yolox).resolve(), pathlib.Path(a.ckpt).resolve()
        if not (yolox_dir / "tools" / "export_onnx.py").is_file() or not ckpt.is_file():
            print("Hata: YOLOX kaynağı (tools/export_onnx.py) ya da ağırlık dosyası bulunamadı", file=sys.stderr)
            return 2
        cmd = export_command(sys.executable, yolox_dir, ckpt, out)
        print("Çalıştırılıyor:", " ".join(cmd))
        if subprocess.run(cmd, cwd=yolox_dir, check=False).returncode != 0:
            print("Hata: YOLOX dışa aktarımı başarısız", file=sys.stderr)
            return 1
    if not out.is_file():
        print(f"Hata: model dosyası yok: {out.name}", file=sys.stderr)
        return 2
    inp, shape = run_onnx(out)
    problem = check_shapes(inp, shape)
    if problem:
        print(f"Denetim BAŞARISIZ: {problem}", file=sys.stderr)
        return 1
    print(f"Denetim tamam: giriş {inp}, çıkış {shape}")
    print(f"SHA-256: {sha256_file(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
