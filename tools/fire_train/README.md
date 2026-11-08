# Yangın/duman modeli eğitimi (`tools/fire_train/`)

Uygulamanın yangın/duman analizi (`countMode: "fire"`) iki sınıflı bir YOLOX-S modeli (`fire_smoke_v1.onnx`) bekler.
Bu klasör o modeli **lisansı temiz** veriyle eğitmek, ONNX'e çevirmek ve ölçmek için araçları tutar. Kullanım, model kartı
ve veri atıfları: `docs/14-yangin-duman.md`. Tasarım: `docs/superpowers/specs/2026-11-08-yangin-duman-design.md` §4–§5.

> **İndirme, eğitim ve ölçüm kullanıcı onayıyla yapılır.** Bu belge adımları anlatır; hiçbiri kendiliğinden çalışmaz.
> Veriler, ağırlıklar (`*.pth`, `*.onnx`) ve ölçüm dosyaları depoya girmez.

## Kurallar
- **Ultralytics kodu, ağırlığı ya da eğitim aracı hiçbir adımda kullanılmaz.** Lisans zinciri YOLOX (Apache-2.0) ve COCO
  ön eğitimli `yolox_s.pth` (YOLOX sürümü, Apache-2.0) üzerinde kalır.
- Eğitim **ayrı bir sanal ortamda** yapılır (PyTorch + YOLOX kaynağı). Ana uygulama ortamına hiçbir şey kurulmaz;
  uygulama `tools/fire_train`'i hiç içe aktarmaz.
- Veri: D-Fire'ın `PublicDataset` ön eki taşımayan görüntüleri (CC0 derlemesi) ve FireNet (MIT). `PublicDataset`
  görüntüleri üçüncü taraf sağlayıcıların koşullarına tabidir; `--include-public` ile yalnız deneme için alınabilir,
  ürün modeline girmez.
- Ölçüm verisi: D-Fire test bölümü (görüntü düzeyi) ve FIRESENSE videoları (CC BY 4.0; olay düzeyi).

## Dosyalar
| Dosya | Ortam | Ne yapar |
|---|---|---|
| `prepare_data.py` | herhangi (yalnız standart kitaplık) | D-Fire YOLO txt + FireNet VOC xml → COCO json (`annotations/instances_{train,val,test}.json`), `sources.csv` (`dosya;kaynak;lisans;bolum`). D-Fire sınıf düzeni (0 smoke, 1 fire) bizim düzene (0 fire, 1 smoke) çevrilir. D-Fire'ın train/test ayrımı korunur; eğitim havuzundan tohumlu %10 doğrulama. `--negatives`: kutusuz zor örnek kareleri (uygulamanın kutusu çizili alarm resimleri atlanır). |
| `exps/fire_yolox_s.py` | eğitim | YOLOX `Exp`: YOLOX-S, 2 sınıf, giriş 640, veri kökü `FIRE_DATA_DIR`. |
| `export.py` | eğitim | YOLOX `tools/export_onnx.py` sarmalayıcısı (opset 11, kod çözmesiz); onnxruntime ile `[1, 8400, 7]` çıkış denetimi; SHA-256. |
| `eval_fire.py` | ana uygulama ortamı | (a) görüntü düzeyi mAP50 (sınıf başına), (b) olay düzeyi: videolar gerçek `FireAnalyzer` ile, (c) eşik kalibrasyonu önerisi; Türkçe Markdown rapor ve kabul kapısı. |

Testler: `tools/tests/test_fire_train.py` (PyTorch gerektirmez; numpy/OpenCV isteyenler `needs_edge` ile işaretli).

## Adımlar

1. **Eğitim ortamı** (ayrı klasör, ayrı sanal ortam): CUDA'lı PyTorch, YOLOX kaynak kodu (`pip install -v -e .` YOLOX
   klasöründe) ve YOLOX sürümlerinden COCO ön eğitimli `yolox_s.pth`.
2. **Veri** (onaydan sonra indirilir): D-Fire (`train/`, `test/`; her birinde `images/`, `labels/`), FireNet (VOC xml),
   FIRESENSE videoları.
3. **Hazırlık:**

   ```
   python tools/fire_train/prepare_data.py --dfire <D-Fire kökü> --firenet <FireNet kökü> --out <veri kökü>
   ```

   Kullanıcı izniyle toplanmış zor örneklerin ham kareleri varsa `--negatives <klasör>` eklenir
   (`docs/14-yangin-duman.md` §8). Özet tabloda bölüm başına görüntü, negatif ve kutu sayıları ile atılan `PublicDataset` sayısı yazar. Sınıf düzenini
   bir kez doğrulamak için `--include-public` ile ayrı bir klasöre hazırlayıp toplam kutu sayılarını D-Fire README'siyle
   (fire 14.692, smoke 11.865) karşılaştırın; sayılar yer değiştirmişse `DFIRE_CLASSES` ters demektir.
4. **Eğitim** (YOLOX kaynak klasöründe; `FIRE_DATA_DIR=<veri kökü>`):

   ```
   python tools/train.py -f <depo>/tools/fire_train/exps/fire_yolox_s.py -d 1 -b 16 --fp16 -o -c yolox_s.pth
   ```

   6 GB ekran kartında `-b 8` gerekebilir. Çıktı `YOLOX_outputs/fire_yolox_s/best_ckpt.pth`.
5. **ONNX** (eğitim ortamında):

   ```
   python tools/fire_train/export.py --yolox <YOLOX kaynağı> --ckpt <best_ckpt.pth> --out fire_smoke_v1.onnx
   ```

   Çıkış `[1, 8400, 7]` değilse dosya kullanılmaz. Yazılan SHA-256 not edilir.
6. **Ölçüm** (ana uygulama ortamında; model dosyası herhangi bir yerde olabilir):

   ```
   python tools/fire_train/eval_fire.py --model fire_smoke_v1.onnx --coco <veri kökü>/annotations/instances_test.json --manifest videolar.json --out rapor.md
   ```

   `videolar.json`: `[{"video": "yol", "label": "fire"|"smoke"|"none", "start": saniye}]` (yollar manifestin
   klasörüne göre; `start` olayın göründüğü an, varsayılan 0). FIRESENSE'in alev/duman pozitif videoları `fire` /
   `smoke`, negatifleri `none` olarak yazılır.
7. **Karar:** kabul hedefleri (aşağıda) tutarsa ve kullanıcı onaylarsa model GitHub sürümüne yüklenir,
   `core/fire_model.py` `FIRE_MODEL_URL` / `FIRE_MODEL_SHA256` doldurulur, kalibrasyon önerisi `core/fire_rules.py`
   `THRESHOLDS`'a ölçüm tablosuyla ayrı commit'te işlenir ve `docs/14-yangin-duman.md` model kartının ölçüm bölümü
   doldurulur. Tutmazsa ayrıntılı rapor kullanıcıya sunulur, **model yayımlanmaz**.

## Kabul hedefleri (v1)
- D-Fire test mAP50 (iki sınıf ortalaması) **≥ 0,60**.
- FIRESENSE pozitif videolarının **≥ %80**'inde Normal hassasiyette **15 sn** içinde alarm.
- Negatif videolarda Normal hassasiyette **0** yanlış alarm.

`eval_fire.py` bu üç kapıyı yazar; çıkış kodu 0 yalnız hepsi geçince (1 kaldı, 2 girdi hatası).
