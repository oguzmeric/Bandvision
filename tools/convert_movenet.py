"""MoveNet SinglePose Thunder (Google, Apache-2.0) → ONNX, orijinal modelle eşdeğerlik doğrulaması.

Kullanım (ayrı ortamda: tensorflow, kagglehub, tf2onnx, onnxruntime, numpy, opencv-python-headless):
  python tools/convert_movenet.py --out movenet_thunder.onnx [--video yerel.mp4] [--opset 13]
Kaynak: Kaggle Models `google/movenet/tensorFlow2/singlepose-thunder`, sürüm 4
  (https://www.kaggle.com/models/google/movenet/tensorFlow2/singlepose-thunder/4); TF Hub `google/movenet/singlepose/thunder/4`
  modelinin devamıdır (tfhub.dev artık yanıt vermiyor). SavedModel, imza `serving_default`: girdi "input" int32 1×256×256×3
  (RGB, 0-255), çıkış "output_0" 1×1×17×3 = y, x, güven (girdiye göre normalize).
Doğrulama: rastgele, sentetik "çöp adam" ve (verilirse) videodan alınan 256×256 karelerde TF ve ONNX çıktıları arasındaki en
büyük fark < 0,01 olmalı; değilse çıkış kodu 1. Çıktının SHA-256'sı yazdırılır (core/pose_model.py'ye girer).
Çalıştırma yeri: GitHub Actions `.github/workflows/models.yml` (TensorFlow yerel geliştirme makinelerinde şart değil).
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import subprocess
import sys

import numpy as np

KAGGLE_HANDLE = "google/movenet/tensorFlow2/singlepose-thunder/4"
KAGGLE_URL = "https://www.kaggle.com/models/google/movenet/tensorFlow2/singlepose-thunder/4"
SIGNATURE = "serving_default"
TOLERANCE = 0.01


def stick_figure() -> np.ndarray:
    """Sentetik kare: gürültülü arka planda çöp adam (RGB uint8). Rastgele gürültüden daha anlamlı bir eklem haritası verir."""
    import cv2

    rng = np.random.default_rng(1)
    img = np.clip(rng.normal(110, 12, (256, 256, 3)), 0, 255).astype(np.uint8)
    skin, cloth = (225, 185, 160), (40, 70, 160)
    cv2.circle(img, (128, 52), 18, skin, -1)
    for a, b in [((128, 72), (128, 150)), ((128, 84), (92, 120)), ((92, 120), (84, 160)), ((128, 84), (164, 120)),
                 ((164, 120), (172, 160)), ((128, 150), (108, 200)), ((108, 200), (106, 246)), ((128, 150), (148, 200)),
                 ((148, 200), (150, 246))]:
        cv2.line(img, a, b, cloth, 9)
    return img


def frames(video: str | None, n: int = 8) -> list[np.ndarray]:
    rng = np.random.default_rng(0)
    out = [rng.integers(0, 256, (256, 256, 3), dtype=np.uint8) for _ in range(n)]
    out.append(stick_figure())
    out.append(np.zeros((256, 256, 3), dtype=np.uint8))
    out.append(np.full((256, 256, 3), 255, dtype=np.uint8))
    if video:
        import cv2

        cap = cv2.VideoCapture(video)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        for k in range(n):
            cap.set(cv2.CAP_PROP_POS_FRAMES, k * total // n)
            ok, f = cap.read()
            if ok:
                f = cv2.resize(f, (256, 256))[:, :, ::-1]
                out.append(np.ascontiguousarray(f))
        cap.release()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--video", default=None)
    ap.add_argument("--opset", type=int, default=13)
    a = ap.parse_args()
    import kagglehub
    import onnxruntime as ort
    import tensorflow as tf

    saved = kagglehub.model_download(KAGGLE_HANDLE)
    print(f"kaynak: {KAGGLE_URL}\nSavedModel: {saved}")
    sig = tf.saved_model.load(saved).signatures[SIGNATURE]
    in_specs = sig.structured_input_signature[1]
    in_key, in_spec = next(iter(in_specs.items()))
    print(f"TF girdi: {in_key} {in_spec.dtype.name} {list(in_spec.shape)}")
    for k, v in sig.structured_outputs.items():
        print(f"TF çıkış: {k} {v.dtype.name} {list(v.shape)}")
    out_key = "output_0" if "output_0" in sig.structured_outputs else next(iter(sig.structured_outputs))

    subprocess.run([sys.executable, "-m", "tf2onnx.convert", "--saved-model", saved, "--signature_def", SIGNATURE,
                    "--opset", str(a.opset), "--output", a.out], check=True)

    sess = ort.InferenceSession(a.out, providers=["CPUExecutionProvider"])
    for t in sess.get_inputs():
        print(f"ONNX girdi: {t.name} {t.type} {t.shape}")
    for t in sess.get_outputs():
        print(f"ONNX çıkış: {t.name} {t.type} {t.shape}")
    name = sess.get_inputs()[0].name
    dtype = in_spec.dtype.as_numpy_dtype
    worst = 0.0
    for f in frames(a.video):
        x = f[None].astype(dtype)
        ref = sig(**{in_key: tf.constant(x)})[out_key].numpy()
        got = sess.run(None, {name: x})[0]
        worst = max(worst, float(np.abs(ref - got).max()))
    print(f"en büyük fark: {worst:.6f}")
    if worst >= TOLERANCE:
        print("HATA: ONNX çıktısı orijinalden farklı")
        return 1
    path = pathlib.Path(a.out)
    print(f"girdi adı: {name}; boyut: {path.stat().st_size} bayt")
    print(f"SHA-256: {hashlib.sha256(path.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
