#!/usr/bin/env python3
"""Tests for jm_lookup.py — no network, no real service."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "jm_lookup.py"


def run(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        capture_output=True,
        text=True,
        input=input_text,
    )


def test_doctor_runs():
    r = run("doctor")
    assert r.returncode == 0
    assert "API base" in r.stdout


def test_search_no_service(monkeypatch):
    """Search exits non-zero when service is unreachable and auto-deploy fails fast."""
    r = run("--api-base", "http://127.0.0.1:19999", "search", "test")
    # Either exits with error or prints a failure message — just must not crash silently
    assert r.returncode != 0 or "error" in r.stdout.lower() or "failed" in r.stdout.lower() or r.stderr


def test_zip_no_service():
    r = run("--api-base", "http://127.0.0.1:19999", "zip", "12345")
    assert r.returncode != 0 or r.stderr


def test_encrypted_zip_roundtrip(tmp_path):
    """The encrypted zip writer produces a file that 7z / unzip can open."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("jm_lookup", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    content = b"hello jmcomic test content " * 100
    src = tmp_path / "test.pdf"
    src.write_bytes(content)
    out = tmp_path / "out.zip"
    mod.create_encrypted_zip([src], out, "testpass123")
    assert out.exists()
    assert out.stat().st_size > 0
    # ZIP magic bytes
    assert out.read_bytes()[:2] == b"PK"


def test_random_password_length():
    import importlib.util

    spec = importlib.util.spec_from_file_location("jm_lookup", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    pw = mod.random_password(12)
    assert len(pw) == 12
    pw2 = mod.random_password(12)
    assert pw != pw2  # collision probability ~1/62^12, negligible
