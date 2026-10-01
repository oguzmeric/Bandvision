# CLAUDE.md — BantVision çalışma kuralları

Bu repo, banttan geçen ürünleri **sayan** ve **kalite kontrol (OK/NOK)** yapan bir görüntü işleme platformudur.
Görüntü kaynağı iPhone kamerası, IP kamera (RTSP/ONVIF), AHD kamera (XVR üzerinden RTSP ya da USB yakalama kartı) olabilir.

## Önce oku
1. `docs/00-overview.md` – mimari ve bileşenler
2. `docs/01-roadmap.md` – fazlar, görevler, kabul kriterleri (**işleri bu sırayla yap**)
3. `docs/02-contracts.md` + `contracts/*.schema.json` – tüm bileşenlerin ortak dili
4. `docs/03-algorithm.md` – sayım/QC algoritmasının bağlayıcı referansı

## Değişmez kurallar
- **Sözleşmeler tek doğruluk kaynağıdır.** Profil ve olay formatı `contracts/` altındadır. Bir alan eklemek/değiştirmek için önce şemayı ve `docs/02-contracts.md`'yi güncelle, sonra tüm uygulamaları (iOS, edge, backend) aynı PR'da uyumla. Şema versiyonunu (`v1`) kırıcı değişiklikte artır.
- **Algoritma eşdeğerliği (parity).** Swift (iOS) ve Python (edge) çekirdekleri `docs/03-algorithm.md`'deki davranışı birebir uygular. `services/edge/bantvision/core/` Python referansıdır; davranış farkı çıkarsa referans doküman kazanır, iki tarafı da düzelt. Sentetik testler her iki tarafta aynı sayıları vermelidir.
- **Cihaz üzerinde işleme.** Görüntüler varsayılan olarak cihazdan çıkmaz. Yalnızca olaylar ve (açıksa) NOK görselleri gönderilir.
- **Çevrimdışı dayanıklılık.** Ağ yokken olaylar yerel kuyrukta (outbox) birikir, ağ gelince gönderilir. Olaylar `event_id` ile idempotent'tir.
- **Güvenlik.** Edge kutusundaki fiziksel çıkışlar (24V, ejektör) yalnızca açık profil ayarıyla tetiklenir; varsayılan kapalı. Ejektör doğrudan ESP32'ye değil röle/PLC girişi üzerinden bağlanır.

## Dil ve stil
- Kullanıcıya görünen metinler **Türkçe**. Kod tanımlayıcıları İngilizce. Yorumlar Türkçe ya da İngilizce olabilir.
- iOS: Swift 5 dil modu, SwiftUI, iOS 17+, harici bağımlılık yok (zorunlu değilse ekleme).
- Edge: Python 3.11+, FastAPI, OpenCV, numpy. Tip ipuçları zorunlu, `ruff` + `pytest`.
- Backend: Supabase (Postgres + Edge Functions, TypeScript), dashboard Next.js 15 (App Router).
- Firmware: ESP32, Arduino framework (PlatformIO).

## Bilinen durum
- `apps/ios/` altındaki Swift kodu **Xcode'da hiç derlenmedi** (Linux ortamında yazıldı). F0'ın ilk görevi derleyip hataları düzeltmektir. Algoritma mantığı Python'da sentetik veriyle doğrulandı.
- `services/edge/bantvision/core/` çalışır ve testleri geçer (`cd services/edge && pytest`).
- TRASSIR entegrasyonunun teknik detayları (script API, restream) **doğrulanmadı**; `docs/08-trassir-integration.md`'deki açık soruları kullanıcıya sor.

## Bir görevi bitirirken
- İlgili kabul kriterlerini (`docs/01-roadmap.md`) tek tek kontrol et.
- Testleri çalıştır. Yeni davranış için test ekle.
- Sözleşme değiştiyse şema + doküman + tüm uygulamalar güncel mi kontrol et.
