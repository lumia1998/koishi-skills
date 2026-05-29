#!/usr/bin/env python3
import argparse
import json
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

SEARCH_URL = "http://music.163.com/api/search/get/web"
PRESET_METING_APIS = [
    "https://api.injahow.cn/meting/",
    "https://api.qijieya.cn/meting/",
    "https://api.moeyao.cn/meting/",
    "https://meting.jinghuashang.cn/",
    "https://meting.qjqq.cn/",
    "https://api.crowya.com/meting/",
    "https://meting-api.mlj-dragon.cn/meting/",
    "https://api.amarea.cn/meting/",
]
USER_AGENT = "Mozilla/5.0 music-skill/1.0"
FFMPEG_DOWNLOADS = {
    "Windows": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "Linux": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
    "Darwin": "https://evermeet.cx/ffmpeg/getrelease/zip",
}
PENALTY_WORDS = ["remix", "instrumental", "live", "cover", "伴奏", "dj", "slowed", "piano"]
RANDOM_WORDS = ["随便", "你选", "随机", "都行", "任选"]
BROAD_HINTS = ["的歌", "歌手", "来首", "随便"]
VERSION_PATTERN = re.compile(r"\b\d+(?:\.\d+)+\b")


def request_text(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        content_type = response.headers.get("content-type", "").lower()
        if content_type.startswith("audio/") or content_type.startswith("video/") or "application/octet-stream" in content_type:
            return response.geturl()
        return response.read().decode("utf-8", errors="replace")


def request_bytes(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def clamp_limit(limit: int) -> int:
    return max(1, min(limit, 10))


def search(query: str, limit: int):
    params = {
        "csrf_token": "hlpretag=",
        "hlposttag": "",
        "s": query,
        "type": "1",
        "offset": "0",
        "total": "true",
        "limit": str(clamp_limit(limit)),
    }
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    data = json.loads(request_text(url, timeout=10))
    songs = data.get("result", {}).get("songs", []) or []
    return [
        {
            "id": song.get("id"),
            "name": song.get("name", ""),
            "artists": "/".join(a.get("name", "") for a in song.get("artists", [])),
            "albumName": (song.get("album") or {}).get("name", ""),
            "duration": song.get("duration", 0),
        }
        for song in songs[:clamp_limit(limit)]
        if song.get("id") is not None
    ]


def normalize_text(value: str) -> str:
    return "".join(value.lower().split())


def version_tokens(value: str) -> set[str]:
    return set(VERSION_PATTERN.findall(value.lower()))


def misses_query_version(query: str, song: dict) -> bool:
    query_versions = version_tokens(query)
    if not query_versions:
        return False
    title_versions = version_tokens(song["name"])
    return not query_versions.issubset(title_versions)


def detect_request_mode(user_text: str, query: str) -> str:
    normalized_text = normalize_text(user_text)
    if any(word in user_text for word in RANDOM_WORDS):
        return "random"
    if any(hint in user_text for hint in BROAD_HINTS) and len(query.strip().split()) <= 1:
        return "broad"
    return "specific"


def score_song(query: str, song: dict) -> int:
    normalized_query = normalize_text(query)
    title = normalize_text(song["name"])
    artists = normalize_text(song["artists"])
    score = 0
    if title == normalized_query:
        score += 120
    if title in normalized_query:
        score += 90
    if normalized_query in title:
        score += 50
    first_artist = artists.split("/")[0] if artists else ""
    if first_artist and first_artist in normalized_query:
        score += 50
    if misses_query_version(query, song):
        score -= 200
    return score


def rank_results(query: str, results: list[dict]):
    return sorted(results, key=lambda song: score_song(query, song), reverse=True)


def choose_best_from_results(query: str, results: list[dict]):
    if not results:
        raise RuntimeError("no search results")

    ranked = rank_results(query, results)
    normalized_query = normalize_text(query)
    exact = [song for song in ranked if normalize_text(song["name"]) == normalized_query]
    if len(exact) == 1 and not misses_query_version(query, exact[0]):
        return {"match": "exact", "ambiguous": False, "song": exact[0], "candidates": ranked}

    title_artist_contains = [
        song for song in ranked
        if normalize_text(song["name"]) in normalized_query
        and normalize_text(song["artists"]).split("/")[0] in normalized_query
        and not misses_query_version(query, song)
    ]
    if title_artist_contains:
        return {"match": "title_artist", "ambiguous": False, "song": title_artist_contains[0], "candidates": ranked}

    title_contains = [song for song in ranked if normalized_query in normalize_text(song["name"]) and not misses_query_version(query, song)]
    if len(title_contains) == 1:
        return {"match": "title_contains", "ambiguous": False, "song": title_contains[0], "candidates": ranked}

    if exact or title_contains:
        return {"match": "ambiguous", "ambiguous": True, "song": None, "candidates": (exact or title_contains)[:10]}

    if version_tokens(query) and all(misses_query_version(query, song) for song in ranked):
        return {"match": "missing_version", "ambiguous": True, "song": None, "candidates": ranked[:10]}

    return {"match": "no_confident_match", "ambiguous": True, "song": None, "candidates": ranked[:10]}


def choose_best(query: str, limit: int):
    return choose_best_from_results(query, search(query, limit))


def choose_random(query: str, limit: int):
    results = search(query, limit)
    if not results:
        raise RuntimeError("no search results")
    return random.choice(results)


def format_duration(ms: int) -> str:
    seconds = max(0, int(ms or 0) // 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"


def format_results_for_user(query: str, results: list[dict]) -> str:
    if not results:
        return f"没搜到和「{query}」相关的歌曲，换个关键词试试？"
    lines = [f"我搜到了这些和「{query}」相关的歌曲："]
    for index, song in enumerate(results[:10], 1):
        duration = format_duration(song.get("duration", 0))
        lines.append(f"{index}. {song['name']} - {song['artists']} ({duration})")
    lines.append("你想听哪首？可以回复序号、歌名，或者说“随便”。")
    return "\n".join(lines)


def build_meting_url(api_base: str, song_id: int) -> str:
    separator = "&" if "?" in api_base else "?"
    return f"{api_base.rstrip('/')}/{separator}type=url&id={song_id}"


def parse_url(raw: str):
    value = raw.strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    url = parsed.get("url") if isinstance(parsed, dict) else None
    if isinstance(url, str) and (url.startswith("http://") or url.startswith("https://")):
        return url
    return None


def meting_api_candidates(custom_apis: list[str] | None = None):
    return custom_apis or PRESET_METING_APIS


def resolve(song_id: int, apis: list[str] | None = None):
    errors = []
    for api in meting_api_candidates(apis):
        try:
            resolved = parse_url(request_text(build_meting_url(api, song_id), timeout=10))
            if resolved:
                return {"url": resolved, "api": api}
            errors.append(f"{api}: empty url")
        except Exception as error:
            errors.append(f"{api}: {error}")
    raise RuntimeError("Meting API did not return a playable URL; " + "; ".join(errors))


def default_ffmpeg_cache_dir() -> Path:
    return Path(__file__).resolve().parents[1] / ".cache" / "ffmpeg"


def find_cached_ffmpeg(cache_dir: Path):
    candidates = ["ffmpeg.exe"] if os.name == "nt" else ["ffmpeg"]
    for name in candidates:
        for path in cache_dir.rglob(name):
            if path.is_file():
                return path
    return None


def download_ffmpeg_archive(cache_dir: Path) -> Path:
    system = platform.system()
    url = FFMPEG_DOWNLOADS.get(system)
    if not url:
        raise RuntimeError(f"automatic ffmpeg download is not supported on {system}")
    archive_path = cache_dir / urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
    archive_path.write_bytes(request_bytes(url, timeout=120))
    return archive_path


def extract_ffmpeg_archive(archive_path: Path, cache_dir: Path):
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as package:
            package.extractall(cache_dir)
    else:
        shutil.unpack_archive(str(archive_path), str(cache_dir))


def ensure_ffmpeg(cache_dir: Path | None = None) -> Path:
    existing = shutil.which("ffmpeg")
    if existing:
        return Path(existing)

    cache_dir = cache_dir or default_ffmpeg_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = find_cached_ffmpeg(cache_dir)
    if cached:
        return cached

    archive_path = download_ffmpeg_archive(cache_dir)
    extract_ffmpeg_archive(archive_path, cache_dir)
    cached = find_cached_ffmpeg(cache_dir)
    if cached:
        return cached
    raise RuntimeError("downloaded ffmpeg archive did not contain an ffmpeg executable")


def convert_to_mp3(source_url: str, out_path: Path):
    ffmpeg = ensure_ffmpeg()

    with tempfile.TemporaryDirectory(prefix="music-skill-") as tmpdir:
        input_path = Path(tmpdir) / "input.audio"
        input_path.write_bytes(request_bytes(source_url, timeout=60))
        subprocess.run(
            [
                str(ffmpeg),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(input_path),
                "-vn",
                "-acodec",
                "libmp3lame",
                "-b:a",
                "192k",
                str(out_path),
            ],
            check=True,
        )


def download(song_id: int, out_path: Path, apis: list[str] | None = None):
    resolved = resolve(song_id, apis)
    convert_to_mp3(resolved["url"], out_path)
    return {"path": str(out_path), "size": os.path.getsize(out_path), "songId": song_id, "api": resolved["api"]}


def play(query: str, out_path: Path, limit: int, apis: list[str] | None = None):
    choice = choose_best(query, limit)
    if choice["ambiguous"]:
        return {"ambiguous": True, "prompt": format_results_for_user(query, choice["candidates"]), "candidates": choice["candidates"]}
    result = download(choice["song"]["id"], out_path, apis)
    return {"ambiguous": False, "song": choice["song"], **result}


def doctor():
    report = {
        "python": {"ok": True, "version": sys.version.split()[0]},
        "ffmpeg": {"ok": False},
        "network": {"ok": False},
        "meting": {"ok": False},
    }
    try:
        ffmpeg = ensure_ffmpeg()
        report["ffmpeg"] = {"ok": True, "path": str(ffmpeg), "source": "path-or-cache"}
    except Exception as error:
        report["ffmpeg"]["error"] = str(error)
    try:
        report["network"]["sampleCount"] = len(search("alanwalker", 1))
        report["network"]["ok"] = True
    except Exception as error:
        report["network"]["error"] = str(error)
    try:
        resolved = resolve(36990266)
        report["meting"] = {"ok": True, "api": resolved["api"]}
    except Exception as error:
        report["meting"]["error"] = str(error)
    return report


def print_json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def add_api_args(parser):
    parser.add_argument("--api", action="append", help="Meting API base URL. Can be repeated; defaults to preset fallback APIs.")


def main():
    parser = argparse.ArgumentParser(description="Search NetEase music and resolve/download songs through Meting API.")
    sub = parser.add_subparsers(dest="command", required=True)

    search_parser = sub.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)

    list_parser = sub.add_parser("format-list")
    list_parser.add_argument("query")
    list_parser.add_argument("--limit", type=int, default=10)

    resolve_parser = sub.add_parser("resolve")
    resolve_parser.add_argument("song_id", type=int)
    add_api_args(resolve_parser)

    download_parser = sub.add_parser("download")
    download_parser.add_argument("song_id", type=int)
    download_parser.add_argument("--out", required=True)
    add_api_args(download_parser)

    play_parser = sub.add_parser("play")
    play_parser.add_argument("query")
    play_parser.add_argument("--out", required=True)
    play_parser.add_argument("--limit", type=int, default=10)
    add_api_args(play_parser)

    best_parser = sub.add_parser("choose-best")
    best_parser.add_argument("query")
    best_parser.add_argument("--limit", type=int, default=10)

    choose_parser = sub.add_parser("choose-random")
    choose_parser.add_argument("query")
    choose_parser.add_argument("--limit", type=int, default=10)

    sub.add_parser("doctor")

    args = parser.parse_args()

    try:
        if args.command == "search":
            print_json(search(args.query, args.limit))
        elif args.command == "format-list":
            print(format_results_for_user(args.query, search(args.query, args.limit)))
        elif args.command == "choose-best":
            print_json(choose_best(args.query, args.limit))
        elif args.command == "choose-random":
            print_json(choose_random(args.query, args.limit))
        elif args.command == "resolve":
            print_json(resolve(args.song_id, args.api))
        elif args.command == "download":
            out_path = Path(args.out).expanduser().resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            print_json(download(args.song_id, out_path, args.api))
        elif args.command == "play":
            out_path = Path(args.out).expanduser().resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            print_json(play(args.query, out_path, args.limit, args.api))
        elif args.command == "doctor":
            report = doctor()
            print_json(report)
            if not all(section.get("ok") for section in report.values()):
                sys.exit(1)
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding.lower() != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
    if sys.stderr.encoding.lower() != 'utf-8':
        try:
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass
    main()
