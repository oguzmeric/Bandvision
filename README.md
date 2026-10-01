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

## Videodan sayım (masa başı test)

Bant videosunu (telefonla çekilmiş ya da lisanslı stok video) çekirdekten geçirir; işaretli video, sayı ve profil üretir.

```bash
cd services/edge && pip install -e ".[dev]"
python -m bantvision.video bant.mp4 --truth 57      # 57 = elle sayılan doğru adet
```

Çıktı `bant_analiz/` klasörüne yazılır: `isaretli.mp4` (ROI, sayım çizgisi, iz kimlikleri, sayaç), `ozet.json`
(sayı, hata %, bulunan ayarlar), `profil.json` (sözleşmeye uygun profil), `sayimlar.csv`.

- Arka plan, eşik, akış yönü ve tek ürün alanı videodan **otomatik** bulunur; boş bant görüntüsü gerekmez.
- Ürünler hep bitişik geliyorsa (ör. çift çift yumurta) alan tek başına belirsizdir: önce ürünlerin **tek tek**
  geçtiği kısa bir videoyla kalibre et, sonra yoğun videoyu o profille say:
  `python -m bantvision.video yogun.mp4 --profile kalibrasyon_analiz/profil.json`
- Bant çoğu zaman **%75'ten fazla doluysa** videonun kendisinden arka plan çıkarılamaz (her pikselde ürün çoğunluktadır). Videonun başında 1–2 sn boş bant çek ve `--bg-range 0,1.5` ver. Öğrenilen arka plan `arka_plan.png`'ye yazılır: orada ürün görünmemeli.
- Elle ayar: `--direction`, `--roi x,y,g,y`, `--line`, `--expected-area`, `--width`. Tümü: `--help`.
- Sabit kamera şart: kayan, zoom yapan ya da kurgulu videolarda klasik yöntem güvenilmez.
