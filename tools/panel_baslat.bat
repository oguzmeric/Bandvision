@echo off
rem BandVision web paneli (yerel demo): analiz sunucusu + panel, hazır olunca tarayıcı.
rem Çalışıyorlarsa yeniden başlatmaz. Kapatmak için görev çubuğundaki "BandVision analiz" ve
rem "BandVision panel" pencerelerini kapat.
chcp 65001 >nul
setlocal
set "ROOT=%~dp0.."
set "EDGE=%ROOT%\services\edge"
set "DASH=%ROOT%\apps\dashboard"

if not exist "%EDGE%\.venv\Scripts\python.exe" (
  echo Analiz sunucusu ortami kuruluyor ^(ilk sefer, birkac dakika^)...
  python -m venv "%EDGE%\.venv" || goto :hata
  "%EDGE%\.venv\Scripts\python.exe" -m pip install -q -e "%EDGE%[analyzer]" || goto :hata
)
if not exist "%DASH%\node_modules" (
  echo Panel paketleri kuruluyor ^(ilk sefer^)...
  pushd "%DASH%"
  call npm install || goto :hata
  popd
)

curl -s -m 2 http://127.0.0.1:8090/healthz >nul 2>&1
if errorlevel 1 start "BandVision analiz" /min /d "%EDGE%" "%EDGE%\.venv\Scripts\python.exe" -m bantvision.analyzer --port 8090
curl -s -m 2 -o nul http://127.0.0.1:3000/login >nul 2>&1
if errorlevel 1 start "BandVision panel" /min /d "%DASH%" cmd /c "npm run dev"

echo BandVision paneli aciliyor...
for /l %%i in (1,1,60) do (
  curl -s -m 2 http://127.0.0.1:8090/healthz >nul 2>&1 && curl -s -m 5 -o nul http://127.0.0.1:3000/login >nul 2>&1 && goto :hazir
  timeout /t 1 >nul
)
echo Sunucular 60 saniyede acilmadi. "BandVision analiz" ve "BandVision panel" pencerelerindeki hataya bak.
pause
exit /b 1

:hazir
start "" http://localhost:3000/videos
exit /b 0

:hata
echo Kurulum basarisiz. Python 3.11+ ve Node.js 20+ kurulu mu?
pause
exit /b 1
