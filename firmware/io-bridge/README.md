# BantVision I/O köprüsü (ESP32)

Spesifikasyon: `docs/07-io-bridge-esp32.md`. Bu klasör F5'te PlatformIO projesi olarak doldurulacak:

```
firmware/io-bridge/
  platformio.ini          # board: wt32-eth01 (esp32dev tabanlı), framework: arduino
  src/main.cpp            # ağ, UDP sunucu, komut ayrıştırma (ArduinoJson), HMAC (mbedtls)
  src/outputs.cpp/.h      # kanal sürücüleri, esp_timer ile zamanlanmış darbeler
  src/encoder.cpp/.h      # PCNT tabanlı hız ölçümü
  src/web.cpp/.h          # yapılandırma sayfası, NVS'de kalıcı ayarlar
  hardware/               # bağlantı şemaları (PNP/NPN PLC girişi, röle modülü)
  test/                   # Python test istemcisi: tools/io_test.py
```
