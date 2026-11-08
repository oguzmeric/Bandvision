"""YOLOX-S yangın/duman deneyi (YOLOX `Exp` kuralı; yalnız ayrı eğitim ortamında çalışır, uygulama ve testler yüklemez).

    python tools/train.py -f <bu dosya> -d 1 -b 16 --fp16 -o -c yolox_s.pth      (YOLOX kaynak klasöründe)

Veri: `prepare_data.py` çıktısı; kök `FIRE_DATA_DIR` ortam değişkeni (varsayılan `fire_data`) ve altında
`annotations/instances_{train,val,test}.json`. COCO `file_name` mutlak yol olduğu için YOLOX'un `train2017` / `val2017`
klasör adları kullanılmaz. Sınıflar 2: 0 fire, 1 smoke (COCO kimliği 1, 2). Giriş 640 (uygulama `core/yolox.py` INPUT).
`FIRE_EPOCHS` (varsayılan 100) ve `FIRE_EVAL_TEST=1` (değerlendirmeyi doğrulama yerine test bölümünde yap) isteğe bağlı.
"""
from __future__ import annotations

import os

from yolox.exp import Exp as BaseExp


class Exp(BaseExp):
    def __init__(self) -> None:
        super().__init__()
        self.depth = 0.33                               # YOLOX-S
        self.width = 0.50
        self.num_classes = 2
        self.input_size = (640, 640)
        self.test_size = (640, 640)
        self.exp_name = os.path.splitext(os.path.basename(__file__))[0]

        self.data_dir = os.environ.get("FIRE_DATA_DIR", "fire_data")
        self.train_ann = "instances_train.json"
        self.val_ann = "instances_test.json" if os.environ.get("FIRE_EVAL_TEST") == "1" else "instances_val.json"
        self.test_ann = "instances_test.json"

        self.max_epoch = int(os.environ.get("FIRE_EPOCHS", "100"))
        self.no_aug_epochs = 15
        self.warmup_epochs = 5
        self.eval_interval = 5
        self.data_num_workers = 4
        self.test_conf = 0.01
        self.nmsthre = 0.45                             # uygulamadaki NMS (core/fire_model.py NMS_IOU)
