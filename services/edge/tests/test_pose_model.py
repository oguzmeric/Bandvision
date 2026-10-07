import re

from bantvision.core import pose_model as pm


def test_pose_model_constants() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", pm.MODEL_SHA256)
    assert pm.MODEL_URL.startswith("https://github.com/oguzmeric/Bandvision/releases/download/models-v1/")
    assert pm.MODEL_URL.endswith(pm.MODEL_NAME) and pm.INPUT_SIZE == 256
