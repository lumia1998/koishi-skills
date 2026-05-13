#!/usr/bin/env python3
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "meting_music.py"

spec = importlib.util.spec_from_file_location("meting_music", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
    )


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def test_format_list_text():
    songs = [
        {"id": 1, "name": "Faded", "artists": "Alan Walker", "albumName": "Faded", "duration": 212626},
        {"id": 2, "name": "Alone", "artists": "Alan Walker", "albumName": "Alone", "duration": 161000},
    ]
    text = module.format_results_for_user("alanwalker", songs)
    assert_true("我搜到了这些" in text, "list output should be user-facing text")
    assert_true("1. Faded - Alan Walker" in text, "list output should include numbered title and artist")
    assert_true("JSON" not in text.upper(), "list output should not expose JSON wording to user")


def test_choose_best_prefers_original_over_remix():
    songs = [
        {"id": 1, "name": "Faded Remix", "artists": "Alan Walker", "albumName": "Faded", "duration": 200000},
        {"id": 2, "name": "Faded", "artists": "Alan Walker", "albumName": "Faded", "duration": 212626},
    ]
    result = module.choose_best_from_results("Faded Alan Walker", songs)
    assert_true(result["song"]["id"] == 2, "title+artist should prefer original exact title over remix")


def test_cli_has_new_commands():
    help_result = run_cli("--help")
    assert_true(help_result.returncode == 0, help_result.stderr)
    assert_true("play" in help_result.stdout, "CLI should expose play command")
    assert_true("doctor" in help_result.stdout, "CLI should expose doctor command")
    assert_true("format-list" in help_result.stdout, "CLI should expose human-readable list command")


def test_ensure_ffmpeg_downloads_when_path_missing():
    original_which = module.shutil.which
    original_request_bytes = module.request_bytes
    try:
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("ffmpeg-test/bin/ffmpeg.exe", b"fake exe")

        def fake_which(name):
            return None if name == "ffmpeg" else original_which(name)

        module.shutil.which = fake_which
        module.request_bytes = lambda url, timeout=60: archive.getvalue()

        with tempfile.TemporaryDirectory() as tmpdir:
            target = module.ensure_ffmpeg(Path(tmpdir))
            assert_true(target.name == "ffmpeg.exe", "Windows auto-download should select ffmpeg.exe")
            assert_true(target.exists(), "auto-download should extract ffmpeg into cache")
    finally:
        module.shutil.which = original_which
        module.request_bytes = original_request_bytes



def main():
    tests = [
        test_format_list_text,
        test_choose_best_prefers_original_over_remix,
        test_cli_has_new_commands,
        test_ensure_ffmpeg_downloads_when_path_missing,
    ]
    for test in tests:
        test()
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
