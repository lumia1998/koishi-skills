#!/usr/bin/env python3
import argparse
import json
import random
import sys
import urllib.parse
import urllib.request

DEFAULT_API_BASE = "https://jav-lumia1998s-projects.vercel.app"
USER_AGENT = "Mozilla/5.0 javbus-skill/1.0"


def api_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}{path}"


def request_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def movie_list_from_payload(payload) -> list[dict]:
    if isinstance(payload, dict):
        return payload.get("movies", []) or []
    if isinstance(payload, list):
        return payload
    return []


def normalize_samples(samples) -> list[dict]:
    result = []
    for sample in samples or []:
        if isinstance(sample, str) and sample.startswith("http"):
            result.append({"src": sample, "referer": ""})
        elif isinstance(sample, dict) and isinstance(sample.get("src"), str) and sample["src"].startswith("http"):
            result.append({"src": sample["src"], "referer": sample.get("referer", "")})
    return result


def magnet_cn(item: dict) -> bool:
    return "ch" in str(item.get("title", "")).lower() or "字幕" in str(item.get("title", ""))


def sorted_magnets(magnets: list[dict], priority: str) -> list[dict]:
    if priority == "cn":
        return sorted(magnets, key=magnet_cn, reverse=True)
    if priority == "size-asc":
        return sorted(magnets, key=lambda item: item.get("numberSize", 0))
    if priority == "size-desc":
        return sorted(magnets, key=lambda item: item.get("numberSize", 0), reverse=True)
    return magnets


def fetch_magnets(base: str, movie: dict, priority: str, limit: int):
    movie_id = movie.get("id", "")
    gid = movie.get("gid")
    uc = movie.get("uc")
    if not movie_id or gid is None or uc is None:
        return []
    url = api_url(base, f"/api/magnets/{urllib.parse.quote(str(movie_id))}?gid={urllib.parse.quote(str(gid))}&uc={urllib.parse.quote(str(uc))}")
    magnets = request_json(url)
    if not isinstance(magnets, list):
        return []
    magnets = sorted_magnets(magnets, priority)
    return magnets if limit == -1 else magnets[:limit]


def fetch_detail(base: str, movie_id: str, magnet_priority: str = "default", magnet_limit: int = 5):
    movie = request_json(api_url(base, f"/api/movies/{urllib.parse.quote(movie_id)}"))
    if not isinstance(movie, dict):
        raise RuntimeError("movie detail response was not an object")
    movie["samples"] = normalize_samples(movie.get("samples"))
    movie["magnets"] = fetch_magnets(base, movie, magnet_priority, magnet_limit)
    return movie


def search_movies(base: str, keyword: str, limit: int = 10, include_unreleased: bool = False):
    path = "/api/movies/search?"
    params = {"keyword": keyword}
    if include_unreleased:
        params["magnet"] = "all"
    return movie_list_from_payload(request_json(api_url(base, path + urllib.parse.urlencode(params))))[:limit]


def latest_movies(base: str, limit: int = 10, uncensored: bool = False, include_unreleased: bool = False):
    params = {}
    if include_unreleased:
        params["magnet"] = "all"
    if uncensored:
        params["type"] = "uncensored"
    suffix = "?" + urllib.parse.urlencode(params) if params else ""
    return movie_list_from_payload(request_json(api_url(base, f"/api/movies{suffix}")))[:limit]


def pick_random_movie(
    base: str,
    rng: random.Random,
    uncensored: bool = False,
    include_unreleased: bool = False,
    pool_size: int = 30,
    magnet_priority: str = "default",
    magnet_limit: int = 5,
):
    movies = latest_movies(base, pool_size, uncensored, include_unreleased)
    if not movies:
        raise RuntimeError("latest movie list was empty")
    choice = rng.choice(movies)
    movie_id = choice.get("id")
    if not movie_id:
        raise RuntimeError("selected movie did not include an id")
    return fetch_detail(base, movie_id, magnet_priority, magnet_limit)


def pick_random_actor(
    base: str,
    rng: random.Random,
    uncensored: bool = False,
    include_unreleased: bool = False,
    pool_size: int = 30,
):
    movie = pick_random_movie(base, rng, uncensored, include_unreleased, pool_size, "default", 0)
    names = [star.get("name", "") for star in movie.get("stars", []) if isinstance(star, dict) and star.get("name")]
    if not names:
        raise RuntimeError("selected random movie did not include actor names")
    return rng.choice(names)


def star_names(movie: dict) -> str:
    stars = movie.get("stars") or []
    names = [star.get("name", "") for star in stars if isinstance(star, dict) and star.get("name")]
    return "、".join(names) if names else "未知"


def format_magnets(magnets: list[dict]) -> str:
    if not magnets:
        return "磁链：暂无"
    lines = []
    for index, magnet in enumerate(magnets, 1):
        title = magnet.get("title") or f"磁链 {index}"
        size = magnet.get("size") or "未知大小"
        link = magnet.get("link") or ""
        lines.append(f"磁链[{index}] {title} / {size}\n{link}")
    return "\n\n".join(lines)


def format_sample_urls(samples: list[dict]) -> str:
    urls = [sample["src"] for sample in samples if sample.get("src")]
    if not urls:
        return "预览图URL：暂无"
    return "预览图URL：\n" + "\n".join(f"{index}. {url}" for index, url in enumerate(urls, 1))


def format_movie_detail(movie: dict) -> str:
    lines = [
        f"标题：{movie.get('title', '')}",
        f"番号：{movie.get('id', '')}",
        f"发行日期：{movie.get('date', '')}",
        f"影片时长：{movie.get('videoLength', '')}分钟",
        f"演员：{star_names(movie)}",
        f"封面URL：{movie.get('img', '') or '暂无'}",
        "",
        format_magnets(movie.get("magnets") or []),
        "",
        format_sample_urls(movie.get("samples") or []),
    ]
    return "\n".join(lines).strip()


def format_movie_list(keyword: str, movies: list[dict]) -> str:
    if not movies:
        return f"没找到和「{keyword}」相关的影片。"
    lines = [f"我找到了这些和「{keyword}」相关的影片："]
    for index, movie in enumerate(movies[:10], 1):
        tags = movie.get("tags") or []
        tag_text = f" / 标签：{', '.join(tags)}" if tags else ""
        lines.extend([
            f"{index}. {movie.get('title', '')}",
            f"番号：{movie.get('id', '')} / 发行日期：{movie.get('date', '')}{tag_text}",
            f"封面URL：{movie.get('img', '') or '暂无'}",
        ])
    lines.append("你要哪个？可以回复序号或番号。")
    return "\n".join(lines)


def print_json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Query JavBus-style API and format movie details without embedding images.")
    parser.add_argument("--api", default=DEFAULT_API_BASE)
    sub = parser.add_subparsers(dest="command", required=True)

    detail_parser = sub.add_parser("detail")
    detail_parser.add_argument("movie_id")
    detail_parser.add_argument("--json", action="store_true")
    detail_parser.add_argument("--magnet-priority", choices=["default", "cn", "size-asc", "size-desc"], default="default")
    detail_parser.add_argument("--magnet-limit", type=int, default=5)

    search_parser = sub.add_parser("search")
    search_parser.add_argument("keyword")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("--include-unreleased", action="store_true")
    search_parser.add_argument("--json", action="store_true")

    latest_parser = sub.add_parser("latest")
    latest_parser.add_argument("--limit", type=int, default=10)
    latest_parser.add_argument("--uncensored", action="store_true")
    latest_parser.add_argument("--include-unreleased", action="store_true")
    latest_parser.add_argument("--json", action="store_true")

    random_parser = sub.add_parser("random")
    random_parser.add_argument("--uncensored", action="store_true")
    random_parser.add_argument("--include-unreleased", action="store_true")
    random_parser.add_argument("--pool-size", type=int, default=30)
    random_parser.add_argument("--json", action="store_true")
    random_parser.add_argument("--magnet-priority", choices=["default", "cn", "size-asc", "size-desc"], default="default")
    random_parser.add_argument("--magnet-limit", type=int, default=5)

    random_actor_parser = sub.add_parser("random-actor")
    random_actor_parser.add_argument("--uncensored", action="store_true")
    random_actor_parser.add_argument("--include-unreleased", action="store_true")
    random_actor_parser.add_argument("--pool-size", type=int, default=30)

    args = parser.parse_args()

    try:
        if args.command == "detail":
            movie = fetch_detail(args.api, args.movie_id, args.magnet_priority, args.magnet_limit)
            print_json(movie) if args.json else print(format_movie_detail(movie))
        elif args.command == "search":
            movies = search_movies(args.api, args.keyword, args.limit, args.include_unreleased)
            print_json(movies) if args.json else print(format_movie_list(args.keyword, movies))
        elif args.command == "latest":
            movies = latest_movies(args.api, args.limit, args.uncensored, args.include_unreleased)
            label = "最新无码" if args.uncensored else "最新"
            print_json(movies) if args.json else print(format_movie_list(label, movies))
        elif args.command == "random":
            movie = pick_random_movie(
                args.api,
                random.Random(),
                args.uncensored,
                args.include_unreleased,
                args.pool_size,
                args.magnet_priority,
                args.magnet_limit,
            )
            print_json(movie) if args.json else print(format_movie_detail(movie))
        elif args.command == "random-actor":
            actor = pick_random_actor(args.api, random.Random(), args.uncensored, args.include_unreleased, args.pool_size)
            print(actor)
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
