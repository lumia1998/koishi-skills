---
name: galgame
description: "Use when a user says anything related to Galgame / visual novels in Chinese or Japanese: asking to recommend a Gal, asking what's releasing today or recently, what character birthdays are today, asking for info about a VN title/character/developer, asking if a specific game has a Chinese patch or download link, asking about top-rated VNs by genre/tag, listing characters in a game, or looking up a VNDB ID. Do not use for music, JAV, anime/manga, or unrelated content."
---

# Galgame Box — VNDB + TouchGal

## Overview

This skill handles all Galgame / 视觉小说 requests without asking the user to pick commands or versions. The bot interprets the user's intent and runs the appropriate script automatically.

Two data sources:
- **VNDB** — visual novel database: titles, characters, developers, ratings, tag-based ranking, event calendar
- **TouchGal** — patch/resource site: download links, Chinese localization patches

**Core rule**: always run a command first, then respond. Never answer VN facts, ratings, or resource availability from memory alone.

---

## Intent → Command Table

Read the full user message and pick the single best-fit row. When multiple rows could apply, the one higher in the table takes priority.

| User says (examples) | Intent | Command |
| --- | --- | --- |
| "随便推荐一个 Gal" / "推荐一部 Gal" / "随机来个" / "今天玩什么" / "再来一个" / "换一个" | Random recommendation | `random-full` |
| "今天有什么 Gal 发售" / "Gal 日历" / "今日资讯" / "今天哪些角色生日" / "今天有什么新 Gal" / "今天 gal 圈有什么" | Today's calendar | `event` |
| "最近有什么好 Gal 出" / "这个月出了什么" / "最近发售了什么" / "近期新作" / "最近出了哪些值得玩的" | Recent releases | `recent` |
| "有没有催泪向推荐" / "有什么好的百合 Gal" / "推荐几部 NTR 的" / "高分恋爱向 Gal 有哪些" / "评分高的 Gal 有哪些" / "Gal 评分榜" | Top by genre/tag | `top "<tag>"` or `top` |
| "有没有千恋万花的资源" / "帮我找 CLANNAD 的下载" / "xxx 有中文补丁吗" / "xxx 哪里下" / "xxx 在哪下载" / "帮我找 xxx 的汉化" / "xxx 有汉化吗" | Resource lookup | `find-download "<game>"` |
| "CLANNAD 是什么游戏" / "介绍一下白色相簿2" / "xxx 好不好玩" / "xxx 剧情怎么样" / "xxx 多久打完" / "xxx 有几条线" / "xxx 值得玩吗" / "查 v4" | VN info | `vn "<keyword>"` or `id v4` |
| "CLANNAD 里有哪些角色" / "xxx 的女主角是谁" / "xxx 女主叫什么" / "xxx 角色列表" / "xxx 有几个女主" | Characters in a VN | `characters-of "<vn name>"` |
| "查古河渚" / "古河渚是哪个游戏的" / "c114 是谁" / "查一下这个角色" | Character info | `character "<keyword>"` or `id c114` |
| "Key 出了哪些游戏" / "VisualArt's 是什么公司" / "这个厂商出过什么" / "查 p22" | Developer info | `producer "<keyword>"` or `id p22` |

### Ambiguity rules

- "推荐一下 CLANNAD" with a specific title → `vn "CLANNAD"` (info, not random)
- "CLANNAD 有没有汉化" / "xxx 哪里下载" → `find-download`, not `vn`
- "再来一个" / "换一个" after a recommendation → `random-full` again
- "A 和 B 哪个好" → run `vn "A"` and `vn "B"` separately, then compare ratings from output
- "这游戏多久打完" / "打完要多少小时" → `vn "<game>"` (length_minutes is in the output)
- User mentions only a character name with no game context → `character "<name>"`
- User asks for characters **of a specific game** → `characters-of "<game>"`

---

## Core Flows

### 1. Random Recommendation（随机推荐）

```bash
python galgame/scripts/galgame_box.py random-full
```

One command returns: game title, VNDB rating, developer, cover URL, page URL, **plus the best Chinese download link automatically picked**. Send directly, no follow-up needed.

---

### 2. Today's Calendar（今日资讯）

```bash
python galgame/scripts/galgame_box.py event
```

Returns today's (UTC+8) new releases + character birthdays, filtered to VNDB rating ≥ 75. Send directly.

If the user wants only birthdays or only releases, still run `event` — the output has both sections clearly labeled.

---

### 3. Recent Releases（最近新作）

```bash
python galgame/scripts/galgame_box.py recent
python galgame/scripts/galgame_box.py recent --days 7    # 近一周
python galgame/scripts/galgame_box.py recent --days 90   # 近三个月
```

Returns VNs released in the past N days (default 30), sorted by release date descending, filtered to rating ≥ 70. Includes cover URLs. Send directly.

---

### 4. Top / Tag-based Ranking（高分榜 / 按类型推荐）

```bash
python galgame/scripts/galgame_box.py top                  # global top (rating ≥ 80)
python galgame/scripts/galgame_box.py top "催泪"            # tearjerker / utsuge
python galgame/scripts/galgame_box.py top "百合"            # yuri
python galgame/scripts/galgame_box.py top "恋爱"            # romance
python galgame/scripts/galgame_box.py top "NTR"
python galgame/scripts/galgame_box.py top "isekai" --rating 75
```

The tag argument is searched on VNDB's tag database first (Japanese/English tag names), then falls back to VN keyword search. Send results directly.

**Keyword extraction**: strip filler words from the user message to get the tag. Examples:
- "有没有催泪向推荐" → `top "催泪"`
- "推荐几部好的百合 Gal" → `top "百合"`
- "高分恋爱向" → `top "恋爱"`
- "Gal 评分榜" → `top` (no tag)

---

### 5. Resource / Download Lookup（找资源 / 下载）

```bash
python galgame/scripts/galgame_box.py find-download "千恋万花"
python galgame/scripts/galgame_box.py find-download "CLANNAD"
```

One command: searches TouchGal → picks best game match → **auto-selects the Chinese/汉化 version** (zh-Hans > zh-Hant > any note containing 汉化/中文 > fallback to any with links) → returns links. Do not ask user which version.

Output always includes the TouchGal page URL. If no resources: tell user and give the page URL for them to check manually.

---

### 6. VN Info（作品信息）

```bash
python galgame/scripts/galgame_box.py vn "白色相簿2"
python galgame/scripts/galgame_box.py id v4
```

- **1 result** → script returns full detail (title, rating, developer, length, cover URL). Send directly.
- **Multiple results** → script returns a numbered list. Send the list. When user picks a number or name, run `id <vndb-id>` with the chosen entry's ID.

Use output `length_minutes` to answer "多久打完" questions: `length_minutes / 60` hours.

---

### 7. Characters in a VN（作品角色列表）

```bash
python galgame/scripts/galgame_box.py characters-of "CLANNAD"
python galgame/scripts/galgame_box.py characters-of "白色相簿2"
```

Returns all characters in the best-matching VN, with gender, birthday, height, and image URL. Send directly.

When user asks "女主是谁" / "女主角叫什么": run `characters-of` and filter the output to female (`sex: f`) characters before sending.

---

### 8. Character Info（角色信息）

```bash
python galgame/scripts/galgame_box.py character "古河渚"
python galgame/scripts/galgame_box.py id c114
```

Same list/detail logic as VN info.

---

### 9. Developer Info（厂商信息）

```bash
python galgame/scripts/galgame_box.py producer "Key"
python galgame/scripts/galgame_box.py id p22
```

Returns company details + top-rated works list. Send directly if 1 result, show list if multiple.

---

## Multi-turn Patterns

| Situation | Action |
| --- | --- |
| User said "再来一个" / "换一个" / "还有吗" after a recommendation | Run `random-full` again |
| User asked about a VN and then "有汉化吗" / "能下载吗" | Run `find-download "<same game name>"` |
| User got a character list and then asked "介绍一下 XX" | Run `id <vndb-id of that character>` |
| User asked "A 和 B 哪个好" | Run `vn "A"` and `vn "B"` separately, compare rating + length in response |
| User said "这个游戏的角色有哪些" after VN info was shown | Run `characters-of "<vn name from previous turn>"` |

---

## Output Rules

- Send cover/image URLs as plain text: `封面URL：https://...`
- Send download links as plain text. Do not call file upload tools.
- Do not embed markdown image tags or download remote images.
- Send script output directly without rewrapping for `random-full`, `find-download`, `event`, `recent`, `top`, `characters-of`.
- For VN/character/producer with multiple results: send the numbered list as-is, then wait for user choice.

---

## Error Handling

| Situation | Bot response |
| --- | --- |
| `find-download` returns "没找到" | "TouchGal 上暂时没找到「xxx」的资源，可能还没有中文补丁，换个关键词试试？" |
| `find-download` returns "暂无可用下载资源" | "找到了游戏页面但目前没有下载资源，可以去 TouchGal 页面看看：[page_url]" |
| `event` has no entries | "今天 Gal 界比较安静，没有新发售也没有角色生日（评分阈值 75+）。" |
| `recent` has no entries | "最近这段时间没有符合条件的新发售，可以降低评分阈值或扩大时间范围再试。" |
| `top` has no entries | "没找到「xxx」相关的高分作品，可能是标签名称不匹配，换个关键词试试？" |
| `vn`/`character` returns no results | "VNDB 上没找到相关内容，换个关键词试试？" |
| Network error | "信息获取失败，可能是网络问题，稍后再试。TouchGal 若持续失败可能需要配置 cf_clearance。" |

---

## Script Reference

```bash
# ── Bot-driven commands (run automatically based on intent) ──────────────────
python galgame/scripts/galgame_box.py random-full              # random + VNDB + best download
python galgame/scripts/galgame_box.py event                    # today releases + birthdays
python galgame/scripts/galgame_box.py recent                   # recent 30-day releases
python galgame/scripts/galgame_box.py recent --days 7          # recent 7-day releases
python galgame/scripts/galgame_box.py top                      # global top-rated
python galgame/scripts/galgame_box.py top "催泪"               # top by tag
python galgame/scripts/galgame_box.py find-download "game"     # search + auto CN version

# ── Info lookups ─────────────────────────────────────────────────────────────
python galgame/scripts/galgame_box.py vn "keyword"
python galgame/scripts/galgame_box.py characters-of "vn name"
python galgame/scripts/galgame_box.py character "keyword"
python galgame/scripts/galgame_box.py producer "keyword"
python galgame/scripts/galgame_box.py id v4

# ── Auth options (when token is configured) ──────────────────────────────────
python galgame/scripts/galgame_box.py random-full --token <T> --cf <C> --nsfw
python galgame/scripts/galgame_box.py find-download "game" --token <T> --cf <C>

# ── Connectivity check ───────────────────────────────────────────────────────
python galgame/scripts/galgame_box.py doctor
```

| Flag | Meaning |
| --- | --- |
| `--json` | Raw JSON for internal chaining |
| `--token T` | TouchGal login token (NSFW / restricted resources) |
| `--cf C` | CloudFlare `cf_clearance` cookie |
| `--nsfw` | Enable NSFW content on TouchGal (default SFW) |
| `--days N` | `recent`: look back N days (default 30) |
| `--rating N` | Min VNDB rating threshold |
| `--limit N` | Max results |
