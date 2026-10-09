@echo off
rem BandVision web paneli (yerel demo): analiz sunucusu + panel, hazır olunca tarayıcı.
rem Çalışıyorlarsa yeniden başlatmaz. Kapatmak için görev çubuğundaki "BandVision analiz" ve
rem "BandVision panel" pencerelerini kapat. Günlükler: .logs\analyzer.log ve .logs\panel.log
rem (Pencere içinde metin seçmek Windows'ta yazan süreci durdurur; bu yüzden çıktı dosyaya gider.)
rem Panel başlatıcısı (tools\panel_run.mjs) tek kopya çalışır; yerel ağ kipinde ilk açılışta üretim derlemesi 1-2 dk
rem sürer: başlatıcının durum dosyası (apps\dashboard\.local\panel-state.json) "building" iken bu pencere bunu yazar ve
rem en çok 240 sn bekler.
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
rem Eski kurulumda canli sayim paketleri (kamera/NVR baglantisi, kisi tanima) yoksa tamamla
"%EDGE%\.venv\Scripts\python.exe" -c "import httpx, onnxruntime, PIL" >nul 2>&1
if errorlevel 1 (
  echo Canli sayim paketleri kuruluyor ^(bir kez^)...
  "%EDGE%\.venv\Scripts\python.exe" -m pip install -q -e "%EDGE%[analyzer]" || goto :hata
)
if not exist "%DASH%\node_modules\qrcode" (
  echo Panel paketleri kuruluyor ^(ilk sefer ya da yeni paket^)...
  pushd "%DASH%"
  call npm install || goto :hata
  popd
)

curl -s -m 2 http://127.0.0.1:8090/healthz >nul 2>&1
if errorlevel 1 start "BandVision analiz" /min /d "%EDGE%" "%EDGE%\.venv\Scripts\python.exe" -m bantvision.analyzer --port 8090 --log "%LOGS%\analyzer.log"
curl -s -m 2 -o nul http://127.0.0.1:3000/login >nul 2>&1
if errorlevel 1 start "BandVision panel" /min /d "%DASH%" cmd /c "node "%ROOT%\tools\panel_run.mjs" 1>>"%LOGS%\panel.log" 2>&1"

set "STATE=%DASH%\.local\panel-state.json"
set "SAID_BUILD="
set "SAID_FAIL="
echo BandVision paneli aciliyor...
for /l %%i in (1,1,240) do (
  curl -s -m 2 http://127.0.0.1:8090/healthz >nul 2>&1 && curl -s -m 5 -o nul http://127.0.0.1:3000/login >nul 2>&1 && goto :hazir
  if not defined SAID_BUILD findstr /c:"\"state\":\"building\"" "%STATE%" >nul 2>&1 && (echo Panel derleniyor ^(ilk acilis 1-2 dk^)... & set "SAID_BUILD=1")
  if not defined SAID_FAIL findstr /c:"\"state\":\"failed\"" "%STATE%" >nul 2>&1 && (echo Yerel ag icin derleme basarisiz; panel yalnizca bu bilgisayarda aciliyor ^(ayrinti: panel.log^). & set "SAID_FAIL=1")
  timeout /t 1 >nul
)
echo Sunucular 240 saniyede acilmadi. Hata icin "%LOGS%\analyzer.log" ve "%LOGS%\panel.log" dosyalarina bak.
pause
exit /b 1

:hazir
start "" http://localhost:3000/cameras
exit /b 0

:hata
echo Kurulum basarisiz. Python 3.11+ ve Node.js 20+ kurulu mu?
pause
exit /b 1
