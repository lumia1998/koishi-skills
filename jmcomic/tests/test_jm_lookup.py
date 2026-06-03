#!/usr/bin/env python3
"""Tests for jm_lookup.py — no network, no real service."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "jm_lookup.py"


def load_mod():
    spec = importlib.util.spec_from_file_location("jm_lookup", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def run(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        capture_output=True,
        text=True,
        input=input_text,
    )


def test_doctor_runs_without_network():
    r = run("--no-auto-deploy", "--api-base", "http://127.0.0.1:19999", "doctor")
    assert r.returncode == 0
    assert "API base" in r.stdout
    assert "Auto deploy" in r.stdout


def test_default_api_base_uses_dedicated_port():
    mod = load_mod()

    assert mod.DEFAULT_API_BASE == "http://127.0.0.1:8700"
    assert mod._port_from_base("http://127.0.0.1") == 8700

def test_health_probe_uses_fastapi_liveness(monkeypatch):
    mod = load_mod()
    called = []

    def fake_get_json(url: str, timeout: int = 15):
        called.append((url, timeout))
        return {"status": "ok"}

    monkeypatch.setattr(mod, "_get_json", fake_get_json)

    assert mod.is_service_running("http://api.local:8699") is True
    assert called == [("http://api.local:8699/health/live", 3)]


def test_search_uses_fastapi_search_endpoint(monkeypatch):
    mod = load_mod()
    called = []

    def fake_get_json(url: str, timeout: int = 15):
        called.append(url)
        return {
            "success": True,
            "data": {"results": [{"id": 12345, "title": "测试 标题"}]},
        }

    monkeypatch.setattr(mod, "_get_json", fake_get_json)

    results = mod.search("http://api.local:8699", "测试 关键词", page=2)

    assert results == [{"id": "12345", "title": "测试 标题"}]
    assert called == ["http://api.local:8699/search?query=%E6%B5%8B%E8%AF%95+%E5%85%B3%E9%94%AE%E8%AF%8D&page=2"]


def test_get_pdf_uses_streaming_fastapi_endpoint(monkeypatch, tmp_path):
    mod = load_mod()
    called = []

    def fake_download(url: str, out_dir: Path, fallback_filename: str, timeout: int = 900):
        called.append((url, out_dir, fallback_filename, timeout))
        path = out_dir / fallback_filename
        path.write_bytes(b"%PDF-1.4\n")
        return path

    monkeypatch.setattr(mod, "_download_binary", fake_download)

    pdf = mod.get_pdf("http://api.local:8699", "JM12345", tmp_path, timeout=123)

    assert pdf == tmp_path / "12345.pdf"
    assert called == [
        (
            "http://api.local:8699/get_pdf/12345?pdf=true&passwd=true&Titletype=2",
            tmp_path,
            "12345.pdf",
            123,
        )
    ]


def test_search_no_service_and_no_auto_deploy_fails_fast():
    r = run(
        "--no-auto-deploy",
        "--api-base",
        "http://127.0.0.1:19999",
        "search",
        "test",
    )
    assert r.returncode != 0
    assert "not running" in r.stderr or "error=" in r.stderr


def test_resolve_download_dir_stays_under_download():
    mod = load_mod()
    root = mod.download_root()

    assert mod.resolve_download_dir() == root
    assert mod.resolve_download_dir("/download") == root
    assert mod.resolve_download_dir("jmcomic") == root / "jmcomic"

    with pytest.raises(RuntimeError):
        mod.resolve_download_dir("../escape")


def test_cleanup_download_root_removes_old_files(tmp_path):
    mod = load_mod()
    original_root = mod.DOWNLOAD_ROOT
    mod.DOWNLOAD_ROOT = tmp_path
    try:
        root = mod.download_root()
        marker = root / "jm-old-test.tmp"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("old", encoding="utf-8")
        old_time = mod.time.time() - mod.DOWNLOAD_MAX_AGE_SECONDS - 60
        mod.os.utime(marker, (old_time, old_time))

        mod.cleanup_download_root()

        assert not marker.exists()
    finally:
        mod.DOWNLOAD_ROOT = original_root
def test_config_local_json_loads(tmp_path):
    mod = load_mod()
    cfg = tmp_path / "config.local.json"
    cfg.write_text(json.dumps({"api_base": "http://127.0.0.1:8700"}), encoding="utf-8")

    assert mod.load_local_config(cfg) == {"api_base": "http://127.0.0.1:8700"}


def test_clean_album_id_strips_jm_prefix():
    mod = load_mod()

    assert mod.clean_album_id("JM12345") == "12345"
    assert mod.clean_album_id("jm12345") == "12345"
    assert mod.clean_album_id("jmid12345") == "12345"
    assert mod.clean_album_id("jm id: 12345") == "12345"
    assert mod.clean_album_id("jm号12345") == "12345"
    assert mod.clean_album_id("禁漫12345") == "12345"
    assert mod.clean_album_id("12345") == "12345"


def test_expand_path_expands_home():
    mod = load_mod()

    assert mod.expand_path("~/services/JMComic-Api").startswith(str(Path.home()))


def test_skill_description_claims_generic_benzi_and_jm_triggers():
    skill_text = (SCRIPT.parents[1] / "SKILL.md").read_text(encoding="utf-8")

    for phrase in ["推荐点本子", "我要看xxx的本子", "jmid12345", "禁漫12345", "禁漫搜xxx"]:
        assert phrase in skill_text
    assert "Prefer this over pica" in skill_text
    assert "哔咔" in skill_text
