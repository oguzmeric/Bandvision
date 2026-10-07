# MoveNet SinglePose Thunder — kaynak ve lisans

- Kaynak: Google, MoveNet SinglePose Thunder, sürüm 4 (SavedModel).
  Adres: https://www.kaggle.com/models/google/movenet/tensorFlow2/singlepose-thunder/4
  (eski TF Hub adresi `google/movenet/singlepose/thunder/4`'ün devamı). Lisans: Apache License 2.0.
- Değişiklik: SavedModel `tools/convert_movenet.py` ile ONNX'e (opset 13, tf2onnx) çevrildi; ağırlıklar değiştirilmedi.
  Çeviri orijinal modelle karşılaştırıldı (en büyük çıktı farkı < 0,01). Çeviri GitHub Actions'ta
  (`.github/workflows/models.yml`) çalışır; çıktı bu sürüme oradan yüklenir.
- Bu dosya BandVision tarafından yalnızca dağıtım kolaylığı için yeniden yayınlanır; lisans metni: LICENSE-APACHE-2.0.txt.
