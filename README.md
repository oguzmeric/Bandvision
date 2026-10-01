# BantVision

Telefonla veya mevcut güvenlik kameralarıyla banttaki ürünleri sayan ve kalite kontrol yapan platform.

| Bileşen | Klasör | Durum |
|---|---|---|
| iOS uygulaması (iPhone kamera, kalibrasyon istemcisi) | `apps/ios` | v1 kodu hazır, derlenmesi gerekiyor |
| Edge servisi (RTSP/ONVIF/AHD, çoklu kamera) | `services/edge` | çekirdek algoritma + testler hazır, servis F2 |
| Backend + dashboard | `supabase`, `apps/dashboard` (F3) | veritabanı şeması hazır |
| I/O köprüsü (24V sayım darbesi, ejektör) | `firmware/io-bridge` | spesifikasyon |
| Uyarı akışları | `n8n` | spesifikasyon |
| Ortak sözleşmeler | `contracts` | v1 |

Başlangıç: `CLAUDE.md` → `docs/00-overview.md` → `docs/01-roadmap.md`.

```bash
# Python referans çekirdeğini test et
cd services/edge && pip install -e ".[dev]" && pytest -q
```
