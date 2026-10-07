"""Canlı sayımın kalıcı ayarları: görüntü kaynakları (IP kamera, kayıt cihazı) ve ürün profilleri.

Dosyalar analiz sunucusunun veri klasöründe (`<ANALYZER_DATA_DIR>/live/`):
- `sources.json`: kaynaklar — **şifre içermez**;
- `secrets.json`: kaynak şifreleri (yalnızca bu sunucu okur; API hiçbir yanıtta şifre döndürmez; POSIX'te 0600);
- `profiles.json`: profiller (sözleşme `contracts/product-profile.schema.json`) — kameraya başlangıç şablonu;
- `camera_profiles.json`: kamera başına kaydedilmiş ayar (alan, çizgi, yön, eşik…): `kaynak|kanal|profil` → profil.
  Her kameranın sahnesi farklı; bir kamerada ayarlanan alan başka kamerayı etkilemez.
Tüm yazmalar kilit altında ve atomik (geçici dosya + yeniden adlandırma).
"""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import threading
import time
import uuid
from typing import Any

from ..core import Profile

# Telefondaki katalogla aynı (apps/ios/BantSayac/Core/ProductCatalog.swift)
CATALOG: list[dict[str, Any]] = [
    {"id": "belt", "title": "Bant üstü ürün", "subtitle": "Banttan geçen ürünleri sayar ve kontrol eder",
     "available": True, "presets": [
         {"key": "egg", "name": "Yumurta"}, {"key": "flour", "name": "Un torbası"},
         {"key": "box", "name": "Koli / kutu"}, {"key": "generic", "name": "Genel ürün"}]},
    {"id": "people", "title": "Kişi sayımı", "subtitle": "Mağaza girişi: giren ve çıkan kişi sayısı",
     "available": True, "presets": [{"key": "people", "name": "Mağaza girişi"}]},
    {"id": "safety", "title": "Güvenlik", "subtitle": "Eller yukarı ve yerde yatan kişi alarmı",
     "available": True, "presets": [{"key": "jeweler", "name": "Kuyumcu güvenliği"}]},
    {"id": "vehicle", "title": "Araç sayımı", "subtitle": "Giriş/çıkış ve otopark doluluğu", "available": False,
     "presets": []},
    {"id": "animal", "title": "Hayvan sayımı", "subtitle": "Koridor geçişi ve ağıl doluluğu", "available": False,
     "presets": []},
    {"id": "stock", "title": "Stok sayımı", "subtitle": "Sera ve depo: sabit kamerayla saksı/ürün sayımı",
     "available": False, "presets": []},
]


def make_preset(key: str) -> Profile:
    makers = {"egg": Profile.egg, "flour": Profile.flour_sack, "box": Profile.box, "generic": Profile,
              "people": Profile.people, "jeweler": Profile.jeweler}
    if key not in makers:
        raise KeyError(key)
    p = makers[key]()
    if key == "people":
        p.name = "Mağaza girişi"
    return p


SOURCE_FIELDS = {"kind", "name", "brand", "host", "port", "channel", "substream", "username", "customUrl",
                 "recorderBrand", "httpPort", "rtspPort"}


class LiveStore:
    def __init__(self, data_dir: pathlib.Path) -> None:
        self.root = data_dir / "live"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        if not (self.root / "profiles.json").exists():
            self._write("profiles.json", [make_preset(k).to_dict() for k in ("egg", "flour", "box", "generic",
                                                                                "people")])

    # ------------------------------------------------------------------ dosya

    def _read(self, name: str, default: Any) -> Any:
        p = self.root / name
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def _write(self, name: str, data: Any) -> None:
        p = self.root / name
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if name == "secrets.json":
            with contextlib.suppress(OSError):                # Windows'ta POSIX izni yok
                os.chmod(tmp, 0o600)
        os.replace(tmp, p)

    # ------------------------------------------------------------------ kaynaklar

    def sources(self) -> list[dict[str, Any]]:
        with self._lock:
            secrets = self._read("secrets.json", {})
            return [{**s, "hasPassword": bool(secrets.get(s["id"]))} for s in self._read("sources.json", [])]

    def source(self, source_id: str) -> dict[str, Any] | None:
        return next((s for s in self.sources() if s["id"] == source_id), None)

    def password(self, source_id: str) -> str:
        with self._lock:
            return str(self._read("secrets.json", {}).get(source_id, ""))

    def save_source(self, data: dict[str, Any], password: str | None, source_id: str | None = None
                    ) -> dict[str, Any]:
        """`password` None: kayıtlı şifre korunur (düzenlemede şifre yeniden yazılmaz)."""
        with self._lock:
            items = self._read("sources.json", [])
            clean = {k: v for k, v in data.items() if k in SOURCE_FIELDS}
            if source_id is None:
                source_id = str(uuid.uuid4())
                items.append({"id": source_id, "createdAt": time.time(), **clean})
            else:
                for i, s in enumerate(items):
                    if s["id"] == source_id:
                        items[i] = {"id": source_id, "createdAt": s.get("createdAt", time.time()), **clean}
                        break
                else:
                    raise KeyError(source_id)
            self._write("sources.json", items)
            if password is not None:
                secrets = self._read("secrets.json", {})
                if password:
                    secrets[source_id] = password
                else:
                    secrets.pop(source_id, None)
                self._write("secrets.json", secrets)
        src = self.source(source_id)
        assert src is not None
        return src

    def delete_source(self, source_id: str) -> bool:
        with self._lock:
            items = self._read("sources.json", [])
            keep = [s for s in items if s["id"] != source_id]
            if len(keep) == len(items):
                return False
            self._write("sources.json", keep)
            secrets = self._read("secrets.json", {})
            if secrets.pop(source_id, None) is not None:
                self._write("secrets.json", secrets)
            self._drop_camera_profiles(lambda k: k.split("|")[0] == source_id)
            return True

    # ------------------------------------------------------------------ profiller

    def profiles(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._read("profiles.json", []))

    def profile(self, profile_id: str) -> Profile | None:
        d = next((p for p in self.profiles() if p.get("id") == profile_id), None)
        return Profile.from_dict(d) if d else None

    def save_profile(self, profile: Profile) -> dict[str, Any]:
        d = profile.to_dict()
        with self._lock:
            items = self._read("profiles.json", [])
            for i, p in enumerate(items):
                if p.get("id") == profile.id:
                    items[i] = d
                    break
            else:
                items.append(d)
            self._write("profiles.json", items)
        return d

    def delete_profile(self, profile_id: str) -> bool:
        with self._lock:
            items = self._read("profiles.json", [])
            keep = [p for p in items if p.get("id") != profile_id]
            if len(keep) == len(items) or not keep:          # son profil silinmez
                return False
            self._write("profiles.json", keep)
            self._drop_camera_profiles(lambda k: k.split("|")[-1] == profile_id)
            return True

    # ------------------------------------------------------------------ kamera başına ayar

    @staticmethod
    def camera_key(source_id: str, channel_id: str | None, profile_id: str) -> str:
        return f"{source_id}|{channel_id or ''}|{profile_id}"

    def camera_profile(self, source_id: str, channel_id: str | None, profile_id: str) -> Profile | None:
        """Bu kamerada bu profille kaydedilmiş ayar; yoksa None (şablon kullanılır)."""
        with self._lock:
            d = self._read("camera_profiles.json", {}).get(self.camera_key(source_id, channel_id, profile_id))
        return Profile.from_dict(d) if d else None

    def save_camera_profile(self, source_id: str, channel_id: str | None, profile: Profile) -> dict[str, Any]:
        d = profile.to_dict()
        with self._lock:
            items = self._read("camera_profiles.json", {})
            items[self.camera_key(source_id, channel_id, profile.id)] = d
            self._write("camera_profiles.json", items)
        return d

    # ------------------------------------------------------------------ bildirim (Telegram)

    def notify_config(self) -> dict[str, Any]:
        """Bildirim ayarı; bot anahtarı hiçbir zaman döndürülmez (yalnızca `hasToken`)."""
        with self._lock:
            c = self._read("notify.json", {})
            return {"enabled": bool(c.get("enabled", False)), "chatId": str(c.get("chatId", "")),
                    "hasToken": bool(self._read("secrets.json", {}).get("telegram"))}

    def save_notify(self, enabled: bool, chat_id: str, token: str | None) -> dict[str, Any]:
        """`token` None: kayıtlı anahtar korunur; "": silinir. Anahtar yalnızca secrets.json'da."""
        with self._lock:
            self._write("notify.json", {"enabled": enabled, "chatId": chat_id.strip()})
            if token is not None:
                secrets = self._read("secrets.json", {})
                if token.strip():
                    secrets["telegram"] = token.strip()
                else:
                    secrets.pop("telegram", None)
                self._write("secrets.json", secrets)
            return self.notify_config()

    def telegram_token(self) -> str:
        with self._lock:
            return str(self._read("secrets.json", {}).get("telegram", ""))

    def _drop_camera_profiles(self, match: Any) -> None:
        with self._lock:
            items = self._read("camera_profiles.json", {})
            keep = {k: v for k, v in items.items() if not match(k)}
            if len(keep) != len(items):
                self._write("camera_profiles.json", keep)
