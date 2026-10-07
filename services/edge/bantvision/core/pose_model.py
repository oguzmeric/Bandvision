"""Poz modeli: MoveNet SinglePose Thunder (Google, Apache-2.0), ONNX çevirisi (tools/convert_movenet.py).

GitHub sürümü models-v1'den indirilir, SHA-256 doğrulanır. Kaynak ve lisans: tools/models/MOVENET-NOTICE.md.
Girdi: "input" int32 1×256×256×3 (RGB, 0-255); çıkış: "output_0" float32 1×1×17×3 = (y, x, güven), girdiye göre normalize.
"""
from __future__ import annotations

MODEL_NAME = "movenet_thunder.onnx"
MODEL_URL = "https://github.com/oguzmeric/Bandvision/releases/download/models-v1/movenet_thunder.onnx"
MODEL_SHA256 = "b890b51c6df9a72004c4d41dbfa51a5159a6c07c21ffac668cd958ffff21f018"
INPUT_SIZE = 256
