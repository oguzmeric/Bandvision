# 07 — I/O Köprüsü (ESP32)

Amaç: Sayım ve QC sonuçlarını fabrikanın fiziksel dünyasına taşımak: PLC'ye 24V sayım darbesi, hatalı ürün için gecikmeli ejektör darbesi, alarm lambası. Telefon ve edge kutusu aynı köprüyü kullanır.

## 1. Donanım
- **Kart:** Kablolu ağ tercih edilir → WT32-ETH01 (ESP32 + LAN8720 Ethernet). Wi-Fi yalnızca kablo çekilemiyorsa.
- **Çıkışlar (4 kanal):** her kanal optokuplör (PC817 sınıfı) ile yalıtılmış transistör çıkışı → PLC dijital girişi (24V). PLC girişinin **PNP (sourcing) / NPN (sinking)** tipine göre bağlantı şeması iki seçenekli çizilmeli; varsayılan PNP.
- **Ejektör/valf/lamba:** ESP32'den doğrudan sürülmez. Ya PLC üzerinden ya da 24V röle/SSR modülü üzerinden; bobin yüklerinde flyback diyot.
- **Girişler (opsiyonel, 2 kanal):** optokuplörlü 24V giriş — "hat çalışıyor" sinyali ve bant enkoderi (darbe sayımı ile kesin bant hızı → ejektör zamanlaması için en iyisi).
- **Besleme:** 24V → 5V DC-DC, DIN ray kutusu, 24V tarafında sigorta.
- Açılışta tüm çıkışlar **kapalı** (pull-down), watchdog 2 sn.

## 2. Firmware (PlatformIO, Arduino framework)
- `firmware/io-bridge/` altında. Ağ: DHCP + statik IP seçeneği; mDNS adı `bv-io-<mac4>.local`, servis `_bantvision-io._udp`.
- Yapılandırma: tarayıcıdan basit web sayfası (`http://<ip>/`): ağ ayarları, kanal adları, darbe testi, kimlik doğrulama anahtarı (paylaşılan gizli).
- Zamanlama: `esp_timer` tek seferlik zamanlayıcılar; en fazla 64 bekleyen darbe; çakışan darbe aynı kanalda birleştirilir (uzatılır).
- Enkoder girişi: donanım darbe sayacı (PCNT), 100 ms'de bir hız hesabı.

## 3. Güvenlik
- Her UDP mesajı `hmac` alanı taşır: `HMAC-SHA256(secret, mesaj gövdesi)` ilk 16 hex. Yanlış HMAC → yok sayılır.
- `seq` alanı ile tekrar oynatma koruması (son 256 seq hatırlanır).
- Uygulama tarafında ejektör yalnızca profilde `io.eject.enabled = true` ise.

## 4. Protokol (UDP, port 4210, JSON)
İstek:
```json
{ "v": 1, "seq": 1234, "cmd": "pulse", "ch": 2, "delayMs": 412, "widthMs": 80, "hmac": "9f1c..." }
```
| `cmd` | Alanlar | Açıklama |
|---|---|---|
| `pulse` | `ch, delayMs, widthMs` | `delayMs` sonra `widthMs` süreli darbe (sayım için `delayMs = 0`) |
| `set` | `ch, on` | Sürekli çıkış (alarm lambası) |
| `status` | — | Yanıt: çıkış durumları, girişler, enkoder hızı (darbe/sn), çalışma süresi, sürüm |
| `ping` | — | Gecikme ölçümü |

Yanıt (her komuta): `{ "v":1, "seq":1234, "ok":true, "err":null }`. İstemci 100 ms içinde yanıt alamazsa **sayım darbesini** bir kez yeniden gönderir (aynı `seq`; köprü tekrarı tanır ve ikinci kez darbe üretmez). Ejektör darbeleri yeniden gönderilmez (geç darbe yanlış ürünü iter).

## 5. Zamanlama hesabı (uygulama tarafı)
`03-algorithm.md` §9. Ağ gecikmesi (`ping` ortalaması / 2) `delayMs`'ten düşülür. Enkoder bağlıysa bant hızı köprünün `status` yanıtından alınır ve görüntüden tahmine tercih edilir.

## 6. Kabul testi
- 1000 ürün: PLC sayacı = uygulama sayacı.
- Ejektör: 1 m/s bantta 100 işaretli üründe ≥ 98 isabet; sağlam ürünlere yanlış itme 0.
- Güç kesilip gelince çıkışlar kapalı başlıyor; ağ koptuğunda bekleyen darbeler yine de zamanında çalışıyor.
