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
    reqs = dict(cd.requirements())
    assert reqs["numpy"] == "1.26" and reqs["opencv-python-headless"] == "4.9"
    assert reqs["uvicorn"] == "0.30" and reqs["psutil"] == "5.9"
    assert {"fastapi", "httpx", "onnxruntime", "pillow", "python-multipart", "imageio-ffmpeg"} <= set(reqs)
    assert "pytest" not in reqs and "zeroconf" not in reqs                       # dev / service ekleri değil


def test_missing_package_added_by_an_update_is_reported() -> None:
    """Eski kurulum: psutil sonradan eklendi, kurulu değil (eski denetim yalnız httpx, onnxruntime, PIL'e bakıyordu)."""
    reqs = cd.requirements()
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
