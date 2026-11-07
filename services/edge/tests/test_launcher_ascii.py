"""Başlatıcı toplu dosyası (tools/panel_baslat.bat) salt ASCII olmalı.

cmd.exe, `chcp 65001` sonrasında toplu dosyayı bayt konumuyla okur; dosyada çok baytlı (UTF-8) karakter varsa sonraki satırlar
kaymış okunur ("cripts\\python.exe" gibi parçalar komut sanılır) ve pencere sessizce kapanır (2026-11-08'de gözlendi).
Kullanıcıya görünen metinler zaten Türkçe karakter kullanmadan yazılıyor; bu test yorumların da ASCII kalmasını sağlar."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_panel_launcher_is_pure_ascii() -> None:
    data = (ROOT / "tools" / "panel_baslat.bat").read_bytes()
    bad = sorted({i + 1 for i, line in enumerate(data.split(b"\n")) if any(b > 127 for b in line)})
    assert not bad, f"ASCII dışı karakter içeren satırlar: {bad}"
    assert b"\r\n" in data, "toplu dosya CRLF satır sonu kullanmalı"
