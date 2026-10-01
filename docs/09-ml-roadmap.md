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

## 4b. Öneri: "Örnekle öğret" — iyi/kötü işaretle, dakikalar içinde öğrensin (F7.0, karar bekliyor)

Kaynak fikir: `11-market-notes-enao.md`. Amaç, model eğitimi yapmadan, sahada operatörün birkaç dokunuşla görünüm tabanlı OK/NOK kriteri tanımlaması.

- **Neden şimdiki mimariye uyuyor:** Klasik hat her ürünü zaten ayırıyor ve çizgiyi geçtiği anda en iyi karede tam çözünürlüklü kırpıntıyı çıkarıyor (QC adımı). Bu kırpıntıdan bir **öznitelik vektörü (embedding)** almak, eğitimsiz bir sınıflandırıcı için yeterli.
- **iOS:** Apple Vision `VNGenerateImageFeaturePrintRequest` cihaz üstünde çalışıyor. Model dosyası taşımak ve lisans sorunu yok; `computeDistance` ile benzerlik hesaplanıyor.
- **Edge:** Apple FeaturePrint olmadığından Apache/BSD lisanslı küçük bir omurga (ör. MobileNetV3, §3'tekiyle aynı) ONNX Runtime / OpenVINO ile kullanılır. Embedding'ler modele özgü olduğu için **profil vektör değil örnek kırpıntı referansı taşır**. Her taraf kendi bankasını örneklerden yeniden üretir; parity (eşdeğerlik) burada sayı değil karar düzeyinde ölçülür.
- **Karar:** k-en yakın komşu (k=3). En yakın OK ve NOK örneklerine uzaklık oranı + güven eşiği. Yalnızca OK örneği varsa §3'teki anomali skoruna düşer.
- **Akış:**
  1. Çalışırken ekranın altında son geçen ürünlerin kırpıntıları şerit olarak akar.
  2. Operatör bir kırpıntıya dokunup "İyi" ya da "Kötü" der; kötüde isteğe bağlı neden seçer.
  3. ~10 iyi + ~5 kötü örnekten sonra "Öğrenildi", ardından **gölge modu**: karar verir, ama ejektöre sinyal göndermez.
  4. Operatör yanlışları düzelttikçe banka büyür.
- **Sözleşme taslağı:** `qc.examples = {enabled, bankRef, k, minConfidence}`, NOK nedeni `appearance`. Belirsiz kararlar `uncertain` olarak işaretlenir ve inceleme kuyruğuna (F1.3 veri toplama) gider.
- **Riskler:** Işık değişimi embedding'i kaydırır (tutarlı aydınlatma şart, `11` §2). Çok ince hatalar (kılcal çatlak) global embedding'de kaybolabilir; o durumda §3'teki yama tabanlı yöntem gerekir.
- **Doğrulama:** `10-field-setup.md` §6 kabul testinin aynısı (500 ürün, bilinen 20 hata).

## 5. Lisans uyarısı (karar F7.2 öncesi)
- **Ultralytics YOLO (v8/11) AGPL-3.0 lisanslıdır.** Kapalı kaynak ticari üründe kullanmak için Ultralytics Enterprise lisansı gerekir. Aksi halde tüm uygulama kaynağını açma yükümlülüğü doğabilir.
- Apache-2.0 alternatifler: YOLOX, RTMDet (MMDetection), D-FINE / RT-DETR'in Apache lisanslı uygulamaları. Doğruluk/hız karşılaştırması F7.2'nin ilk görevi.
- Ön eğitimli ağırlıkların lisansı da ayrıca kontrol edilmeli.
