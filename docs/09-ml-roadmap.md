# 09 — ML Yol Haritası

Klasik hat sahada çalışırken veri biriktirir; ML onun zorlandığı yerlerde devreye girer.

## 1. Ne zaman ML gerekir?
- Ürünler sürekli birbirine değiyor / üst üste biniyor (dökme yumurta, yığılmış torba).
- Ürün ile bant aynı renk/parlaklıkta (arka plan farkı zayıf).
- Hata görünüme dayalı ve geometriyle yakalanmıyor (çatlak, yırtık doku, yanlış baskı).

## 2. Veri toplama (F1.3 iOS, F2 edge)
- Klasik hat **otomatik etiketleyici**dir. Etiket yalnızca güvenli karelerde üretilir: en az bir leke, tüm lekelerin çarpanı 1, hiçbir leke ROI kenarına değmiyor.
- Format (YOLO):
```
<dataset>/
  images/<cihaz>_<zaman>_<sıra>.jpg      # uzun kenar 640, JPEG 85
  labels/<aynı ad>.txt                   # her satır: 0 cx cy w h (görüntüye göre 0–1)
  meta.json                              # profil, cihaz, kamera, tarih, fps, mmPerPixel
```
- QC açıksa NOK kırpıntıları ayrıca `crops/nok/<neden>/` ve rastgele %2 OK kırpıntısı `crops/ok/` altına (anomali tespiti ve sınıflandırıcı için).
- Kontrol: `tools/check_dataset.py <dataset> --draw out/`.
- Elle düzeltme gerekirse CVAT ya da Label Studio (YOLO içe/dışa aktarma).

## 3. Anomali tespiti — sadece sağlam ürünle (F7.1)
- Girdi: ürün kırpıntısı (QC'deki tam çözünürlüklü kırpıntı, 224×224'e ölçeklenmiş, ürün maskesi dışı nötr griye boyanmış).
- Öznitelik çıkarıcı: ImageNet ön eğitimli MobileNetV3-Large'ın ara katmanları (PaDiM/PatchCore yaklaşımı). iOS'ta CoreML, edge'de ONNX Runtime / OpenVINO.
- Hafıza bankası: ~50–200 sağlam kırpıntının yama öznitelikleri (coreset alt örnekleme ile ≤ 5.000 vektör).
- Skor: test yamalarının en yakın komşu uzaklıklarının maksimumu. Eşik: ayrı 50 sağlam örnekte skorların 99. yüzdeliği × 1,1.
- Profil: `qc.anomaly = {enabled, bankRef, threshold}` (sözleşmeye F7'de eklenir). Neden kodu `anomaly`.
- Kalibrasyon akışı: "Sağlam ürün öğret" → 100 ürün geçir → banka + eşik otomatik.

## 4. YOLO dedektör eklentisi (F7.2)
- Çekirdekte `Detector` arayüzü: `detect(gray_or_bgr, roi) -> list[Blob]`. Klasik segmenter de bu arayüzü uygular; izleme/sayım/QC değişmez.
- Model: küçük tek sınıflı dedektör (ürün), giriş 640 ya da 416.
- Eğitim: `tools/train/` (F7'de) — veri bölme (gün bazlı, sızıntı olmasın), artırma (parlaklık, bulanıklık, hareket bulanıklığı), dışa aktarma: iOS **CoreML** (NMS dahil), edge **OpenVINO** (Intel) / ONNX.
- Sahada aktif öğrenme: düşük güvenli tespitler ve klasik/ML uyuşmazlıkları `datasets/review/` altına.

## 5. Lisans uyarısı (karar F7.2 öncesi)
- **Ultralytics YOLO (v8/11) AGPL-3.0 lisanslıdır.** Kapalı kaynak ticari üründe kullanmak için Ultralytics Enterprise lisansı gerekir. Aksi halde tüm uygulama kaynağını açma yükümlülüğü doğabilir.
- Apache-2.0 alternatifler: YOLOX, RTMDet (MMDetection), D-FINE / RT-DETR'in Apache lisanslı uygulamaları. Doğruluk/hız karşılaştırması F7.2'nin ilk görevi.
- Ön eğitimli ağırlıkların lisansı da ayrıca kontrol edilmeli.
