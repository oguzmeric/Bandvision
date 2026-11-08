"""tools/fire_train araçları: veri hazırlığı (D-Fire/FireNet → COCO), ölçüm (AP, olay düzeyi, kalibrasyon) ve ONNX
denetimi. PyTorch/YOLOX gerekmez; numpy/OpenCV ve bantvision isteyen testler `needs_edge` ile işaretlidir (CI'da edge-core
işinde koşar, contracts işinde atlanır)."""
from __future__ import annotations

import csv
import importlib.util
import json
import pathlib
import struct
import sys
import types
from dataclasses import dataclass
from typing import Any

import pytest

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "fire_train"


def load(name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(f"fire_train_{name}", TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)                 # type: ignore[arg-type]
    sys.modules[spec.name] = mod                                # type: ignore[union-attr]  # dataclass ek açıklamaları
    spec.loader.exec_module(mod)                                # type: ignore[union-attr]
    return mod


prep = load("prepare_data")
ev = load("eval_fire")
ex = load("export")

needs_edge = pytest.mark.skipif(importlib.util.find_spec("cv2") is None, reason="edge bağımlılıkları yok")


def png(path: pathlib.Path, w: int, h: int) -> pathlib.Path:
    """Yalnız başlığı geçerli PNG (boy okuyucu IHDR'ye bakar, görüntüyü çözmez)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    return path


def jpeg(path: pathlib.Path, w: int, h: int) -> pathlib.Path:
    """SOI + APP0 (JFIF) + SOF0 başlıklı JPEG parçası (boy okuyucu SOF'a kadar okur)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, h, w, 3) + b"\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    path.write_bytes(b"\xff\xd8" + app0 + sof0 + b"\xff\xd9")
    return path


def dfire_tree(root: pathlib.Path) -> pathlib.Path:
    """Küçük sahte D-Fire: train'de a (alev + duman + bozuk satır), b (hiçbiri), c (etiketsiz), PublicDataset_p;
    test'te d (tam kare alev)."""
    png(root / "train/images/a.png", 100, 50)
    (root / "train/labels").mkdir(parents=True)
    (root / "train/labels/a.txt").write_text("0 0.5 0.5 0.2 0.4\n1 0.1 0.5 0.4 0.2\nbozuk satır\n7 0.5 0.5 0.1 0.1\n")
    png(root / "train/images/b.png", 100, 50)
    (root / "train/labels/b.txt").write_text("")
    png(root / "train/images/c.png", 100, 50)
    png(root / "train/images/PublicDataset_p.png", 100, 50)
    (root / "train/labels/PublicDataset_p.txt").write_text("1 0.5 0.5 0.5 0.5\n")
    jpeg(root / "test/images/d.jpg", 64, 32)
    (root / "test/labels").mkdir(parents=True)
    (root / "test/labels/d.txt").write_text("1 0.5 0.5 1.0 1.0\n")
    return root


# ---------------------------------------------------------------- prepare_data

def test_class_order_constants() -> None:
    assert prep.CLASSES == ("fire", "smoke")                   # uygulama düzeni (core/fire_model.py)
    assert prep.DFIRE_CLASSES == ("smoke", "fire")             # D-Fire: 0 smoke, 1 fire
    assert [c["id"] for c in prep.CATEGORIES] == [1, 2] and [c["name"] for c in prep.CATEGORIES] == ["fire", "smoke"]
    assert ev.KINDS == prep.CLASSES


def test_image_size_png_and_jpeg(tmp_path: pathlib.Path) -> None:
    assert prep.image_size(png(tmp_path / "x.png", 640, 360)) == (640, 360)
    assert prep.image_size(jpeg(tmp_path / "y.jpg", 1920, 1080)) == (1920, 1080)
    (tmp_path / "z.gif").write_bytes(b"GIF89a")
    with pytest.raises(prep.InputError):
        prep.image_size(tmp_path / "z.gif")


def test_dfire_class_mapping_and_public_filter(tmp_path: pathlib.Path) -> None:
    root = dfire_tree(tmp_path / "dfire")
    st = prep.Stats()
    items = {it.path.name: it for it in prep.read_dfire(root, "train", False, st)}
    assert set(items) == {"a.png", "b.png"}
    assert st.public_skipped == 1 and st.missing == 1 and st.bad_lines == 2          # bozuk satır ve sınıf 7
    a = items["a.png"]
    # D-Fire 0 (smoke) → bizim 1; D-Fire 1 (fire) → bizim 0. YOLO normalize merkez → COCO piksel sol üst + boy
    assert a.boxes == [(1, [40.0, 15.0, 20.0, 20.0]), (0, [0.0, 20.0, 30.0, 10.0])]   # 2. kutu sola kırpıldı
    assert items["b.png"].boxes == [] and a.source == "dfire"

    st2 = prep.Stats()
    with_public = {it.path.name: it for it in prep.read_dfire(root, "train", True, st2)}
    assert st2.public_skipped == 0 and with_public["PublicDataset_p.png"].source == "dfire-public"
    assert with_public["PublicDataset_p.png"].boxes == [(0, [25.0, 12.5, 50.0, 25.0])]


def test_dfire_missing_folder_is_input_error(tmp_path: pathlib.Path) -> None:
    with pytest.raises(prep.InputError):
        prep.read_dfire(tmp_path, "train", False, prep.Stats())


def test_firenet_voc_to_coco(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "firenet"
    jpeg(root / "train/images/f1.jpg", 200, 100)
    (root / "train/annotations").mkdir(parents=True)
    (root / "train/annotations/f1.xml").write_text(
        "<annotation><filename>f1.jpg</filename><size><width>200</width><height>100</height></size>"
        "<object><name>Fire</name><bndbox><xmin>10</xmin><ymin>20</ymin><xmax>250</xmax><ymax>60</ymax></bndbox></object>"
        "<object><name>lamba</name><bndbox><xmin>1</xmin><ymin>1</ymin><xmax>5</xmax><ymax>5</ymax></bndbox></object>"
        "<object><name>fire</name><bndbox><xmin>30</xmin><ymin>30</ymin><xmax>30</xmax><ymax>40</ymax></bndbox></object>"
        "</annotation>")
    (root / "train/annotations/yetim.xml").write_text("<annotation><filename>yok.jpg</filename></annotation>")
    st = prep.Stats()
    items = prep.read_firenet(root, st)
    assert len(items) == 1 and items[0].source == "firenet" and (items[0].width, items[0].height) == (200, 100)
    assert items[0].boxes == [(0, [10.0, 20.0, 190.0, 40.0])]          # büyük harf "Fire" kabul, sağdan kırpıldı
    assert st.unknown_names == {"lamba": 1} and st.bad_boxes == 1 and st.missing == 1


def test_negatives_skip_drawn_alarm_images(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "neg"
    png(root / "buhar/kare1.png", 320, 240)
    jpeg(root / "0123/image.jpg", 640, 360)                       # uygulamanın zor örnek klasörü: kutular çizili
    (root / "0123/meta.json").write_text("{}")
    jpeg(root / "0123/kare_ham.jpg", 640, 360)
    st = prep.Stats()
    items = prep.read_negatives(root, st)
    assert [(i.path.name, i.boxes, i.source) for i in items] == [("kare_ham.jpg", [], "negatives"),
                                                                 ("kare1.png", [], "negatives")]
    assert st.drawn_skipped == 1
    with pytest.raises(prep.InputError):
        prep.read_negatives(tmp_path / "yok", st)


def test_split_keeps_dfire_test_and_seeds_validation() -> None:
    mk = [prep.Item(pathlib.Path(f"/x/{i}.jpg"), 10, 10, [], "dfire") for i in range(20)]
    extra = [prep.Item(pathlib.Path("/x/f.jpg"), 10, 10, [], "firenet")]
    test = [prep.Item(pathlib.Path("/x/t.jpg"), 10, 10, [], "dfire")]
    p1 = prep.split(mk, test, extra, 0.1, 3)
    p2 = prep.split(mk, test, extra, 0.1, 3)
    assert p1["test"] == test
    assert len(p1["val"]) == 2 and len(p1["train"]) == 19                # 21 × %10 = 2
    assert [i.path for i in p1["val"]] == [i.path for i in p2["val"]]    # tohumlu: aynı bölme
    assert {i.path for i in p1["val"]}.isdisjoint({i.path for i in p1["train"]})


def test_main_writes_coco_and_sources(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = dfire_tree(tmp_path / "dfire")
    out = tmp_path / "out"
    assert prep.main(["--dfire", str(root), "--out", str(out), "--val", "0"]) == 0
    text = capsys.readouterr().out
    assert "PublicDataset ön ekli atılan görüntü: 1" in text
    train = json.loads((out / "annotations/instances_train.json").read_text(encoding="utf-8"))
    test = json.loads((out / "annotations/instances_test.json").read_text(encoding="utf-8"))
    val = json.loads((out / "annotations/instances_val.json").read_text(encoding="utf-8"))
    assert val["images"] == [] and train["categories"] == prep.CATEGORIES
    assert [pathlib.Path(i["file_name"]).name for i in train["images"]] == ["a.png", "b.png"]
    assert pathlib.Path(train["images"][0]["file_name"]).is_absolute()
    assert sorted(a["category_id"] for a in train["annotations"]) == [1, 2]
    assert test["images"][0]["id"] == 3 and test["images"][0]["width"] == 64          # kimlikler bölümler arası benzersiz
    assert test["annotations"] == [{"id": 3, "image_id": 3, "category_id": 1, "bbox": [0.0, 0.0, 64.0, 32.0],
                                    "area": 2048.0, "iscrowd": 0}]
    with (out / "sources.csv").open(encoding="utf-8") as f:
        rows = list(csv.reader(f, delimiter=";"))
    assert rows[0] == ["dosya", "kaynak", "lisans", "bolum"]
    assert rows[1:] == [["a.png", "D-Fire", "CC0-1.0", "train"], ["b.png", "D-Fire", "CC0-1.0", "train"],
                        ["d.jpg", "D-Fire", "CC0-1.0", "test"]]
    assert prep.main(["--dfire", str(tmp_path / "yok"), "--out", str(out)]) == 2
    assert prep.main(["--dfire", str(root), "--out", str(out), "--val", "0.9"]) == 2


# ---------------------------------------------------------------- eval_fire: görüntü düzeyi

def test_ap11_hand_computed() -> None:
    # 2 gerçek kutu; tespitler skor sırasıyla D, Y, D → geri çağırma .5 .5 1, kesinlik 1 .5 .667.
    # r = 0 … 0,5 (6 nokta) için en yüksek kesinlik 1; r = 0,6 … 1 (5 nokta) için 2/3 → (6 + 5·2/3) / 11
    assert ev.ap11([True, False, True], 2) == pytest.approx((6 + 5 * 2 / 3) / 11)
    assert ev.ap11([], 3) == 0.0 and ev.ap11([True], 0) is None
    assert ev.ap11([True, True], 2) == pytest.approx(1.0)


def test_match_iou_and_single_use() -> None:
    gts = {1: [(0.0, 0.0, 10.0, 10.0)], 2: [(50.0, 50.0, 10.0, 10.0)]}
    dets = [(1, 0.5, (0.0, 0.0, 10.0, 10.0)), (1, 0.9, (1.0, 0.0, 10.0, 10.0)), (2, 0.7, (55.0, 50.0, 10.0, 10.0))]
    # 0,9: IoU 90/110 ≥ 0,5 → D; 0,7: IoU 50/150 < 0,5 → Y; 0,5: aynı gerçek kutu kullanıldı → Y
    assert ev.match(gts, dets) == [True, False, False]
    assert ev.iou((0, 0, 10, 10), (20, 20, 5, 5)) == 0.0


def test_simple_ap50_per_class_and_mean() -> None:
    coco = {"images": [{"id": 1}, {"id": 2}],
            "annotations": [{"image_id": 1, "category_id": 1, "bbox": [0, 0, 10, 10]},
                            {"image_id": 2, "category_id": 1, "bbox": [50, 50, 10, 10]},
                            {"image_id": 2, "category_id": 2, "bbox": [0, 0, 20, 20]}]}
    dets = [{"image_id": 1, "category_id": 1, "score": 0.9, "bbox": [0, 0, 10, 10]},
            {"image_id": 2, "category_id": 1, "score": 0.8, "bbox": [90, 90, 5, 5]},
            {"image_id": 2, "category_id": 1, "score": 0.7, "bbox": [50, 50, 10, 10]},
            {"image_id": 1, "category_id": 2, "score": 0.6, "bbox": [0, 0, 20, 20]}]   # duman yanlış görüntüde
    res, method = ev.ap50(coco, dets, use_pycocotools=False)
    assert method.startswith("11 nokta")
    assert res["fire"] == pytest.approx((6 + 5 * 2 / 3) / 11) and res["smoke"] == 0.0
    assert res["mean"] == pytest.approx(((6 + 5 * 2 / 3) / 11) / 2)
    only_fire, _ = ev.ap50({"images": [], "annotations": coco["annotations"][:1]}, dets[:1], use_pycocotools=False)
    assert only_fire["smoke"] is None and only_fire["mean"] == pytest.approx(1.0)    # kutusu olmayan sınıf ortalamada yok


# ---------------------------------------------------------------- eval_fire: olay düzeyi

@dataclass
class FakeAlarm:
    kind: str
    ts: float


class FakeAnalyzer:
    """`process` çağrılarını kaydeder; verilen zamanlarda alarm döndürür."""

    def __init__(self, fire_at: dict[float, str]) -> None:
        self.calls: list[float] = []
        self.fire_at = fire_at

    def process(self, frame: Any, ts: float, profile: Any) -> Any:
        self.calls.append(ts)
        return types.SimpleNamespace(fired=[FakeAlarm(self.fire_at[ts], ts)] if ts in self.fire_at else [])


def test_alarms_from_frames_limits_to_max_fps_like_live() -> None:
    frames = [(i / 25, None) for i in range(50)]                   # 2 sn, 25 kare/sn
    an = FakeAnalyzer({0.4: "fire", 1.2: "smoke"})
    alarms = ev.alarms_from_frames(frames, an, None)
    assert an.calls == pytest.approx([0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8])   # en çok 5/sn
    assert alarms == [(0.4, "fire"), (1.2, "smoke")]
    slow = FakeAnalyzer({})
    ev.alarms_from_frames([(float(i), None) for i in range(4)], slow, None)
    assert slow.calls == [0.0, 1.0, 2.0, 3.0]                      # 1 kare/sn akışta her kare


def test_video_outcome_positive_negative_and_before() -> None:
    o = ev.video_outcome("fire", 5.0, [(2.0, "smoke"), (9.0, "smoke"), (12.5, "fire")])
    assert o == {"label": "fire", "first": 7.5, "caught": True, "false": 0, "before": 1}   # duman yanlış sayılmaz
    late = ev.video_outcome("smoke", 0.0, [(15.5, "smoke")])
    assert late["caught"] is False and late["first"] == 15.5
    edge = ev.video_outcome("smoke", 0.0, [(15.0, "smoke")])
    assert edge["caught"] is True                                  # 15 sn dahil
    neg = ev.video_outcome("none", 0.0, [(3.0, "fire"), (40.0, "smoke")])
    assert neg["false"] == 2 and neg["caught"] is False
    assert ev.video_outcome("fire", 0.0, [])["first"] is None


def test_aggregate_rates_and_first_alarm() -> None:
    outs = [ev.video_outcome("fire", 0.0, [(4.0, "fire")]), ev.video_outcome("fire", 0.0, [(20.0, "fire")]),
            ev.video_outcome("smoke", 2.0, [(1.0, "fire"), (12.0, "smoke")]), ev.video_outcome("none", 0.0, []),
            ev.video_outcome("none", 0.0, [(8.0, "smoke")])]
    a = ev.aggregate(outs)
    assert (a["positives"], a["caught"], a["negatives"], a["false"], a["before"]) == (3, 2, 2, 1, 1)
    assert a["rate"] == pytest.approx(2 / 3)
    assert a["medianFirst"] == pytest.approx(7.0) and a["maxFirst"] == pytest.approx(10.0)   # yakalananlar: 4 ve 10
    assert a["byLabel"] == {"fire": (2, 1), "smoke": (1, 1)}
    empty = ev.aggregate([])
    assert empty["rate"] is None and empty["medianFirst"] is None


def test_gates_and_markdown() -> None:
    good = ev.aggregate([ev.video_outcome("fire", 0.0, [(4.0, "fire")]) for _ in range(4)]
                        + [ev.video_outcome("smoke", 0.0, [])] + [ev.video_outcome("none", 0.0, [])])
    assert good["rate"] == pytest.approx(0.8)
    g = ev.gates({"fire": 0.7, "smoke": 0.5, "mean": 0.6}, good)
    assert [ok for _t, ok in g] == [True, True, True]                  # 0,60 ve %80 sınırları dahil
    bad = ev.gates({"fire": 0.7, "smoke": 0.4, "mean": 0.55}, ev.aggregate([ev.video_outcome("fire", 0.0, [])]))
    assert [ok for _t, ok in bad] == [False, False, False]             # negatif video yoksa kapı geçmez
    events = {s: good for s in ev.SENSITIVITIES}
    sweeps = {k: {0.3: {**good, "false": 2}, 0.35: good} for k in ev.KINDS}
    md = ev.markdown("m.onnx", "ab" * 32, ({"fire": 0.7, "smoke": 0.5, "mean": 0.6}, "11 nokta", {"fire": 3, "smoke": 2}),
                     events, sweeps)
    assert "| Normal | 5 | %80,0 (4) | 4/4 | 0/1 |" in md
    assert "| **Ortalama (mAP50)** | **0,600** | |" in md
    assert "Yangın: Düşük 0,50, Normal 0,35, Yüksek 0,25" in md
    assert md.rstrip().endswith("Sonuç: GEÇTİ")


def test_suggest_threshold() -> None:
    sweep = {0.25: {"false": 3}, 0.3: {"false": 1}, 0.4: {"false": 0}, 0.45: {"false": 0}}
    assert ev.suggest(sweep) == {"low": 0.55, "normal": 0.4, "high": 0.3}
    assert ev.suggest({0.25: {"false": 1}}) is None
    assert ev.suggest({0.9: {"false": 0}})["low"] == 0.95                # üst sınır


def test_manifest_validation(tmp_path: pathlib.Path) -> None:
    (tmp_path / "v.mp4").write_bytes(b"x")
    ok = ev.check_manifest([{"video": "v.mp4", "label": "fire"}, {"video": "v.mp4", "label": "none", "start": 2}],
                           tmp_path)
    assert ok[0]["start"] == 0.0 and ok[1]["label"] == "none" and ok[0]["video"] == tmp_path / "v.mp4"
    for bad in ([], [{"video": "v.mp4"}], [{"video": "v.mp4", "label": "lamba"}],
                [{"video": "v.mp4", "label": "fire", "start": -1}], [{"video": "yok.mp4", "label": "fire"}],
                [{"video": "v.mp4", "label": "fire", "kamera": "x"}], [{"video": "v.mp4", "label": "fire", "start": True}]):
        with pytest.raises(ev.InputError):
            ev.check_manifest(bad, tmp_path)


def test_main_input_errors(tmp_path: pathlib.Path) -> None:
    assert ev.main(["--model", str(tmp_path / "m.onnx")]) == 2                    # ne --coco ne --manifest
    assert ev.main(["--model", str(tmp_path / "m.onnx"), "--coco", "x.json"]) == 2   # model yok


@dataclass
class Det:
    cls: str
    score: float


def test_detection_cache_runs_model_once_and_filters() -> None:
    calls: list[dict[str, float]] = []

    class Model:
        def detect(self, bgr: Any, conf: dict[str, float]) -> list[Det]:
            calls.append(conf)
            return [Det("fire", 0.3), Det("fire", 0.6), Det("smoke", 0.45)]

    cache = ev.DetectionCache(Model())
    first = cache.detector("v")
    assert first.detect(None, {"fire": 0.5, "smoke": 0.5}) == [Det("fire", 0.6)]
    assert calls == [{"fire": ev.CACHE_FLOOR, "smoke": ev.CACHE_FLOOR}]
    again = cache.detector("v")
    assert again.detect(None, {"smoke": 0.4}) == [Det("smoke", 0.45)] and len(calls) == 1   # saklanandan
    assert again.detect(None, {"fire": 0.25}) == [Det("fire", 0.3), Det("fire", 0.6)] and len(calls) == 2  # yeni kare


# ---------------------------------------------------------------- export

def test_export_command_and_shapes(tmp_path: pathlib.Path) -> None:
    cmd = ex.export_command("py", pathlib.Path("Y"), pathlib.Path("c.pth"), pathlib.Path("o.onnx"))
    assert cmd[1].replace("\\", "/") == "Y/tools/export_onnx.py"
    assert cmd[cmd.index("-o") + 1] == "11" and "--decode_in_inference" not in cmd
    assert cmd[cmd.index("-f") + 1] == str(ex.EXP)
    assert ex.EXP.is_file()
    assert ex.ANCHORS == 8400 and ex.EXPECTED_OUTPUT == (1, 8400, 7)
    assert ex.check_shapes([1, 3, 640, 640], [1, 8400, 7]) is None
    assert "Çıkış" in ex.check_shapes([1, 3, 640, 640], [1, 8400, 85])
    assert "Giriş" in ex.check_shapes([1, 3, 416, 416], [1, 3549, 7])
    f = tmp_path / "m.bin"
    f.write_bytes(b"abc")
    assert ex.sha256_file(f) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert ev.sha256_file(f) == ex.sha256_file(f)
    assert ex.main(["--out", str(tmp_path / "yok.onnx")]) == 2                     # --yolox/--ckpt yok
    assert ex.main(["--check-only", "--out", str(tmp_path / "yok.onnx")]) == 2


def test_export_main_resolves_relative_paths(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    """README'deki göreli yollar: komut cwd=YOLOX klasöründe koşar; betik, ağırlık ve çıktı yolu mutlak olmalı ve
    çıktı, çağıranın çalışma klasörüne göre yazılıp orada denetlenmeli."""
    (tmp_path / "YOLOX" / "tools").mkdir(parents=True)
    (tmp_path / "YOLOX" / "tools" / "export_onnx.py").write_text("")
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "best_ckpt.pth").write_bytes(b"w")
    monkeypatch.chdir(tmp_path / "work")
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], cwd: Any, check: bool) -> Any:
        seen["cmd"], seen["cwd"] = cmd, cwd
        pathlib.Path(cmd[cmd.index("--output-name") + 1]).write_bytes(b"onnx")   # YOLOX çıktıyı bu yola yazar
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    monkeypatch.setattr(ex, "run_onnx", lambda path: ([1, 3, 640, 640], [1, 8400, 7]))
    assert ex.main(["--yolox", "../YOLOX", "--ckpt", "best_ckpt.pth"]) == 0
    cmd = seen["cmd"]
    for flag in ("-f", "-c", "--output-name"):
        assert pathlib.Path(cmd[cmd.index(flag) + 1]).is_absolute()
    assert pathlib.Path(cmd[1]).is_absolute() and pathlib.Path(cmd[1]).is_file()
    assert pathlib.Path(cmd[cmd.index("-c") + 1]) == (tmp_path / "work" / "best_ckpt.pth").resolve()
    assert pathlib.Path(seen["cwd"]) == (tmp_path / "YOLOX").resolve()
    assert (tmp_path / "work" / ex.MODEL_NAME).is_file()                            # varsayılan --out: çağıranın klasörü
    assert "SHA-256: " in capsys.readouterr().out


def test_tools_do_not_import_training_stack() -> None:
    for mod in (prep, ev, ex):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")  # type: ignore[arg-type]
        assert "import torch" not in src and "ultralytics" not in src.lower()
    exp_src = (TOOLS / "exps" / "fire_yolox_s.py").read_text(encoding="utf-8")
    assert "num_classes = 2" in exp_src and "(640, 640)" in exp_src and "ultralytics" not in exp_src.lower()


# ---------------------------------------------------------------- uygulamayla uyum (edge)

@needs_edge
def test_constants_match_app() -> None:
    from bantvision.core import fire_model, fire_rules, yolox

    assert ev.MAX_FPS == fire_rules.MAX_FPS
    assert prep.CLASSES == fire_model.CLASSES and ev.KINDS == fire_rules.KINDS
    assert ex.INPUT == yolox.INPUT == fire_model.INPUT and fire_model.MODEL_NAME == ex.MODEL_NAME
    assert ev.CACHE_FLOOR <= min(min(v.values()) for v in fire_rules.THRESHOLDS.values())


@needs_edge
def test_thresholds_override_is_temporary() -> None:
    from bantvision.core import fire_rules

    before = json.dumps(fire_rules.THRESHOLDS, sort_keys=True)
    with ev.thresholds({"smoke": 0.3}) as sens:
        p = ev.fire_profile(sens, only="smoke")
        assert fire_rules.class_conf(p.fire) == {"smoke": 0.3}
    assert json.dumps(fire_rules.THRESHOLDS, sort_keys=True) == before
    assert fire_rules.class_conf(ev.fire_profile("high").fire) == fire_rules.THRESHOLDS["high"]


@needs_edge
def test_play_with_real_analyzer() -> None:
    """Gerçek FireAnalyzer: kutu içinde değişen (titreyen) bölge + sahte dedektör → alev kuralı (3 sn) alarm verir;
    dedektörün hiç kutu vermediği video negatiftir."""
    import numpy as np

    from bantvision.core.detector import Detection

    rng = np.random.default_rng(0)

    def frames(path: pathlib.Path) -> list[tuple[float, Any]]:
        out = []
        for i in range(25 * 8):                                    # 8 sn, 25 kare/sn
            f = np.full((120, 160, 3), 90, np.uint8)
            f[40:80, 60:100] = rng.integers(0, 255, (40, 40, 3), dtype=np.uint8)
            out.append((i / 25, f))
        return out

    class Model:
        def detect(self, bgr: Any, conf: dict[str, float]) -> list[Detection]:
            return [Detection(60, 40, 100, 80, 0.9, "fire")]

    class Empty:
        def detect(self, bgr: Any, conf: dict[str, float]) -> list[Detection]:
            return []

    pos = ev.play([{"video": pathlib.Path("p"), "label": "fire", "start": 0.0}], ev.DetectionCache(Model()),
                  ev.fire_profile("normal"), frames=frames)
    assert pos[0]["caught"] is True and 3.0 <= pos[0]["first"] <= 3.0 + 1 / ev.MAX_FPS + 1e-6
    neg = ev.play([{"video": pathlib.Path("n"), "label": "none", "start": 0.0}], ev.DetectionCache(Empty()),
                  ev.fire_profile("high"), frames=frames)
    assert neg[0]["false"] == 0
