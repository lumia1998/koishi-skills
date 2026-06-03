#!/usr/bin/env python3
import importlib.util
import json
import subprocess
import sys
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


def test_choose_best_respects_version_qualifier():
    songs = [
        {"id": 1, "name": "The Spectre", "artists": "Alan Walker", "albumName": "The Spectre", "duration": 193000},
        {"id": 2, "name": "The Spectre 2.0", "artists": "Alan Walker", "albumName": "The Spectre 2.0", "duration": 205000},
    ]
    result = module.choose_best_from_results("The Spectre 2.0 Alan Walker", songs)
    assert_true(result["song"]["id"] == 2, "version qualifiers like 2.0 should not be dropped")


def test_choose_best_asks_when_version_qualifier_is_missing():
    songs = [
        {"id": 1, "name": "The Spectre", "artists": "Alan Walker", "albumName": "The Spectre", "duration": 193000},
        {"id": 2, "name": "The Spectre (Sped up Remix)", "artists": "Alan Walker", "albumName": "The Spectre Remixes", "duration": 176000},
    ]
    result = module.choose_best_from_results("The Spectre 2.0 Alan Walker", songs)
    assert_true(result["ambiguous"], "missing requested version qualifier should ask user to choose")


def test_choose_best_does_not_autoplay_top_result():
    songs = [
        {"id": 1, "name": "Faded", "artists": "Alan Walker", "albumName": "Faded", "duration": 212626},
        {"id": 2, "name": "The Spectre", "artists": "Alan Walker", "albumName": "The Spectre", "duration": 193000},
    ]
    result = module.choose_best_from_results("Alan Walker song", songs)
    assert_true(result["ambiguous"], "unclear queries should show choices instead of autoplaying the top result")


def test_choose_best_asks_when_same_title_has_multiple_artists():
    songs = [
        {"id": 1, "name": "Hello", "artists": "Adele", "albumName": "25", "duration": 295000},
        {"id": 2, "name": "Hello", "artists": "OMFG", "albumName": "Hello", "duration": 225000},
    ]
    result = module.choose_best_from_results("Hello", songs)
    assert_true(result["ambiguous"], "same title by multiple artists should ask user to choose")


def test_cli_has_new_commands():
    help_result = run_cli("--help")
    assert_true(help_result.returncode == 0, help_result.stderr)
    assert_true("play" in help_result.stdout, "CLI should expose play command")
    assert_true("doctor" in help_result.stdout, "CLI should expose doctor command")
    assert_true("format-list" in help_result.stdout, "CLI should expose human-readable list command")


def test_resolve_download_path_stays_under_download():
    root = module.download_root()

    assert_true(module.resolve_download_path("song.mp3") == root / "song.mp3", "relative filenames should resolve under /download")
    assert_true(module.resolve_download_path("/download/song.mp3") == root / "song.mp3", "/download paths should be accepted")

    for bad_path in ["", "../song.mp3"]:
        try:
            module.resolve_download_path(bad_path)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"{bad_path!r} should be rejected")


def test_cleanup_download_root_removes_old_files():
    with module.tempfile.TemporaryDirectory() as tmpdir:
        original_root = module.DOWNLOAD_ROOT
        module.DOWNLOAD_ROOT = Path(tmpdir)
        try:
            root = module.download_root()
            marker = root / "music-old-test.tmp"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("old", encoding="utf-8")
            old_time = module.time.time() - module.DOWNLOAD_MAX_AGE_SECONDS - 60
            module.os.utime(marker, (old_time, old_time))

            module.cleanup_download_root()

            assert_true(not marker.exists(), "cleanup should remove files older than 24 hours")
        finally:
            module.DOWNLOAD_ROOT = original_root


def main():
    tests = [
        test_format_list_text,
        test_choose_best_prefers_original_over_remix,
        test_choose_best_respects_version_qualifier,
        test_choose_best_asks_when_version_qualifier_is_missing,
        test_choose_best_does_not_autoplay_top_result,
        test_choose_best_asks_when_same_title_has_multiple_artists,
        test_cli_has_new_commands,
        test_resolve_download_path_stays_under_download,
        test_cleanup_download_root_removes_old_files,
    ]
    for test in tests:
        test()
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
