---
name: pica
description: Use when a bot or assistant needs Pica/哔咔 comic search or encrypted ZIP downloads, including 搜xxx漫画, 搜xxxx本子, 我要看本子, 给我整个本子看, 随便来个本子, pica, 哔咔, Pica account login, random comic selection, chapter selection, downloading comic pages, or sending password-protected zip files instead of image URLs.
---

# Pica Comic ZIP Bot

## Overview

Use this skill for conversational Pica/哔咔漫画搜索和下载。搜索阶段只给用户纯文本候选；下载阶段必须下载图片并打包成带密码 ZIP 文件发送。

不要返回图片 URL、页面 URL、封面 URL，也不要逐张发送图片。

## Configuration

Configure credentials through `pica/config.local.json`, environment variables, or CLI options. Precedence: CLI options > environment variables > `config.local.json` > defaults.

| Setting | Environment variable | CLI option |
| --- | --- | --- |
| Pica username | `PICA_USERNAME` | `--username` |
| Pica password | `PICA_PASSWORD` | `--password` |
| ZIP password | `PICA_ZIP_PASSWORD` | `--zip-password` |
| API host | `PICA_API_HOST` | `--api-host` |
| API key | `PICA_API_KEY` | `--api-key` |
| HMAC key | `PICA_HMAC_KEY` | `--hmac-key` |
| Random keyword pool | `PICA_RANDOM_KEYWORDS` | `--random-keywords` |
| Random chapter mode | `PICA_RANDOM_CHAPTER` | `--random-chapter` |

Copy `pica/config.local.example.json` to `pica/config.local.json`, then fill in your own Pica account, Pica password, and ZIP password. Do not commit `pica/config.local.json`; it is ignored by git and is meant for local secrets. Do not print the Pica account password in chat or logs. When sending the ZIP, tell the user the ZIP 解压密码 so they can open the file.

Example `pica/config.local.json`:

```json
{
  "username": "你的哔咔账号",
  "password": "你的哔咔密码",
  "zip_password": "ZIP解压密码",
  "random_keywords": ["全彩", "短篇", "同人", "校园", "恋爱"],
  "random_chapter": "first"
}
```

`PICA_RANDOM_KEYWORDS` is a comma-separated keyword pool used for casual requests such as “给我整个本子看” or “随便来个本子”. Default: `全彩,短篇,同人,校园,恋爱`. `PICA_RANDOM_CHAPTER` can be `first` or `random`; default is `first`.

## When to Use

Use this skill for messages like:

- `搜xxx漫画`
- `搜xxxx本子`
- `我要看本子`
- `给我整个本子看`
- `随便来个本子`
- `来个本子`
- `pica 搜一下 xxx`
- `哔咔 搜 xxx`
- `下载这个漫画第一话`
- `把这本漫画打包 zip`
- Any Pica/哔咔 comic request that should return a password-protected ZIP

## Conversation Flow

### 1. Random casual requests

For casual requests such as “给我整个本子看”, “随便来个本子”, “来个本子”, or “我要看本子” without a keyword, do not ask for a keyword. Use the configured random keyword pool and package a random result:

```bash
python scripts/pica_lookup.py random --out ./downloads
```

The helper chooses one keyword from `PICA_RANDOM_KEYWORDS`, searches it, randomly selects one comic from the result list, chooses the first chapter by default, and generates an encrypted ZIP. If `PICA_RANDOM_CHAPTER=random`, it chooses a random chapter instead.

Send the ZIP and tell the user the 解压密码.

### 2. Search first for broad requests

For search requests, call:

```bash
python scripts/pica_lookup.py search "关键词" --limit 10
python scripts/pica_lookup.py search "关键词" --limit 10 --json
```

Send only the plain text list to the user. Keep JSON internally so a follow-up number maps to the comic ID.

Example user-facing output:

```text
我找到了 12 个和「keyword」相关的结果，先显示前 10 个：
1. Example Title
作者：Example Author
ID：abc123
你要哪一本？可以回复序号或漫画 ID。
```

### 3. Ask for chapter if missing

If the user selected a comic but did not specify a chapter, call:

```bash
python scripts/pica_lookup.py chapters "comicId"
```

Show the chapter list and ask which chapter to package. `full` is allowed for full comic packaging, but it may take longer and produce a large file.

### 4. Generate encrypted ZIP

When the user gives a comic ID and chapter:

```bash
python scripts/pica_lookup.py zip "comicId" 1 --out ./downloads
python scripts/pica_lookup.py zip "comicId" full --out ./downloads
```

Send the generated ZIP file to the user. Also tell the user:

```text
解压密码：<configured PICA_ZIP_PASSWORD>
```

If the runtime cannot safely reveal environment values, say that the password is the configured `PICA_ZIP_PASSWORD` and provide it from the bot configuration layer if available.

## Reusable Helper Script

Use `scripts/pica_lookup.py` instead of rewriting Pica API logic:

```bash
python scripts/pica_lookup.py doctor
python scripts/pica_lookup.py search "关键词" --limit 10
python scripts/pica_lookup.py search "关键词" --limit 10 --json
python scripts/pica_lookup.py chapters "comicId"
python scripts/pica_lookup.py zip "comicId" 1 --out ./downloads
python scripts/pica_lookup.py zip "comicId" full --out ./downloads
python scripts/pica_lookup.py random --out ./downloads
```

`doctor` checks whether Pica username, Pica password, and ZIP password are configured. It does not print secret values.

## Output Rules

- 搜索结果发纯文本列表。
- 不要返回图片 URL。
- 不要返回页面 URL。
- 不要发送封面 URL。
- 不要直接发送 JSON 给用户。
- 下载结果只发送带密码 ZIP 文件。
- 发送 ZIP 时明确告诉用户解压密码。
- 不要把 Pica 登录密码发给用户。
- ZIP 加密由 helper 脚本内置实现，不需要额外 pip 依赖。

## Error Handling

| Failure | Bot response |
| --- | --- |
| Missing username/password | `Pica 账号未配置，请先配置 PICA_USERNAME 和 PICA_PASSWORD。` |
| Missing ZIP password | `ZIP 密码未配置，请先配置 PICA_ZIP_PASSWORD。` |
| Empty search result | `没找到相关漫画，换个关键词试试？` |
| Chapter not found | `没找到这一话，请换一个章节序号。` |
| Download timeout | `下载超时了，可以稍后重试或换一个章节。` |
