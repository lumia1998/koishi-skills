#!/usr/bin/env python3
"""
Galgame Box — VNDB + TouchGal CLI helper for Koishi/ChatLuna bots.

Provides subcommands:
  vn <keyword>              Search VNDB for visual novels
  character <keyword>       Search VNDB for characters
  producer <keyword>        Search VNDB for producers/developers
  id <vndb-id>              Look up by VNDB ID (v*, c*, p*)
  event                     Today's releases and character birthdays (UTC+8)
  recent                    Recent releases in the past N days (default 30)
  top                       Top-rated VNs, optionally filtered by tag keyword
  characters-of <keyword>   List all characters appearing in a specific VN
  random                    Random game from TouchGal (returns unique_id only)
  random-full               Random game + VNDB info + download links, all-in-one
  find-download <keyword>   Search TouchGal, auto-pick best CN version, return links
  search-touchgal <kw>      Search TouchGal by keyword (returns download resources)
  download <unique_id>       Get download links for a TouchGal game page
  doctor                    Test connectivity to VNDB and TouchGal APIs
"""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

VNDB_API = "https://api.vndb.org/kana/"
TOUCHGAL_BASE = "https://www.touchgal.top/"
TOUCHGAL_SEARCH = TOUCHGAL_BASE + "api/search/"
TOUCHGAL_RANDOM = TOUCHGAL_BASE + "api/home/random"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)

TOUCHGAL_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": USER_AGENT,
    "Origin": "https://www.touchgal.top",
    "Referer": "https://www.touchgal.top/search",
    "X-Requested-With": "kun-fetch",
}

VNDB_VN_FIELDS = (
    "id,average,rating,released,length_minutes,platforms,aliases,"
    "developers{id,original,name},titles{lang,title,official},"
    "image{url},alttitle,title"
)
VNDB_CHARACTER_FIELDS = (
    "id,name,aliases,sex,birthday,waist,hips,bust,blood_type,"
    "weight,height,cup,original,image{url},vns{id,alttitle,title}"
)
VNDB_PRODUCER_FIELDS = "id,name,original,aliases,lang,type"
VNDB_VN_SHORT_FIELDS = "id,alttitle,title,released,rating,image{url}"
VNDB_CHARACTER_SHORT_FIELDS = "id,name,original,aliases,image{url},vns{id,alttitle,title}"

ID_PREFIX_MAP = {"v": "vn", "c": "character", "p": "producer"}

LANG_NAMES = {"ja": "日文", "en": "英文", "zh-Hans": "简中", "zh-Hant": "繁中", "zh": "中文"}
PRODUCER_TYPE = {"co": "公司", "in": "个人", "ng": "业余团体"}
GENDER_MAP = {"m": "男性", "f": "女性", "b": "双性", "n": "无性"}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout: int = 15, headers: dict | None = None) -> dict | str:
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _http_post(url: str, data: dict, headers: dict | None = None, timeout: int = 15) -> dict:
    req_headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _http_get_with_cookies(
    url: str,
    cookies: dict | None = None,
    headers: dict | None = None,
    timeout: int = 15,
) -> dict | str:
    req_headers = dict(TOUCHGAL_HEADERS)
    if headers:
        req_headers.update(headers)
    if cookies:
        req_headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _http_post_with_cookies(
    url: str,
    data: dict,
    cookies: dict | None = None,
    headers: dict | None = None,
    timeout: int = 15,
) -> dict:
    req_headers = dict(TOUCHGAL_HEADERS)
    if headers:
        req_headers.update(headers)
    if cookies:
        req_headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


# ---------------------------------------------------------------------------
# TouchGal cookies helper
# ---------------------------------------------------------------------------

def _touchgal_cookies(token: str = "", cf_clearance: str = "", nsfw: bool = False) -> dict:
    cookies = {
        "kun-patch-setting-store|state|data|kunNsfwEnable": "all" if nsfw else "sfw"
    }
    if token:
        cookies["kun-galgame-patch-moe-token"] = token
    if cf_clearance:
        cookies["cf_clearance"] = cf_clearance
    return cookies


# ---------------------------------------------------------------------------
# VNDB queries
# ---------------------------------------------------------------------------

def vndb_search_vn(keyword: str, limit: int = 10) -> list[dict]:
    payload = {
        "filters": ["search", "=", keyword],
        "fields": VNDB_VN_FIELDS,
        "results": limit,
    }
    res = _http_post(VNDB_API + "vn", payload)
    return res.get("results", [])


def vndb_search_character(keyword: str, limit: int = 10) -> list[dict]:
    payload = {
        "filters": ["search", "=", keyword],
        "fields": VNDB_CHARACTER_FIELDS,
        "results": limit,
    }
    res = _http_post(VNDB_API + "character", payload)
    return res.get("results", [])


def vndb_search_producer(keyword: str, limit: int = 5) -> tuple[list[dict], list[list[dict]]]:
    payload = {
        "filters": ["search", "=", keyword],
        "fields": VNDB_PRODUCER_FIELDS,
        "results": limit,
    }
    pro_res = _http_post(VNDB_API + "producer", payload).get("results", [])
    vns_by_producer: list[list[dict]] = []
    for producer in pro_res:
        vn_payload = {
            "filters": ["developer", "=", ["id", "=", producer["id"]]],
            "fields": VNDB_VN_SHORT_FIELDS,
            "sort": "rating",
            "reverse": True,
            "results": 9,
        }
        vns = _http_post(VNDB_API + "vn", vn_payload).get("results", [])
        vns_by_producer.append(vns)
    return pro_res, vns_by_producer


def vndb_lookup_id(vndb_id: str) -> dict:
    prefix = vndb_id[0].lower()
    entity = ID_PREFIX_MAP.get(prefix)
    if not entity:
        raise ValueError(f"未知 VNDB ID 前缀：{vndb_id!r}，支持 v/c/p")

    if entity == "vn":
        fields = VNDB_VN_FIELDS
    elif entity == "character":
        fields = VNDB_CHARACTER_FIELDS
    else:
        fields = VNDB_PRODUCER_FIELDS

    payload = {"filters": ["id", "=", [vndb_id]], "fields": fields}
    results = _http_post(VNDB_API + entity, payload).get("results", [])
    if not results:
        raise RuntimeError(f"VNDB 中未找到 ID：{vndb_id}")
    return {"type": entity, "data": results[0]}


def vndb_event(rating_threshold: int = 75) -> dict:
    now = datetime.now(tz=timezone(timedelta(hours=8)))
    year = now.year
    month = f"{now.month:02d}"
    day = f"{now.day:02d}"
    date_str = f"{year}-{month}-{day}"

    # Released today in any past/current year
    released_filters = [["released", "=", f"{y}-{month}-{day}"] for y in range(1990, year + 1)]
    vn_payload = {
        "filters": ["and", ["or", *released_filters], ["rating", ">=", rating_threshold]],
        "fields": VNDB_VN_SHORT_FIELDS,
        "results": 20,
    }
    cha_payload = {
        "filters": [
            "and",
            ["birthday", "=", [int(month), int(day)]],
            ["vn", "=", ["rating", ">=", rating_threshold]],
        ],
        "fields": VNDB_CHARACTER_SHORT_FIELDS,
        "results": 20,
    }

    vn_res = _http_post(VNDB_API + "vn", vn_payload).get("results", [])
    cha_res = _http_post(VNDB_API + "character", cha_payload).get("results", [])
    return {"date": date_str, "releases": vn_res, "birthdays": cha_res}


def vndb_recent(days: int = 30, rating_threshold: int = 70, limit: int = 15) -> dict:
    """VNs released in the past N days, sorted by release date descending."""
    now = datetime.now(tz=timezone(timedelta(hours=8)))
    past = now - timedelta(days=days)

    def _fmt(dt: datetime) -> str:
        return f"{dt.year}-{dt.month:02d}-{dt.day:02d}"

    payload = {
        "filters": [
            "and",
            ["released", ">=", _fmt(past)],
            ["released", "<=", _fmt(now)],
            ["rating", ">=", rating_threshold],
        ],
        "fields": VNDB_VN_SHORT_FIELDS,
        "sort": "released",
        "reverse": True,
        "results": limit,
    }
    results = _http_post(VNDB_API + "vn", payload).get("results", [])
    return {"days": days, "from": _fmt(past), "to": _fmt(now), "results": results}


def vndb_top(tag_keyword: str = "", limit: int = 10, rating_threshold: int = 80) -> dict:
    """Top-rated VNs globally, or filtered by a tag keyword search."""
    matched_tags: list[str] = []
    if tag_keyword:
        tag_payload = {
            "filters": ["search", "=", tag_keyword],
            "fields": "id,name,aliases",
            "results": 5,
        }
        tag_res = _http_post(VNDB_API + "tag", tag_payload).get("results", [])
        if tag_res:
            tag_filters = [["tag", "=", ["id", "=", t["id"]]] for t in tag_res[:3]]
            vn_filter = ["and", ["or", *tag_filters], ["rating", ">=", rating_threshold]]
            matched_tags = [t.get("name", "") for t in tag_res]
        else:
            vn_filter = ["and", ["search", "=", tag_keyword], ["rating", ">=", rating_threshold]]
    else:
        vn_filter = ["rating", ">=", rating_threshold]

    payload = {
        "filters": vn_filter,
        "fields": VNDB_VN_SHORT_FIELDS,
        "sort": "rating",
        "reverse": True,
        "results": limit,
    }
    results = _http_post(VNDB_API + "vn", payload).get("results", [])
    return {"tag_keyword": tag_keyword, "matched_tags": matched_tags, "results": results}


def vndb_characters_of(vn_keyword: str, limit: int = 20) -> dict:
    """List characters appearing in a VN matched by keyword."""
    vn_results = vndb_search_vn(vn_keyword, limit=1)
    if not vn_results:
        return {"found": False, "keyword": vn_keyword, "vn": None, "characters": []}

    vn = vn_results[0]
    vn_id = vn["id"]
    cha_payload = {
        "filters": ["vn", "=", ["id", "=", vn_id]],
        "fields": VNDB_CHARACTER_FIELDS,
        "results": limit,
    }
    cha_results = _http_post(VNDB_API + "character", cha_payload).get("results", [])
    return {"found": True, "keyword": vn_keyword, "vn": vn, "characters": cha_results}


# ---------------------------------------------------------------------------
# TouchGal queries
# ---------------------------------------------------------------------------

def touchgal_search(
    keyword: str,
    limit: int = 12,
    token: str = "",
    cf_clearance: str = "",
    nsfw: bool = False,
) -> list[dict]:
    cookies = _touchgal_cookies(token, cf_clearance, nsfw)
    query_string = json.dumps(
        [{"type": "keyword", "name": part} for part in keyword.strip().split()]
    )
    payload = {
        "queryString": query_string,
        "limit": limit,
        "searchOption": {
            "searchInIntroduction": False,
            "searchInAlias": True,
            "searchInTag": False,
        },
        "page": 1,
        "selectedType": "all",
        "selectedLanguage": "all",
        "selectedPlatform": "all",
        "sortField": "resource_update_time",
        "sortOrder": "desc",
        "selectedYears": ["all"],
        "selectedMonths": ["all"],
    }
    res = _http_post_with_cookies(TOUCHGAL_SEARCH, payload, cookies=cookies)
    return res.get("galgames", [])


def touchgal_random(token: str = "", cf_clearance: str = "", nsfw: bool = False) -> str:
    cookies = _touchgal_cookies(token, cf_clearance, nsfw)
    res = _http_get_with_cookies(TOUCHGAL_RANDOM, cookies=cookies)
    if isinstance(res, dict):
        return res.get("uniqueId", "")
    raise RuntimeError(f"TouchGal random 返回了非预期内容：{res!r}")


def touchgal_download(touchgal_id: int, token: str = "", cf_clearance: str = "", nsfw: bool = False) -> list[dict]:
    cookies = _touchgal_cookies(token, cf_clearance, nsfw)
    url = f"{TOUCHGAL_BASE}api/patch/resource?patchId={touchgal_id}"
    res = _http_get_with_cookies(url, cookies=cookies)
    if isinstance(res, list):
        return res
    raise RuntimeError(f"TouchGal download 返回了非预期内容：{res!r}")


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _titles_str(titles: list[dict] | None, alttitle: str | None, title: str) -> str:
    if not titles:
        return alttitle or title
    official = [t for t in titles if t.get("official")]
    if not official:
        return alttitle or title
    parts = []
    for t in official:
        lang_label = LANG_NAMES.get(t.get("lang", ""), t.get("lang", ""))
        parts.append(f"{t['title']}（{lang_label}）")
    return " / ".join(parts)


def _vn_summary(vn: dict) -> str:
    title = _titles_str(vn.get("titles"), vn.get("alttitle"), vn.get("title", ""))
    parts = [f"【{title}】({vn.get('id', '')})"]
    if vn.get("released"):
        parts.append(f"发行：{vn['released']}")
    if vn.get("rating") is not None:
        parts.append(f"评分：{vn['rating']:.1f}")
    if vn.get("average") is not None:
        parts.append(f"均分：{vn['average']:.1f}")
    if vn.get("length_minutes"):
        hours = vn["length_minutes"] // 60
        mins = vn["length_minutes"] % 60
        parts.append(f"时长：{hours}h{mins}m" if hours else f"时长：{mins}m")
    platforms = vn.get("platforms") or []
    if platforms:
        parts.append(f"平台：{', '.join(platforms)}")
    developers = vn.get("developers") or []
    if developers:
        dev_names = [d.get("original") or d.get("name", "") for d in developers]
        parts.append(f"开发：{' / '.join(dev_names)}")
    aliases = vn.get("aliases") or []
    if aliases:
        parts.append(f"别名：{' / '.join(aliases[:3])}")
    image = vn.get("image") or {}
    if image.get("url"):
        parts.append(f"封面URL：{image['url']}")
    return "\n".join(parts)


def _character_summary(cha: dict) -> str:
    name = cha.get("original") or cha.get("name", "")
    parts = [f"【{name}】({cha.get('id', '')})"]
    if cha.get("name") and cha.get("original") and cha["name"] != cha["original"]:
        parts.append(f"译名：{cha['name']}")
    sex_list = cha.get("sex") or []
    if sex_list:
        genders = [GENDER_MAP.get(s, s) for s in sex_list]
        parts.append(f"性别：{'/'.join(genders)}")
    birthday = cha.get("birthday") or []
    if len(birthday) == 2:
        parts.append(f"生日：{birthday[0]}月{birthday[1]}日")
    measurements = []
    if cha.get("height"):
        measurements.append(f"身高 {cha['height']}cm")
    if cha.get("weight"):
        measurements.append(f"体重 {cha['weight']}kg")
    if cha.get("bust"):
        measurements.append(f"胸围 {cha['bust']}cm")
    if cha.get("waist"):
        measurements.append(f"腰围 {cha['waist']}cm")
    if cha.get("hips"):
        measurements.append(f"臀围 {cha['hips']}cm")
    if cha.get("cup"):
        measurements.append(f"罩杯 {cha['cup']}")
    if cha.get("blood_type"):
        measurements.append(f"血型 {cha['blood_type'].upper()}")
    if measurements:
        parts.append(" / ".join(measurements))
    vns = cha.get("vns") or []
    if vns:
        vn_titles = [v.get("alttitle") or v.get("title", "") for v in vns[:3]]
        parts.append(f"出场作品：{' / '.join(vn_titles)}")
    image = cha.get("image") or {}
    if image.get("url"):
        parts.append(f"图片URL：{image['url']}")
    return "\n".join(parts)


def _producer_summary(pro: dict, vns: list[dict] | None = None) -> str:
    name = pro.get("original") or pro.get("name", "")
    parts = [f"【{name}】({pro.get('id', '')})"]
    if pro.get("name") and pro.get("original") and pro["name"] != pro["original"]:
        parts.append(f"译名：{pro['name']}")
    if pro.get("type"):
        parts.append(f"类型：{PRODUCER_TYPE.get(pro['type'], pro['type'])}")
    if pro.get("lang"):
        parts.append(f"语言：{LANG_NAMES.get(pro['lang'], pro['lang'])}")
    aliases = pro.get("aliases") or []
    if aliases:
        parts.append(f"别名：{' / '.join(aliases[:3])}")
    if vns:
        parts.append(f"\n代表作（评分倒序）：")
        for vn in vns[:9]:
            title = vn.get("alttitle") or vn.get("title", "")
            rating = f" [{vn['rating']:.1f}]" if vn.get("rating") else ""
            released = f" {vn['released']}" if vn.get("released") else ""
            parts.append(f"  · {title}{rating}{released}")
    return "\n".join(parts)


def format_vn_list(keyword: str, results: list[dict]) -> str:
    if not results:
        return f"没找到和「{keyword}」相关的 VN，换个关键词试试？"
    lines = [f"找到了这些和「{keyword}」相关的 VN："]
    for i, vn in enumerate(results[:10], 1):
        title = _titles_str(vn.get("titles"), vn.get("alttitle"), vn.get("title", ""))
        released = vn.get("released") or "未知"
        rating = f" / 评分 {vn['rating']:.1f}" if vn.get("rating") else ""
        lines.append(f"{i}. {title} ({vn['id']}) — {released}{rating}")
    return "\n".join(lines)


def format_character_list(keyword: str, results: list[dict]) -> str:
    if not results:
        return f"没找到和「{keyword}」相关的角色，换个关键词试试？"
    lines = [f"找到了这些和「{keyword}」相关的角色："]
    for i, cha in enumerate(results[:10], 1):
        name = cha.get("original") or cha.get("name", "")
        vns = cha.get("vns") or []
        vn_title = (vns[0].get("alttitle") or vns[0].get("title", "")) if vns else "未知作品"
        lines.append(f"{i}. {name} ({cha['id']}) — 出自：{vn_title}")
    return "\n".join(lines)


def format_producer_list(keyword: str, results: list[dict]) -> str:
    if not results:
        return f"没找到和「{keyword}」相关的厂商，换个关键词试试？"
    lines = [f"找到了这些和「{keyword}」相关的厂商："]
    for i, pro in enumerate(results[:5], 1):
        name = pro.get("original") or pro.get("name", "")
        lang = LANG_NAMES.get(pro.get("lang", ""), pro.get("lang", ""))
        lines.append(f"{i}. {name} ({pro['id']}) — {lang}")
    return "\n".join(lines)


def format_event(data: dict) -> str:
    date = data["date"]
    releases = data["releases"]
    birthdays = data["birthdays"]
    lines = [f"=== {date} 今日资讯 ==="]
    if releases:
        lines.append(f"\n本日发售（{len(releases)} 部）：")
        for vn in releases:
            title = vn.get("alttitle") or vn.get("title", "")
            rating = f" [评分 {vn['rating']:.1f}]" if vn.get("rating") else ""
            lines.append(f"  · {title}{rating}")
    else:
        lines.append("\n本日无新发售。")
    if birthdays:
        lines.append(f"\n本日生日角色（{len(birthdays)} 位）：")
        for cha in birthdays:
            name = cha.get("original") or cha.get("name", "")
            vns = cha.get("vns") or []
            from_vn = (vns[0].get("alttitle") or vns[0].get("title", "")) if vns else ""
            suffix = f" — 出自：{from_vn}" if from_vn else ""
            lines.append(f"  · {name}{suffix}")
    else:
        lines.append("\n本日无角色生日。")
    return "\n".join(lines)


def format_touchgal_list(keyword: str, results: list[dict]) -> str:
    if not results:
        return f"TouchGal 没找到和「{keyword}」相关的 Gal，换个关键词试试？"
    lines = [f"找到了这些和「{keyword}」相关的 Gal（TouchGal）："]
    for i, game in enumerate(results[:10], 1):
        name = game.get("name", "")
        uid = game.get("unique_id", "")
        gid = game.get("id", "")
        rating = f" / 评分 {game['averageRating']:.1f}" if game.get("averageRating") else ""
        langs = game.get("language") or []
        lang_str = " / ".join(langs) if langs else ""
        lines.append(f"{i}. {name} [ID:{gid}] [{uid}]{rating}{' | ' + lang_str if lang_str else ''}")
    return "\n".join(lines)


def format_download_resources(game_name: str, resources: list[dict]) -> str:
    if not resources:
        return f"「{game_name}」暂无可用下载资源。"
    lines = [f"「{game_name}」下载资源："]
    for res in resources:
        section = res.get("section") or res.get("name", "")
        note = res.get("note", "")
        platforms = res.get("platform") or []
        langs = res.get("language") or []
        header = f"\n【{section}】"
        if note:
            header += f" {note}"
        if platforms:
            header += f" 平台：{', '.join(platforms)}"
        if langs:
            header += f" 语言：{', '.join(langs)}"
        lines.append(header)
        for link in res.get("links") or []:
            storage = link.get("storage", "")
            size = link.get("size", "")
            content = link.get("content", "")
            code = link.get("code", "")
            password = link.get("password", "")
            link_line = f"  [{storage}] {content}"
            if size:
                link_line += f" ({size})"
            if code:
                link_line += f"\n  提取码：{code}"
            if password:
                link_line += f"\n  解压密码：{password}"
            lines.append(link_line)
    return "\n".join(lines)


def format_recent(data: dict) -> str:
    results = data.get("results") or []
    days = data.get("days", 30)
    date_from = data.get("from", "")
    date_to = data.get("to", "")
    if not results:
        return f"最近 {days} 天（{date_from} 至 {date_to}）暂无符合条件的新发售（评分阈值 70+）。"
    lines = [f"最近 {days} 天新发售（{date_from} 至 {date_to}，共 {len(results)} 部）："]
    for vn in results:
        title = vn.get("alttitle") or vn.get("title", "")
        released = vn.get("released") or "未知"
        rating = f" [评分 {vn['rating']:.1f}]" if vn.get("rating") else ""
        img = (vn.get("image") or {}).get("url", "")
        img_part = f"\n  封面URL：{img}" if img else ""
        lines.append(f"  · {title} — {released}{rating}{img_part}")
    return "\n".join(lines)


def format_top(data: dict) -> str:
    results = data.get("results") or []
    tag_kw = data.get("tag_keyword", "")
    matched = data.get("matched_tags") or []
    if not results:
        hint = f"「{tag_kw}」相关" if tag_kw else ""
        return f"没找到{hint}高分作品（可能标签不匹配，换个关键词试试？）"
    if tag_kw:
        tag_label = "、".join(matched[:3]) if matched else tag_kw
        header = f"「{tag_label}」相关高分 Gal（评分倒序）："
    else:
        header = "全局高分 Gal 榜单（评分倒序）："
    lines = [header]
    for i, vn in enumerate(results, 1):
        title = vn.get("alttitle") or vn.get("title", "")
        released = vn.get("released") or "未知"
        rating = f" [评分 {vn['rating']:.1f}]" if vn.get("rating") else ""
        lines.append(f"  {i}. {title} — {released}{rating}")
    return "\n".join(lines)


def format_characters_of(data: dict) -> str:
    if not data.get("found"):
        return f"VNDB 上没找到「{data['keyword']}」，换个关键词试试？"
    vn = data["vn"]
    characters = data.get("characters") or []
    vn_title = _titles_str(vn.get("titles"), vn.get("alttitle"), vn.get("title", ""))
    if not characters:
        return f"【{vn_title}】在 VNDB 暂无角色信息。"
    lines = [f"【{vn_title}】角色列表（共 {len(characters)} 位）："]
    for cha in characters:
        name = cha.get("original") or cha.get("name", "")
        sex_list = cha.get("sex") or []
        gender = GENDER_MAP.get(sex_list[0], "") if sex_list else ""
        birthday = cha.get("birthday") or []
        bday = f" 生日：{birthday[0]}月{birthday[1]}日" if len(birthday) == 2 else ""
        height = f" 身高：{cha['height']}cm" if cha.get("height") else ""
        img = (cha.get("image") or {}).get("url", "")
        img_part = f"\n    图片URL：{img}" if img else ""
        meta = "、".join(filter(None, [gender, bday.strip(), height.strip()]))
        lines.append(f"  · {name} ({cha['id']}){' — ' + meta if meta else ''}{img_part}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# High-level composite commands (no user interaction needed)
# ---------------------------------------------------------------------------

CN_LANGS = {"zh-Hans", "zh-Hant", "zh"}
CN_PLATFORM_KEYS = ["zh-hans", "zh-hant", "zh", "简中", "繁中", "中文", "汉化"]


def _resource_cn_score(res: dict) -> int:
    """Higher = better Chinese version. Used for auto-picking."""
    score = 0
    langs = [l.lower() for l in (res.get("language") or [])]
    note = (res.get("note") or "").lower()
    section = (res.get("section") or "").lower()
    for lang in langs:
        if lang in ("zh-hans", "zh", "简中"):
            score += 10
        elif lang in ("zh-hant", "繁中"):
            score += 6
    for hint in ["汉化", "中文", "简中", "繁中"]:
        if hint in note or hint in section:
            score += 3
    # Prefer resources that actually have links
    if res.get("links"):
        score += 1
    return score


def _pick_best_resource(resources: list[dict]) -> dict | None:
    """Pick the best resource: prefer Chinese, then any with links."""
    if not resources:
        return None
    scored = sorted(resources, key=_resource_cn_score, reverse=True)
    # Prefer ones with links
    with_links = [r for r in scored if r.get("links")]
    return (with_links or scored)[0]


def random_full(token: str = "", cf: str = "", nsfw: bool = False) -> dict:
    """
    Get a random game from TouchGal, enrich with VNDB info if possible,
    and attach its best download resource. Returns a single dict ready to format.
    """
    uid = touchgal_random(token, cf, nsfw)
    tg_results = touchgal_search(uid, limit=3, token=token, cf_clearance=cf, nsfw=nsfw)

    # Try to find this exact game by unique_id in search results
    game = next((g for g in tg_results if g.get("unique_id") == uid), None)
    if not game and tg_results:
        game = tg_results[0]

    game_name = (game or {}).get("name", uid)
    touchgal_id = (game or {}).get("id")
    page_url = TOUCHGAL_BASE + uid

    # Fetch VNDB info using game name
    vndb_info = None
    try:
        vns = vndb_search_vn(game_name, limit=1)
        if vns:
            vndb_info = vns[0]
    except Exception:
        pass

    # Fetch download resources
    resources: list[dict] = []
    if touchgal_id:
        try:
            resources = touchgal_download(touchgal_id, token, cf, nsfw)
        except Exception:
            pass

    best = _pick_best_resource(resources)
    return {
        "game_name": game_name,
        "unique_id": uid,
        "page_url": page_url,
        "touchgal": game,
        "vndb": vndb_info,
        "best_resource": best,
        "all_resources": resources,
    }


def format_random_full(data: dict) -> str:
    game_name = data["game_name"]
    page_url = data["page_url"]
    vndb = data.get("vndb")
    best = data.get("best_resource")

    lines = []

    # Header from VNDB if available, else TouchGal name
    if vndb:
        title = _titles_str(vndb.get("titles"), vndb.get("alttitle"), vndb.get("title", game_name))
        lines.append(f"【{title}】")
        if vndb.get("released"):
            lines.append(f"发行：{vndb['released']}")
        if vndb.get("rating") is not None:
            lines.append(f"评分：{vndb['rating']:.1f}")
        if vndb.get("average") is not None:
            lines.append(f"均分：{vndb['average']:.1f}")
        if vndb.get("length_minutes"):
            hours = vndb["length_minutes"] // 60
            mins = vndb["length_minutes"] % 60
            lines.append(f"时长：{hours}h{mins}m" if hours else f"时长：{mins}m")
        devs = vndb.get("developers") or []
        if devs:
            dev_names = [d.get("original") or d.get("name", "") for d in devs]
            lines.append(f"开发：{' / '.join(dev_names)}")
        img = (vndb.get("image") or {}).get("url")
        if img:
            lines.append(f"封面URL：{img}")
    else:
        lines.append(f"【{game_name}】")

    lines.append(f"TouchGal 页面：{page_url}")

    if best:
        lines.append("")
        section = best.get("section") or best.get("name", "下载")
        langs = best.get("language") or []
        note = best.get("note", "")
        header = f"下载（{section}"
        if langs:
            header += f" / {', '.join(langs)}"
        header += "）"
        if note:
            header += f" {note}"
        lines.append(header)
        for link in best.get("links") or []:
            storage = link.get("storage", "")
            size = link.get("size", "")
            content = link.get("content", "")
            code = link.get("code", "")
            password = link.get("password", "")
            link_line = f"  [{storage}] {content}"
            if size:
                link_line += f"（{size}）"
            if code:
                link_line += f"\n  提取码：{code}"
            if password:
                link_line += f"\n  解压密码：{password}"
            lines.append(link_line)
    elif data.get("touchgal_id"):
        lines.append("（暂无可用下载资源）")

    return "\n".join(lines)


def find_download(keyword: str, token: str = "", cf: str = "", nsfw: bool = False) -> dict:
    """
    Search TouchGal for keyword, auto-pick the game most likely to match,
    then fetch resources and auto-select the best Chinese version.
    Returns a dict with game info and chosen resource.
    """
    results = touchgal_search(keyword, limit=12, token=token, cf_clearance=cf, nsfw=nsfw)
    if not results:
        return {"found": False, "keyword": keyword}

    # Pick best game match: exact name match first, then highest rating
    kw_lower = keyword.lower()

    def _game_score(g: dict) -> tuple:
        name = (g.get("name") or "").lower()
        exact = name == kw_lower
        contains = kw_lower in name
        rating = g.get("averageRating") or 0
        # prefer games with zh lang
        has_cn = any(l in CN_LANGS for l in (g.get("language") or []))
        return (exact, contains, has_cn, rating)

    best_game = max(results, key=_game_score)
    touchgal_id = best_game.get("id")
    game_name = best_game.get("name", keyword)
    uid = best_game.get("unique_id", "")
    page_url = TOUCHGAL_BASE + uid if uid else ""

    # Fetch resources
    resources: list[dict] = []
    if touchgal_id:
        try:
            resources = touchgal_download(touchgal_id, token, cf, nsfw)
        except Exception:
            pass

    best_res = _pick_best_resource(resources)

    # Also try VNDB for extra info
    vndb_info = None
    try:
        vns = vndb_search_vn(game_name, limit=1)
        if vns:
            vndb_info = vns[0]
    except Exception:
        pass

    return {
        "found": True,
        "keyword": keyword,
        "game_name": game_name,
        "unique_id": uid,
        "page_url": page_url,
        "touchgal": best_game,
        "vndb": vndb_info,
        "best_resource": best_res,
        "all_resources": resources,
    }


def format_find_download(data: dict) -> str:
    if not data.get("found"):
        return f"TouchGal 上没找到「{data['keyword']}」的相关资源，换个关键词试试？"

    game_name = data["game_name"]
    page_url = data.get("page_url", "")
    vndb = data.get("vndb")
    best = data.get("best_resource")
    all_res = data.get("all_resources") or []

    lines = []

    if vndb:
        title = _titles_str(vndb.get("titles"), vndb.get("alttitle"), vndb.get("title", game_name))
        lines.append(f"【{title}】")
        if vndb.get("rating") is not None:
            lines.append(f"VNDB 评分：{vndb['rating']:.1f}")
        img = (vndb.get("image") or {}).get("url")
        if img:
            lines.append(f"封面URL：{img}")
    else:
        lines.append(f"【{game_name}】")

    if page_url:
        lines.append(f"TouchGal 页面：{page_url}")

    if not all_res:
        lines.append("暂无可用下载资源。")
        return "\n".join(lines)

    if best:
        lines.append("")
        section = best.get("section") or best.get("name", "下载")
        langs = best.get("language") or []
        note = best.get("note", "")
        cn_score = _resource_cn_score(best)
        label = "中文汉化版" if cn_score >= 6 else section
        header = f"推荐下载（{label}"
        if langs and cn_score < 6:
            header += f" / {', '.join(langs)}"
        header += "）"
        if note:
            header += f" {note}"
        lines.append(header)
        for link in best.get("links") or []:
            storage = link.get("storage", "")
            size = link.get("size", "")
            content = link.get("content", "")
            code = link.get("code", "")
            password = link.get("password", "")
            link_line = f"  [{storage}] {content}"
            if size:
                link_line += f"（{size}）"
            if code:
                link_line += f"\n  提取码：{code}"
            if password:
                link_line += f"\n  解压密码：{password}"
            lines.append(link_line)

        # Mention if there are more versions
        if len(all_res) > 1:
            other_names = []
            for r in all_res:
                if r is best:
                    continue
                langs_r = r.get("language") or []
                s = r.get("section") or r.get("name", "")
                label_r = f"{s}（{'、'.join(langs_r)}）" if langs_r else s
                other_names.append(label_r)
            if other_names:
                lines.append(f"\n其他版本：{' / '.join(other_names[:4])}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------

def doctor() -> dict:
    report: dict = {"vndb": {"ok": False}, "touchgal": {"ok": False}}
    try:
        results = vndb_search_vn("Clannad", limit=1)
        report["vndb"] = {"ok": bool(results), "sample": results[0].get("title") if results else None}
    except Exception as e:
        report["vndb"]["error"] = str(e)
    try:
        uid = touchgal_random()
        report["touchgal"] = {"ok": bool(uid), "sample_uid": uid}
    except Exception as e:
        report["touchgal"]["error"] = str(e)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _add_touchgal_auth_args(parser):
    parser.add_argument("--token", default="", help="TouchGal 登录 Token")
    parser.add_argument("--cf", default="", help="CloudFlare cf_clearance Cookie")
    parser.add_argument("--nsfw", action="store_true", help="启用 NSFW 内容")


def main():
    parser = argparse.ArgumentParser(
        description="Galgame Box — VNDB + TouchGal CLI for Koishi/ChatLuna bots."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # vn search
    vn_p = sub.add_parser("vn", help="搜索 VNDB 视觉小说")
    vn_p.add_argument("keyword")
    vn_p.add_argument("--limit", type=int, default=10)
    vn_p.add_argument("--json", action="store_true")

    # character search
    cha_p = sub.add_parser("character", help="搜索 VNDB 角色")
    cha_p.add_argument("keyword")
    cha_p.add_argument("--limit", type=int, default=10)
    cha_p.add_argument("--json", action="store_true")

    # producer search
    pro_p = sub.add_parser("producer", help="搜索 VNDB 厂商")
    pro_p.add_argument("keyword")
    pro_p.add_argument("--limit", type=int, default=5)
    pro_p.add_argument("--json", action="store_true")

    # id lookup
    id_p = sub.add_parser("id", help="通过 VNDB ID 直接查询（v*/c*/p*）")
    id_p.add_argument("vndb_id")
    id_p.add_argument("--json", action="store_true")

    # event (today's releases + birthdays)
    event_p = sub.add_parser("event", help="今日发售和角色生日")
    event_p.add_argument("--rating", type=int, default=75, help="最低评分阈值")
    event_p.add_argument("--json", action="store_true")

    # recent releases
    recent_p = sub.add_parser("recent", help="最近 N 天新发售的 VN")
    recent_p.add_argument("--days", type=int, default=30, help="查询过去几天（默认 30）")
    recent_p.add_argument("--rating", type=int, default=70, help="最低评分阈值（默认 70）")
    recent_p.add_argument("--limit", type=int, default=15)
    recent_p.add_argument("--json", action="store_true")

    # top / tag-based ranking
    top_p = sub.add_parser("top", help="高分 VN 榜单，可按标签关键词筛选")
    top_p.add_argument("tag", nargs="?", default="", help="标签关键词（可选，如：百合、催泪、NTR）")
    top_p.add_argument("--limit", type=int, default=10)
    top_p.add_argument("--rating", type=int, default=80, help="最低评分阈值（默认 80）")
    top_p.add_argument("--json", action="store_true")

    # characters of a VN
    cof_p = sub.add_parser("characters-of", help="列出指定 VN 的所有角色")
    cof_p.add_argument("keyword", help="VN 名称关键词")
    cof_p.add_argument("--limit", type=int, default=20)
    cof_p.add_argument("--json", action="store_true")

    # touchgal random (uid only)
    rand_p = sub.add_parser("random", help="从 TouchGal 随机获取一部 Gal（仅返回 uid）")
    _add_touchgal_auth_args(rand_p)
    rand_p.add_argument("--json", action="store_true")

    # random-full: random + VNDB + download, all-in-one
    randf_p = sub.add_parser("random-full", help="随机推荐 Gal，附带 VNDB 信息和最佳下载链接")
    _add_touchgal_auth_args(randf_p)
    randf_p.add_argument("--json", action="store_true")

    # find-download: search + auto-pick best CN version
    fd_p = sub.add_parser("find-download", help="搜索 Gal 并自动选最优中文版下载链接")
    fd_p.add_argument("keyword")
    _add_touchgal_auth_args(fd_p)
    fd_p.add_argument("--json", action="store_true")

    # touchgal search
    tg_p = sub.add_parser("search-touchgal", help="在 TouchGal 搜索 Gal")
    tg_p.add_argument("keyword")
    tg_p.add_argument("--limit", type=int, default=12)
    _add_touchgal_auth_args(tg_p)
    tg_p.add_argument("--json", action="store_true")

    # touchgal download
    dl_p = sub.add_parser("download", help="获取 TouchGal 游戏下载链接（需要 TouchGal 数字 ID）")
    dl_p.add_argument("touchgal_id", type=int, help="TouchGal 游戏的数字 ID（search-touchgal 结果中的 ID 字段）")
    dl_p.add_argument("--name", default="", help="游戏名（仅用于显示）")
    _add_touchgal_auth_args(dl_p)
    dl_p.add_argument("--json", action="store_true")

    # doctor
    sub.add_parser("doctor", help="检测 VNDB 和 TouchGal 连通性")

    args = parser.parse_args()

    try:
        if args.command == "vn":
            results = vndb_search_vn(args.keyword, args.limit)
            if args.json:
                print_json(results)
            elif len(results) == 1:
                print(_vn_summary(results[0]))
            else:
                print(format_vn_list(args.keyword, results))

        elif args.command == "character":
            results = vndb_search_character(args.keyword, args.limit)
            if args.json:
                print_json(results)
            elif len(results) == 1:
                print(_character_summary(results[0]))
            else:
                print(format_character_list(args.keyword, results))

        elif args.command == "producer":
            pros, vns_list = vndb_search_producer(args.keyword, args.limit)
            if args.json:
                print_json([{"producer": p, "vns": v} for p, v in zip(pros, vns_list)])
            elif len(pros) == 1:
                print(_producer_summary(pros[0], vns_list[0]))
            else:
                print(format_producer_list(args.keyword, pros))

        elif args.command == "id":
            result = vndb_lookup_id(args.vndb_id)
            if args.json:
                print_json(result)
            else:
                entity_type = result["type"]
                data = result["data"]
                if entity_type == "vn":
                    print(_vn_summary(data))
                elif entity_type == "character":
                    print(_character_summary(data))
                else:
                    print(_producer_summary(data))

        elif args.command == "event":
            data = vndb_event(args.rating)
            if args.json:
                print_json(data)
            else:
                print(format_event(data))

        elif args.command == "recent":
            data = vndb_recent(args.days, args.rating, args.limit)
            if args.json:
                print_json(data)
            else:
                print(format_recent(data))

        elif args.command == "top":
            data = vndb_top(args.tag, args.limit, args.rating)
            if args.json:
                print_json(data)
            else:
                print(format_top(data))

        elif args.command == "characters-of":
            data = vndb_characters_of(args.keyword, args.limit)
            if args.json:
                print_json(data)
            else:
                print(format_characters_of(data))

        elif args.command == "random":
            uid = touchgal_random(args.token, args.cf, args.nsfw)
            if args.json:
                print_json({"unique_id": uid, "url": TOUCHGAL_BASE + uid})
            else:
                print(f"随机获取到游戏页面：{TOUCHGAL_BASE}{uid}\nUnique ID：{uid}")

        elif args.command == "random-full":
            data = random_full(args.token, args.cf, args.nsfw)
            if args.json:
                print_json(data)
            else:
                print(format_random_full(data))

        elif args.command == "find-download":
            data = find_download(args.keyword, args.token, args.cf, args.nsfw)
            if args.json:
                print_json(data)
            else:
                print(format_find_download(data))

        elif args.command == "search-touchgal":
            results = touchgal_search(args.keyword, args.limit, args.token, args.cf, args.nsfw)
            if args.json:
                print_json(results)
            else:
                print(format_touchgal_list(args.keyword, results))

        elif args.command == "download":
            resources = touchgal_download(args.touchgal_id, args.token, args.cf, args.nsfw)
            if args.json:
                print_json(resources)
            else:
                print(format_download_resources(args.name or f"ID:{args.touchgal_id}", resources))

        elif args.command == "doctor":
            report = doctor()
            print_json(report)
            if not all(v.get("ok") for v in report.values()):
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
