---
name: javbus
description: Use when a bot or assistant needs JavBus-style adult/NSFW movie metadata: 番号 lookup, actress/女优 search, title/keyword search, censored or uncensored/latest lists, random movie recommendations, random actress-style keyword recommendations, magnet links, cover URL, preview image URLs, or the jav-lumia1998s-projects.vercel.app API. Use only where adult content is allowed.
---

# JavBus Metadata Bot

## Overview

Use this skill to satisfy adult/NSFW movie metadata lookup requests through a JavBus-style API. It can search by code or keyword, show a numbered candidate list, resolve one selected movie, and return title/metadata, magnet links, cover URL, and preview image URLs.

Do not download, embed, or send image files. Only send image URLs.

Default API base:

```text
https://jav-lumia1998s-projects.vercel.app
```

## When to Use

Use this skill when the user asks for:

- 番号 lookup, such as `ABP-123` or “查一下 ABC-123”
- Actress/女优 search, such as “搜一下三上悠亚” or “来个某女优的片”
- Title/tag/keyword search
- Censored/latest list, such as “来个有码影片”
- Uncensored/latest list, such as “来个无码影片”
- Random movie recommendation, such as “随机来一个影片”
- Random uncensored/censored recommendation, such as “随便来个无码/有码”
- Magnet links / 磁链
- Cover URL / 封面 URL
- Preview image URLs / 样品图 URL

Do not use this outside adult/NSFW contexts where the bot is allowed to handle this content.

## Request Modes

Classify the user request before choosing a command:

| User message | Mode | Bot behavior |
| --- | --- | --- |
| “查 ABP-123” | Direct code lookup | Call `detail "ABP-123"` and return formatted detail |
| “搜三上悠亚” | Actress/keyword search | Call `search "三上悠亚"`, show list, wait for selection |
| “搜教师题材” | Title/tag/keyword search | Call `search "教师"`, show list, wait for selection |
| “给我来个无码影片” | Random uncensored movie | Call `random --uncensored`, return formatted detail immediately |
| “给我来个有码影片” | Random censored movie | Call `random`, return formatted detail immediately |
| “最新无码有什么” | Latest uncensored list | Call `latest --uncensored`, show list, wait for selection |
| “随机推荐个女优/演员” | Random recommendation seed | Use `latest` or `random` detail, then suggest one actor name from the result; if no actor exists, return the random movie detail |

For search/list modes, do not fetch magnets for every candidate. Show the list first, store IDs internally, and fetch detail only after the user chooses.

## API Endpoints

| Purpose | Endpoint |
| --- | --- |
| Movie detail by code | `GET /api/movies/<movieId>` |
| Magnets for detail result | `GET /api/magnets/<movieId>?gid=<gid>&uc=<uc>` |
| Keyword search | `GET /api/movies/search?keyword=<encoded keyword>` |
| Keyword search including unreleased | `GET /api/movies/search?magnet=all&keyword=<encoded keyword>` |
| Latest censored list | `GET /api/movies` |
| Latest uncensored list | `GET /api/movies?type=uncensored` |
| Latest including unreleased | `GET /api/movies?magnet=all` |

## Conversation Flow

### 1. Direct code lookup

If the user gives a clear code/番号, call detail directly:

```bash
python scripts/javbus_lookup.py detail "ABP-123"
```

Send the formatted text result. It should include:

- Title / 标题
- Code / 番号
- Date / 发行日期
- Length / 时长
- Actors / 演员
- Cover URL / 封面URL
- Magnet links / 磁链
- Preview image URLs / 预览图URL

### 2. Keyword search

For keyword search, first show candidates and wait for selection:

```bash
python scripts/javbus_lookup.py search "keyword" --limit 10
python scripts/javbus_lookup.py search "keyword" --limit 10 --json
```

Send only the plain text list to the user. Keep the JSON internally so a follow-up number can map back to the movie `id`.

Example user-facing list:

```text
我找到了这些和「keyword」相关的影片：
1. Example Title
番号：ABC-123 / 发行日期：2026-05-13 / 标签：高清, 字幕
封面URL：https://example.com/cover.jpg
你要哪个？可以回复序号或番号。
```

When the user chooses a number or code, call detail on that `id`.

### 3. Latest and random recommendations

For latest movie lists:

```bash
python scripts/javbus_lookup.py latest --limit 10
python scripts/javbus_lookup.py latest --uncensored --limit 10
```

Show the list and wait for selection before calling detail.

For direct random recommendations, return a detail result immediately:

```bash
python scripts/javbus_lookup.py random --magnet-limit 5
python scripts/javbus_lookup.py random --uncensored --magnet-limit 5
```

Use `random --uncensored` for requests like “给我来个无码影片”. Use `random` for “给我来个有码影片” or generic “随机来个影片”. The response should be formatted detail text with title, date, magnets, cover URL, and preview image URLs.

For random actress/actor recommendations:

```bash
python scripts/javbus_lookup.py random-actor
python scripts/javbus_lookup.py random-actor --uncensored
```

Send the returned actor name. If the user then asks for that actor's movies, run `search "<actor name>"` and show a candidate list.

## Reusable Helper Script

Use `scripts/javbus_lookup.py` instead of rewriting requests:

```bash
python scripts/javbus_lookup.py search "keyword" --limit 10
python scripts/javbus_lookup.py search "keyword" --limit 10 --json
python scripts/javbus_lookup.py detail "ABP-123"
python scripts/javbus_lookup.py detail "ABP-123" --magnet-priority cn --magnet-limit 5
python scripts/javbus_lookup.py latest --limit 10
python scripts/javbus_lookup.py latest --uncensored --limit 10
python scripts/javbus_lookup.py random --magnet-limit 5
python scripts/javbus_lookup.py random --uncensored --magnet-limit 5
python scripts/javbus_lookup.py random-actor
python scripts/javbus_lookup.py random-actor --uncensored
```

Options:

| Option | Meaning |
| --- | --- |
| `--api <url>` | Override the API base URL |
| `--json` | Return raw JSON for internal state |
| `--magnet-priority default` | Keep API order |
| `--magnet-priority cn` | Put subtitle/中文字幕-like magnets first |
| `--magnet-priority size-asc` | Smallest magnets first |
| `--magnet-priority size-desc` | Largest magnets first |
| `--magnet-limit N` | Return at most N magnets |
| `--magnet-limit -1` | Return all magnets |
| `--pool-size N` | For random commands, choose from the latest N candidates |
| `--uncensored` | Use uncensored/无码 list where supported |
| `--include-unreleased` | Include unreleased/all-magnet list where supported |

## Output Rules

- Send image URLs as text: `封面URL：...`, `预览图URL：...`.
- Do not call image upload/file publish tools for cover or preview images.
- Do not convert remote images to base64.
- Do not embed markdown/HTML image tags.
- Send magnet links as plain text.
- For keyword/latest lists, show candidates first and wait for selection.
- For direct code lookup, returning detail immediately is OK.

## Error Handling

| Failure | Bot response |
| --- | --- |
| Empty search result | “没找到相关影片，换个关键词试试？” |
| Detail not found | “没找到这个番号的信息，请检查番号是否正确。” |
| API timeout/network failure | “查询服务暂时没响应，稍后再试。” |
| No magnets | “找到了影片信息，但暂时没有磁链。” |
| Invalid selection | “这个序号/番号不在刚才的列表里，请重新选。” |

## Common Mistakes

- Do not send image files; send image URLs only.
- Do not lose search state before the user chooses.
- Do not send raw JSON to the user unless they explicitly ask for JSON.
- Do not call `/api/magnets/<movieId>` before reading `gid` and `uc` from `/api/movies/<movieId>`.
- Do not assume a keyword search result is the intended movie; show a list and wait for selection.
