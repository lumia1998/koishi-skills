#!/usr/bin/env python3
import importlib.util
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "javbus_lookup.py"

spec = importlib.util.spec_from_file_location("javbus_lookup", SCRIPT)
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


def test_format_movie_detail_uses_urls_not_images():
    movie = {
        "id": "ABC-123",
        "title": "Example Title",
        "date": "2026-05-13",
        "videoLength": "120",
        "stars": [{"name": "Actor A"}],
        "img": "https://example.com/cover.jpg",
        "samples": [
            {"src": "https://example.com/sample1.jpg", "referer": "https://www.javbus.com/ABC-123"},
        ],
        "magnets": [
            {"title": "Example 1", "size": "1.2GB", "link": "magnet:?xt=urn:btih:abc"},
        ],
    }
    text = module.format_movie_detail(movie)
    assert_true("标题：Example Title" in text, "detail output should include title")
    assert_true("封面URL：https://example.com/cover.jpg" in text, "detail output should include cover URL")
    assert_true("预览图URL：" in text, "detail output should include sample URLs")
    assert_true("magnet:?xt=urn:btih:abc" in text, "detail output should include magnet link")
    assert_true("<img" not in text.lower(), "detail output should not embed images")


def test_format_movie_list_is_numbered_text():
    movies = [
        {"id": "ABC-123", "title": "Example Title", "date": "2026-05-13", "img": "https://example.com/cover.jpg", "tags": ["tag1", "tag2"]},
    ]
    text = module.format_movie_list("keyword", movies)
    assert_true("我找到了这些和「keyword」相关的影片：" in text, "list output should be user-facing text")
    assert_true("1. Example Title" in text, "list output should be numbered")
    assert_true("封面URL：https://example.com/cover.jpg" in text, "list output should include cover URL")


def test_pick_random_movie_fetches_detail():
    original_latest = module.latest_movies
    original_detail = module.fetch_detail
    try:
        module.latest_movies = lambda base, limit=10, uncensored=False, include_unreleased=False: [
            {"id": "ABC-123", "title": "Example Title"},
        ]
        module.fetch_detail = lambda base, movie_id, magnet_priority="default", magnet_limit=5: {
            "id": movie_id,
            "title": "Example Title",
            "date": "2026-05-13",
            "videoLength": "120",
            "stars": [],
            "img": "https://example.com/cover.jpg",
            "samples": [],
            "magnets": [],
        }
        movie = module.pick_random_movie("https://example.com", random.Random(1), uncensored=True)
        assert_true(movie["id"] == "ABC-123", "random movie should fetch selected movie detail")
    finally:
        module.latest_movies = original_latest
        module.fetch_detail = original_detail


def test_pick_random_actor_returns_name():
    original_random_movie = module.pick_random_movie
    try:
        module.pick_random_movie = lambda base, rng, uncensored=False, include_unreleased=False, pool_size=30, magnet_priority="default", magnet_limit=5: {
            "stars": [{"name": "Actor A"}, {"name": "Actor B"}],
        }
        actor = module.pick_random_actor("https://example.com", random.Random(1))
        assert_true(actor in {"Actor A", "Actor B"}, "random actor should return a star name from random movie detail")
    finally:
        module.pick_random_movie = original_random_movie


def test_cli_has_expected_commands():
    result = run_cli("--help")
    assert_true(result.returncode == 0, result.stderr)
    assert_true("detail" in result.stdout, "CLI should expose detail command")
    assert_true("search" in result.stdout, "CLI should expose search command")
    assert_true("latest" in result.stdout, "CLI should expose latest command")
    assert_true("random" in result.stdout, "CLI should expose random command")
    assert_true("random-actor" in result.stdout, "CLI should expose random actor command")


def main():
    tests = [
        test_format_movie_detail_uses_urls_not_images,
        test_format_movie_list_is_numbered_text,
        test_pick_random_movie_fetches_detail,
        test_pick_random_actor_returns_name,
        test_cli_has_expected_commands,
    ]
    for test in tests:
        test()
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
