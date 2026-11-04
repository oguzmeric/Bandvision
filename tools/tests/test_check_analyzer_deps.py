"""Başlatıcının bağımlılık denetimi (tools/check_analyzer_deps.py): güncellemeyle eklenen paket eski kurulumda eksikse
yakalanır, başlatıcı paketleri yeniden kurar. Yalnızca standart kütüphane; kurulu paketler sahtelenir."""
from __future__ import annotations

import importlib.metadata
import pathlib
from collections.abc import Callable

import check_analyzer_deps as cd
import pytest


def _version(installed: dict[str, str]) -> Callable[[str], str]:
    """Sahte `importlib.metadata.version`: yalnızca verilen paketler kurulu."""

    def version(name: str) -> str:
        if name not in installed:
            raise importlib.metadata.PackageNotFoundError(name)
        return installed[name]
    return version


def test_reads_runtime_dependencies_from_source_pyproject() -> None:
    """Kaynak pyproject.toml okunur: çekirdek + analyzer eki; ekler ([standard]) atılır, alt sürüm kalır. Durum şeridinin
    işlemci yükü için psutil analyzer ekinde bildirilmiştir."""
    reqs = dict(cd.requirements(platform="linux"))
    assert reqs["numpy"] == "1.26" and reqs["opencv-python-headless"] == "4.9"
    assert reqs["uvicorn"] == "0.30" and reqs["psutil"] == "5.9"
    assert {"fastapi", "httpx", "onnxruntime", "pillow", "python-multipart", "imageio-ffmpeg"} <= set(reqs)
    assert "pytest" not in reqs and "zeroconf" not in reqs                       # dev / service ekleri değil


def test_missing_package_added_by_an_update_is_reported() -> None:
    """Eski kurulum: psutil sonradan eklendi, kurulu değil (eski denetim yalnız httpx, onnxruntime, PIL'e bakıyordu)."""
    reqs = cd.requirements(platform="linux")
    old_env = {name: "99" for name, _ in reqs if name != "psutil"}
    assert cd.problems(reqs, _version(old_env)) == ["psutil: kurulu değil"]
    assert cd.problems(reqs, _version({**old_env, "psutil": "7.2.2"})) == []


def test_too_old_version_is_reported_and_versions_compare_numerically() -> None:
    reqs = [("fastapi", "0.115"), ("pillow", "10.1"), ("numpy", "1.26"), ("x", None)]
    env = {"fastapi": "0.99.1", "pillow": "10.1.0", "numpy": "1.26.0rc1", "x": "0"}
    assert cd.problems(reqs, _version(env)) == ["fastapi: 0.99.1 kurulu, en az 0.115 gerekli"]
    assert cd.problems(reqs, _version({**env, "fastapi": "0.142.2"})) == []
    assert cd._release("1.18.0") == cd._release("1.18") < cd._release("1.18.1") < cd._release("1.180")


def test_requirements_parsing_handles_extras_markers_and_bare_names(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "pyproject.toml"
    p.write_text('[project]\nname = "x"\ndependencies = ["a>=1.2", "b"]\n'
                 '[project.optional-dependencies]\nanalyzer = ["c[standard] >= 3", "d>=4; python_version >= \'3.11\'"]\n'
                 'dev = ["e>=5"]\n', encoding="utf-8")
    assert cd.requirements(p) == [("a", "1.2"), ("b", None), ("c", "3"), ("d", "4")]


def test_app_module_must_import() -> None:
    assert cd.import_problem("json") is None
    err = cd.import_problem("bantvision_boyle_bir_modul_yok")
    assert err is not None and err.startswith("bantvision_boyle_bir_modul_yok açılmıyor: ModuleNotFoundError")


def test_main_exit_code(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "pyproject.toml"
    p.write_text('[project]\nname = "x"\ndependencies = ["pytest>=1"]\n', encoding="utf-8")
    assert cd.main(p, "json") == 0 and capsys.readouterr().out == ""
    assert cd.main(p, "bantvision_boyle_bir_modul_yok") == 1
    p.write_text('[project]\nname = "x"\ndependencies = ["boyle-bir-paket-yok-xyz>=1"]\n', encoding="utf-8")
    assert cd.main(p, "json") == 1
    assert capsys.readouterr().out.splitlines()[-1] == "boyle-bir-paket-yok-xyz: kurulu değil"


def test_platform_markers_pick_the_matching_onnxruntime_package() -> None:
    """Gerçek pyproject.toml: Linux/CI işlemci sürümünü, Windows ekran kartı (DirectML) sürümünü ister; ikisini birden değil."""
    linux = dict(cd.requirements(platform="linux"))
    win = dict(cd.requirements(platform="win32"))
    assert linux["onnxruntime"] == "1.18" and "onnxruntime-directml" not in linux
    assert win["onnxruntime-directml"] == "1.24" and "onnxruntime" not in win
    assert {n for n, _ in cd.requirements(extra="detect", platform="linux")} >= {"onnxruntime", "pillow"}
    assert {n for n, _ in cd.requirements(extra="detect", platform="win32")} >= {"onnxruntime-directml", "pillow"}
    assert linux.keys() - {"onnxruntime"} == win.keys() - {"onnxruntime-directml"}          # geri kalan her şey aynı


def test_marker_evaluation_is_limited_to_sys_platform_equality(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "pyproject.toml"
    p.write_text("""[project]
name = "x"
dependencies = []
[project.optional-dependencies]
analyzer = [
  "a>=1; sys_platform == 'win32'", "b>=1; sys_platform != 'win32'",
  "c>=1; sys_platform == \\"linux\\"", "d>=1; python_version >= '3.11'",
  "e>=1; sys_platform in 'linux'", "f>=1;sys_platform=='darwin'",
  "g>=1; sys_platform == 'win32' and python_version >= '3.11'",
  "h>=1; sys_platform != 'win32' and python_version >= '3.11'",
  "i>=1; extra == 'x'", "j>=1; sys_platform == 'win32' or sys_platform == 'linux'",
]
""", encoding="utf-8")

    def names(platform: str) -> list[str]:
        return [n for n, _ in cd.requirements(p, platform=platform)]
    # e: desteklenmeyen işleç, d: python_version, g/h/j: bileşik (and/or), i: extra → hepsi her platformda doğru sayılır
    assert names("win32") == ["a", "d", "e", "g", "h", "i", "j"]
    assert names("linux") == ["b", "c", "d", "e", "g", "h", "i", "j"]
    assert names("darwin") == ["b", "d", "e", "f", "g", "h", "i", "j"]
    assert cd.requirements(p, platform="win32")[1] == ("d", "1")   # python_version işaretli bağımlılık sürümüyle kalır



def OK(name: str) -> bool:  # sahte "dosyalar yerinde" denetimi
    return True


CONFLICT = ("onnxruntime (işlemci sürümü) ekran kartı sürümüyle (onnxruntime-directml) aynı klasörü kullanıyor; "
            "kaldırılmalı")


def test_conflict_between_cpu_and_directml_onnxruntime_on_windows() -> None:
    reqs = [("numpy", "1.26"), ("onnxruntime-directml", "1.24")]
    both = {"onnxruntime": "1.30.0", "onnxruntime-directml": "1.24.4"}
    assert cd.conflicts(reqs, installed=both, platform="win32") == [CONFLICT]
    assert cd.conflicts(reqs, installed={"onnxruntime-directml": "1.24.4"}, platform="win32") == []   # işlemci sürümü yok
    assert cd.conflicts(reqs, installed={"onnxruntime": "1.30.0"}, platform="win32") == []            # DirectML henüz yok
    assert cd.conflicts(reqs, installed=both, platform="linux") == []                                 # yalnız Windows
    assert cd.conflicts([("numpy", "1.26")], installed=both, platform="win32") == []                  # DirectML istenmiyor


def _project(tmp_path: pathlib.Path, deps: str) -> pathlib.Path:
    p = tmp_path / "pyproject.toml"
    p.write_text(f'[project]\nname = "x"\ndependencies = {deps}\n', encoding="utf-8")
    return p


def test_main_exit_codes_conflict_beats_missing(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _project(tmp_path, """["onnxruntime-directml>=1.24; sys_platform == 'win32'", "boyle-bir-paket-yok-xyz>=1"]""")
    both = {"onnxruntime": "1.30.0", "onnxruntime-directml": "1.24.4"}
    # çakışma + eksik paket birlikte: 3 (çakışma önce çözülmeli), iki satır da yazılır
    assert cd.main(p, "json", version=_version(both), platform="win32", files_present=OK) == 3
    assert capsys.readouterr().out.splitlines() == ["boyle-bir-paket-yok-xyz: kurulu değil", CONFLICT]
    # yalnız eksik paket: 1
    assert cd.main(p, "json", version=_version({"onnxruntime-directml": "1.24.4"}), platform="win32", files_present=OK) == 1
    assert capsys.readouterr().out.splitlines() == ["boyle-bir-paket-yok-xyz: kurulu değil"]
    # her şey tamam: 0
    ok = _project(tmp_path, """["onnxruntime-directml>=1.24; sys_platform == 'win32'"]""")
    assert cd.main(ok, "json", version=_version({"onnxruntime-directml": "1.24.4"}), platform="win32", files_present=OK) == 0
    assert capsys.readouterr().out == ""
    # yalnız çakışma (paketler tamam): yine 3
    assert cd.main(ok, "json", version=_version(both), platform="win32", files_present=OK) == 3
    assert capsys.readouterr().out.splitlines() == [CONFLICT]
    # Linux'ta aynı kurulum çakışma sayılmaz (DirectML işaretle elenir, işlemci sürümü yeterli)
    lin = _project(tmp_path, """["onnxruntime>=1.18; sys_platform != 'win32'"]""")
    assert cd.main(lin, "json", version=_version({"onnxruntime": "1.30.0"}), platform="linux", files_present=OK) == 0


def test_first_update_on_a_machine_with_cpu_onnxruntime_goes_missing_then_conflict(tmp_path: pathlib.Path) -> None:
    """Başlatıcının iki aşamalı yolu: eski ortamda yalnız işlemci onnxruntime var → 1 (DirectML eksik); pip DirectML'i
    ekleyince ikisi birlikte → 3 (başlatıcı işlemci sürümünü kaldırıp DirectML'i zorla yeniden kurar); sonra 0."""
    p = _project(tmp_path, """["onnxruntime-directml>=1.24; sys_platform == 'win32'"]""")
    assert cd.main(p, "json", version=_version({"onnxruntime": "1.30.0"}), platform="win32", files_present=OK) == 1
    both = {"onnxruntime": "1.30.0", "onnxruntime-directml": "1.24.4"}
    assert cd.main(p, "json", version=_version(both), platform="win32", files_present=OK) == 3
    assert cd.main(p, "json", version=_version({"onnxruntime-directml": "1.24.4"}), platform="win32", files_present=OK) == 0


def test_directml_registered_but_files_missing_is_reported_as_repair(
        tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Değiştirme yarıda kalırsa (işlemci sürümü kaldırıldı, DirectML'in zorla kurulumu başarısız) DirectML'in kaydı kalır
    ama ortak onnxruntime klasörü yoktur: kayıt, sürüm ve uygulama modülü denetimleri geçse de dosyalar eksikse 3 döner
    (başlatıcı çakışma adımını izler: kaldırma boşa geçer, DirectML zorla yeniden kurulur)."""
    p = _project(tmp_path, """["onnxruntime-directml>=1.24; sys_platform == 'win32'"]""")
    only_dml = _version({"onnxruntime-directml": "1.24.4"})
    repair = "onnxruntime-directml: kayıtlı ama dosyaları eksik (kurulum yarım kalmış); yeniden kurulmalı"
    reqs = cd.requirements(p, platform="win32")
    assert cd.damaged(reqs, {"onnxruntime-directml": "1.24.4"}, "win32", lambda n: False) == [repair]
    assert cd.damaged(reqs, {"onnxruntime-directml": "1.24.4"}, "win32", lambda n: True) == []
    assert cd.damaged(reqs, {}, "win32", lambda n: False) == []                       # kurulu değil: eksik olarak 1
    assert cd.damaged(reqs, {"onnxruntime-directml": "1.24.4"}, "linux", lambda n: False) == []
    assert cd.main(p, "json", version=only_dml, platform="win32", files_present=lambda n: False) == 3
    assert capsys.readouterr().out.splitlines() == [repair]
    assert cd.main(p, "json", version=only_dml, platform="win32", files_present=lambda n: True) == 0
    assert capsys.readouterr().out == ""
    # DirectML kurulu değilken dosya denetimi hiç çağrılmaz: eksik paket 1 kalır
    def boom(name: str) -> bool:
        raise AssertionError("kurulu olmayan dağıtım için çağrılmamalı")
    assert cd.main(p, "json", version=_version({}), platform="win32", files_present=boom) == 1


def test_dist_files_present_looks_at_registered_native_libraries(tmp_path: pathlib.Path,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """Gerçek denetim: dist-info'daki .pyd/.dll dosyalarından biri bile yoksa False."""
    site = tmp_path / "site"
    (site / "fakedml-1.0.dist-info").mkdir(parents=True)
    info = site / "fakedml-1.0.dist-info"
    info.joinpath("METADATA").write_text(chr(10).join(["Metadata-Version: 2.1", "Name: fakedml", "Version: 1.0", ""]))
    info.joinpath("RECORD").write_text(chr(10).join(
        ["fakedml/__init__.py,,", "fakedml/native.pyd,,", "fakedml/lib.dll,,", "fakedml-1.0.dist-info/METADATA,,", ""]))
    monkeypatch.syspath_prepend(str(site))
    assert cd.dist_files_present("fakedml") is False                  # kayıt var, dosyalar yok
    (site / "fakedml").mkdir()
    (site / "fakedml" / "native.pyd").write_bytes(b"")
    assert cd.dist_files_present("fakedml") is False                  # biri hâlâ eksik
    (site / "fakedml" / "lib.dll").write_bytes(b"")
    assert cd.dist_files_present("fakedml") is True


def test_dist_files_present_unreadable_record_counts_as_ok(tmp_path: pathlib.Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """Okunamayan RECORD (bozuk kodlama, CSV hatası, erişim hatası) denetimi çökertmez: karar verilemez, tamam sayılır."""
    site = tmp_path / "site"
    info = site / "fakedml-1.0.dist-info"
    info.mkdir(parents=True)
    info.joinpath("METADATA").write_text(chr(10).join(["Metadata-Version: 2.1", "Name: fakedml", "Version: 1.0", ""]))
    info.joinpath("RECORD").write_bytes(b"fakedml/native.pyd,,\n\xff\xfe\xfa bozuk\n")
    monkeypatch.syspath_prepend(str(site))
    assert cd.dist_files_present("fakedml") is True                   # UnicodeDecodeError
    info.joinpath("RECORD").write_text("fakedml/native.pyd,,\n")
    assert cd.dist_files_present("fakedml") is False                  # okunabilir: dosya yok

    def csv_boom(*a: object, **k: object) -> object:
        raise cd.csv.Error("field larger than field limit")

    monkeypatch.setattr(cd.csv, "reader", csv_boom)
    assert cd.dist_files_present("fakedml") is True                   # csv.Error
    monkeypatch.undo()
    monkeypatch.syspath_prepend(str(site))

    def os_boom(self: object, filename: str) -> str:
        raise PermissionError(13, "erişim reddedildi")

    monkeypatch.setattr(importlib.metadata.PathDistribution, "read_text", os_boom)
    assert cd.dist_files_present("fakedml") is True                   # OSError
