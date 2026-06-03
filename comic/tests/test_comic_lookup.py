#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "comic_lookup.py"


def load_mod():
    spec = importlib.util.spec_from_file_location("comic_lookup", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_resolve_download_dir_stays_under_download():
    mod = load_mod()
    root = mod.download_root()

    assert mod.resolve_download_dir() == root
    assert mod.resolve_download_dir("/download") == root
    assert mod.resolve_download_dir("comic") == root / "comic"

    with pytest.raises(RuntimeError):
        mod.resolve_download_dir("/tmp")
    with pytest.raises(RuntimeError):
        mod.resolve_download_dir("../escape")

def test_cleanup_download_root_removes_old_files(tmp_path):
    mod = load_mod()
    original_root = mod.DOWNLOAD_ROOT
    mod.DOWNLOAD_ROOT = tmp_path
    try:
        root = mod.download_root()
        marker = root / "comic-old-test.tmp"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("old", encoding="utf-8")
        old_time = mod.time.time() - mod.DOWNLOAD_MAX_AGE_SECONDS - 60
        mod.os.utime(marker, (old_time, old_time))

        mod.cleanup_download_root()

        assert not marker.exists()
    finally:
        mod.DOWNLOAD_ROOT = original_root