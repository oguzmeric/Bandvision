# Alt akışı ölü kanallar: ana akışa düşme — plan (2026-11-06)

**Ölçüm (ofis TRASSIR, 16 kanal):** 8 kanal panelde "Görüntü yok". 7'sinde ANA akış 1–2 sn'de kare veriyor (704×576), ALT akış
"açıldı" ama 18 sn boyunca hiç kare vermiyor; TRASSIR kanal listesi yine de `have_substream=true` diyor. Küçük resim de alt
akıştan jpeg jetonuyla istendiği için 555 portu yanıt vermiyor ("Kayıt cihazına bağlanılamadı (…:555 yanıt vermedi)").
Tek gerçek sinyalsiz kanal "RTSP 3" (ikisi de kare yok). Kullanıcı: "1 kamera hariç sorunu çöz."

## Kararlar
R1. **Tek ortak nokta: `LiveManager`'da kanal başına "alt akış ölü" belleği** (`_dead_sub: dict[(source_id, channel_id), monotonic]`).
    Bir kanalın alt akışı ölü işaretlendiyse `opener()` (izleme, oturum) ve `_snapshot()` o kanal için ANA akışı kullanır.
    İşaret `DEAD_SUB_RETRY_S = 600` sn sonra düşer (alt akış yeniden denenir; TRASSIR'da kanal ayarı düzeltilebilir).
R2. **Nasıl öğrenilir:**
    - **Küçük resim** (`_snapshot`): alt akış jpeg isteği `unreachable`/`unexpected` ile düşerse ve kanal alt akış diyorsa, hemen
      ANA akış jpeg'i denenir; o gelirse kanal "alt ölü" işaretlenir ve resim döner. Ana da düşerse mevcut 502.
    - **İzleme okuyucusu** (`CameraViewer`): bir deneme alt akışta "açıldı ama 0 kare" bitirdiyse (okuma zaman aşımı), bir
      sonraki deneme ANA akışla yapılır (`quality` anahtarı değişmez; yalnız adres). Ana akış kare verirse kanal "alt ölü"
      işaretlenir. Bunun için `opener`'a `prefer_main: bool` ipucu geçer: `_view_opener(source, channel, sub, prefer_main)`.
      Okuyucu bunu `_no_frames` ile birlikte takip eder: ilk deneme alt, kare yoksa ana, ana da kare yoksa tekrar alt…
      (gerçek sinyalsiz kanal ikisinde de kare vermez; mevcut geri çekilme sürer).
    - **Analiz oturumu** (`LiveSession._read_loop`): aynı mantık; oturumun `substream` seçimi kullanıcıya aitse (False) zaten ana.
      `substream=True` ya da None ise ve ilk denemede alt akış 0 kare verdiyse ana akışa geçilir, oturum `status.message`
      "Alt akış görüntü vermiyor; ana akış kullanılıyor." yazar (kalıcı değil, bir sonraki başarılı bağlanışta temizlenir).
R3. **Ana akış maliyeti:** izleme duvarında ana akış 2688×1520 olabilir; `CameraViewer` zaten `MAX_WIDTH[sub]=960`'a küçültüyor,
    CPU artar ama görüntü gelir. `MAX_MAIN=2` sınırı yalnız `quality="main"` kutuları içindir; alt ölü kanalın ana akışı
    `quality="sub"` anahtarıyla açıldığı için sayılmaz — kabul (sinyalsiz kanal yerine görüntü, kullanıcı isteği).
R4. **API/panel:** `GET /sources/{id}/channels` yanıtına `subDead: bool` eklenir (panel küçük resim altında ipucu: "Alt akış
    görüntü vermiyor; ana akış kullanılıyor." soluk satır). Kameralar sayfası bunu gösterir. Sözleşme yok (canlı API).
R5. **Günlük:** kanal alt ölü işaretlenince bir kez INFO: "Alt akış görüntü vermiyor, ana akışa geçildi: <kaynak>/<kanal>".
R6. **Testler:** `test_viewer.py` (alt 0 kare → ana denemesi, ana kare verince işaret; 600 sn sonra alt tekrar),
    `test_live.py` (oturum geçişi + mesaj), `test_recorders`/api (küçük resim ana akışa düşer, `subDead`), e2e Kameralar ipucu.
R7. **Belge:** docs/13 "Canlı sayım: kamera ve kayıt cihazı" ve "Çoklu izleme" bölümlerine kural; docs/12 satır.
