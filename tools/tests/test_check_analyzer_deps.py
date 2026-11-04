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
]
""", encoding="utf-8")

    def names(platform: str) -> list[str]:
        return [n for n, _ in cd.requirements(p, platform=platform)]
    assert names("win32") == ["a", "d", "e"]          # e: desteklenmeyen işleç → doğru sayılır; d: python_version doğru
    assert names("linux") == ["b", "c", "d", "e"]
    assert names("darwin") == ["b", "d", "e", "f"]
    assert cd.requirements(p, platform="win32")[1] == ("d", "1")   # python_version işaretli bağımlılık sürümüyle kalır


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
    assert cd.main(p, "json", version=_version(both), platform="win32") == 3
    assert capsys.readouterr().out.splitlines() == ["boyle-bir-paket-yok-xyz: kurulu değil", CONFLICT]
    # yalnız eksik paket: 1
    assert cd.main(p, "json", version=_version({"onnxruntime-directml": "1.24.4"}), platform="win32") == 1
    assert capsys.readouterr().out.splitlines() == ["boyle-bir-paket-yok-xyz: kurulu değil"]
    # her şey tamam: 0
    ok = _project(tmp_path, """["onnxruntime-directml>=1.24; sys_platform == 'win32'"]""")
    assert cd.main(ok, "json", version=_version({"onnxruntime-directml": "1.24.4"}), platform="win32") == 0
    assert capsys.readouterr().out == ""
    # yalnız çakışma (paketler tamam): yine 3
    assert cd.main(ok, "json", version=_version(both), platform="win32") == 3
    assert capsys.readouterr().out.splitlines() == [CONFLICT]
    # Linux'ta aynı kurulum çakışma sayılmaz (DirectML işaretle elenir, işlemci sürümü yeterli)
    lin = _project(tmp_path, """["onnxruntime>=1.18; sys_platform != 'win32'"]""")
    assert cd.main(lin, "json", version=_version({"onnxruntime": "1.30.0"}), platform="linux") == 0


def test_first_update_on_a_machine_with_cpu_onnxruntime_goes_missing_then_conflict(tmp_path: pathlib.Path) -> None:
    """Başlatıcının iki aşamalı yolu: eski ortamda yalnız işlemci onnxruntime var → 1 (DirectML eksik); pip DirectML'i
    ekleyince ikisi birlikte → 3 (başlatıcı işlemci sürümünü kaldırıp DirectML'i zorla yeniden kurar); sonra 0."""
    p = _project(tmp_path, """["onnxruntime-directml>=1.24; sys_platform == 'win32'"]""")
    assert cd.main(p, "json", version=_version({"onnxruntime": "1.30.0"}), platform="win32") == 1
    both = {"onnxruntime": "1.30.0", "onnxruntime-directml": "1.24.4"}
    assert cd.main(p, "json", version=_version(both), platform="win32") == 3
    assert cd.main(p, "json", version=_version({"onnxruntime-directml": "1.24.4"}), platform="win32") == 0
