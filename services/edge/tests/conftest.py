"""Tüm edge testleri için ortak koruma: testte hiçbir model İNDİRİLMEZ ve önbellekteki gerçek model de sessizce
YÜKLENMEZ (CI'da önbellek yok: indirme GitHub'a giderdi; yerelde gerçek model yavaş ve deterministik değil).

- `BANTVISION_MODEL_DIR` oturum boyunca boş geçici klasör: model gerektiren her yol indirmeye düşer.
- `urllib.request.urlopen` (model indirmenin tek giriş noktası, core/model_download.py) yasak: çağrılırsa
  `RuntimeError("testte model indirme yasak")` fırlar ve girişim kaydedilir; o test (ya da önceki testin arka plan
  yükleyicisi) başarısız sayılır.
- İndirme yardımcısının kendi testleri `urlopen`'ı kendileri sahteler (o testte yasak devre dışı kalır, test bitince
  geri gelir). Gerçek model duman testi önbellekteki dosyayı doğrudan açar (yoksa atlanır, asla indirmez).
"""
from __future__ import annotations

import urllib.request
from collections.abc import Iterator

import pytest

_ATTEMPTS: list[str] = []


def _forbidden(url: object, *_a: object, **_k: object) -> object:
    _ATTEMPTS.append(str(getattr(url, "full_url", url)))
    raise RuntimeError("testte model indirme yasak")


@pytest.fixture(scope="session", autouse=True)
def _no_model_download(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("BANTVISION_MODEL_DIR", str(tmp_path_factory.mktemp("modeller-bos")))
        mp.setattr(urllib.request, "urlopen", _forbidden)
        yield


@pytest.fixture(autouse=True)
def _assert_no_download_attempt() -> Iterator[None]:
    before = len(_ATTEMPTS)
    yield
    tried = _ATTEMPTS[before:]
    assert not tried, f"test model indirmeye çalıştı (gerçek model yerine sahte verin): {tried}"
