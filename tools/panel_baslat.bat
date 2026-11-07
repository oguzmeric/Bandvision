@echo off
rem BandVision web paneli (yerel demo): analiz sunucusu + panel, hazir olunca tarayici.
rem Calisiyorlarsa yeniden baslatmaz. Kapatmak icin gorev cubugundaki "BandVision analiz" ve
rem "BandVision panel" pencerelerini kapat. Gunlukler: .logs\analyzer.log ve .logs\panel.log
rem (Pencere icinde metin secmek Windows'ta yazan sureci durdurur; bu yuzden cikti dosyaya gider.)
rem Panel baslaticisi (tools\panel_run.mjs) tek kopya calisir (zaten calisiyorsa yeni kopya hemen cikar) ve uretim
rem kipinde acar; derleme gerekiyorsa (ilk acilis ya da guncelleme) 1-2 dk surer: baslaticinin durum dosyasi
rem (apps\dashboard\.local\panel-state.json) "building" iken bu pencere bunu yazar ve en cok 240 sn bekler.
rem Port: panel 3300'de acilir (3000 bu bilgisayarda baska bir uygulamanin); 3300 doluysa siradaki bos portta (3301...).
rem Port apps\dashboard\.local\panel.port dosyasindan okunur (PowerShell yok: klasor adindaki kesme isareti bozmaz); panel
rem sayfadaki "bv-panel" isaretiyle taninir (o porttaki baska uygulama panel sanilmaz). Baslatici acilamazsa nedenini
rem apps\dashboard\.local\panel-notice.txt dosyasina yazar (eski surum panel calisiyor, bos port yok...); burada gosterilir.
rem Bu dosya SALT ASCII kalmali: chcp 65001 sonrasinda cmd cok baytli karakter iceren dosyayi kaymis okur (testi: tests/test_launcher_ascii.py).
chcp 65001 >nul
setlocal
set "ROOT=%~dp0.."
set "EDGE=%ROOT%\services\edge"
set "DASH=%ROOT%\apps\dashboard"
set "LOGS=%ROOT%\.logs"
if not exist "%LOGS%" mkdir "%LOGS%"

if not exist "%EDGE%\.venv\Scripts\python.exe" (
  echo Analiz sunucusu ortami kuruluyor ^(ilk sefer, birkac dakika^)...
  python -m venv "%EDGE%\.venv" || goto :hata
  "%EDGE%\.venv\Scripts\python.exe" -m pip install -q -e "%EDGE%[analyzer]" || goto :hata
)
rem Eski kurulumda (guncellemeyle yeni bir paket eklendiyse ya da alt surumu yukseldiyse) analiz sunucusu acilmaz:
rem pyproject.toml'daki calisma bagimliliklarinin hepsi kurulu ve yeterince yeni mi, uygulama modulu aciliyor mu bakilir
rem (tools\check_analyzer_deps.py); degilse paketler yeniden kurulur. Cikis kodu: 0 tamam, 1 eksik/eski, 3 cakisma
rem (Windows'ta islemci "onnxruntime" ile ekran karti "onnxruntime-directml" ayni klasoru kullanir: ikisi birlikte
rem kalamaz; islemci surumu kaldirilir, DirectML zorla yeniden kurulur).
set "PY=%EDGE%\.venv\Scripts\python.exe"
"%PY%" "%ROOT%\tools\check_analyzer_deps.py" >nul 2>&1
set "DEPS=%errorlevel%"
if %DEPS% EQU 0 goto :paketler_tamam
rem Analiz sunucusu calisiyorsa paketler degistirilemez (DLL'leri kilitli): kurulum atlanir, kullanici uyarilir.
curl -s -m 2 http://127.0.0.1:8090/healthz >nul 2>&1
if not errorlevel 1 goto :analiz_calisiyor
if %DEPS% EQU 3 goto :cakisma
echo Analiz sunucusu paketleri guncelleniyor ^(bir kez^)...
"%PY%" -m pip install -q -e "%EDGE%[analyzer]" || goto :hata
rem Eski ortamda yalniz islemci onnxruntime varsa DirectML ancak simdi kuruldu ve ikisi birlikte kaldi: yeniden denetle.
"%PY%" "%ROOT%\tools\check_analyzer_deps.py" >nul 2>&1
if not errorlevel 3 goto :paketler_tamam
:cakisma
echo Islemci onnxruntime kaldirilip ekran karti surumu ^(onnxruntime-directml^) kuruluyor...
"%PY%" -m pip uninstall -y onnxruntime || goto :takas_hata
"%PY%" -m pip install -q --force-reinstall --no-deps "onnxruntime-directml>=1.24" || goto :takas_hata
"%PY%" -m pip install -q -e "%EDGE%[analyzer]" || goto :takas_hata
goto :paketler_tamam
:analiz_calisiyor
echo Analiz sunucusu paketleri guncellenecek: "BandVision analiz" penceresini kapatip kisayolu yeniden calistirin.
:paketler_tamam
if not exist "%DASH%\node_modules\qrcode" (
  echo Panel paketleri kuruluyor ^(ilk sefer ya da yeni paket^)...
  pushd "%DASH%"
  call npm install || goto :hata
  popd
)

curl -s -m 2 http://127.0.0.1:8090/healthz >nul 2>&1
if errorlevel 1 start "BandVision analiz" /min /d "%EDGE%" "%EDGE%\.venv\Scripts\python.exe" -m bantvision.analyzer --port 8090 --log "%LOGS%\analyzer.log"
set "STATE=%DASH%\.local\panel-state.json"
set "NOTICE=%DASH%\.local\panel-notice.txt"
if exist "%NOTICE%" del "%NOTICE%" >nul 2>&1
call :panel_hazir
if errorlevel 1 start "BandVision panel" /min /d "%DASH%" cmd /c "node "%ROOT%\tools\panel_run.mjs" 1>>"%LOGS%\panel.log" 2>&1"

set "SAID_BUILD="
set "SAID_FAIL="
echo BandVision paneli aciliyor...
for /l %%i in (1,1,240) do (
  if exist "%NOTICE%" goto :bildirim
  curl -s -m 2 http://127.0.0.1:8090/healthz >nul 2>&1 && call :panel_hazir && goto :hazir
  if not defined SAID_BUILD findstr /c:"\"state\":\"building\"" "%STATE%" >nul 2>&1 && (echo Panel derleniyor ^(ilk acilis ya da guncelleme, 1-2 dk^)... & set "SAID_BUILD=1")
  if not defined SAID_FAIL findstr /c:"\"state\":\"failed\"" "%STATE%" >nul 2>&1 && (echo Panel derlenemedi; yalnizca bu bilgisayarda gelistirme kipinde aciliyor ^(ayrinti: panel.log^). & set "SAID_FAIL=1")
  rem 1 sn bekle: `timeout`, girdi yonlendirilmisken (konsolsuz calistirma, gorev zamanlayici) hemen cikiyor; ping her yerde bekler
  ping -n 2 127.0.0.1 >nul
)
echo Sunucular 240 saniyede acilmadi. Hata icin "%LOGS%\analyzer.log" ve "%LOGS%\panel.log" dosyalarina bak.
pause
exit /b 1

:bildirim
rem Baslaticinin yazdigi tek satirlik neden (UTF-8; pencere chcp 65001)
type "%NOTICE%"
del "%NOTICE%" >nul 2>&1
pause
exit /b 1

:hazir
if not "%PANEL_PORT%"=="3300" echo Port 3300 dolu; panel %PANEL_PORT% portunda acildi.
start "" http://localhost:%PANEL_PORT%/cameras
exit /b 0

rem Panel calisiyor ve yanit veriyor mu: portu panel.port dosyasindan okur (PANEL_PORT; derlenirken dosya yoktur), o porttaki
rem sayfada "bv-panel" isareti var mi bakar. Cikis 0: hazir.
:panel_hazir
set "PANEL_PORT="
if not exist "%DASH%\.local\panel.port" exit /b 1
set /p PANEL_PORT=<"%DASH%\.local\panel.port"
if not defined PANEL_PORT exit /b 1
curl -s -m 5 -L "http://127.0.0.1:%PANEL_PORT%/login" 2>nul | findstr /c:"bv-panel" >nul 2>&1
exit /b %errorlevel%

:hata
echo Kurulum basarisiz. Python 3.11+ ve Node.js 20+ kurulu mu?
pause
exit /b 1

:takas_hata
echo Ekran karti paketi degistirilemedi; "BandVision analiz" penceresini kapatip kisayolu yeniden calistirin.
echo Baska bir BandVision ya da Python sureci paketleri kilitliyorsa once onu kapatin.
echo Internet baglantisini kontrol edip yeniden deneyin.
pause
exit /b 1
