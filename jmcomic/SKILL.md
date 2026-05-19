---
name: jmcomic
description: Use when a bot or assistant needs JMComic/禁漫天堂 comic search or encrypted ZIP downloads, including jmxxxxx, JMxxxxx, jm号, 禁漫, 禁漫本子, 我要看本子, 我要看jm, 我要看禁漫, 搜xxx本子, 给我jm, 下载jm, 来个禁漫, 随便来个本子, or any request to search or download a comic from JMComic and receive a password-protected ZIP file.
---

# JMComic ZIP Bot

## Overview

Use this skill for conversational JMComic/禁漫天堂 搜索和下载。搜索阶段只给用户纯文本候选；下载阶段打包成带随机密码的 ZIP 文件发送。

不要返回图片 URL、页面 URL、封面 URL，也不要逐张发送图片。

## Configuration

通过 `jmcomic/config.local.json`、环境变量或 CLI 参数配置，优先级：CLI > 环境变量 > config.local.json > 默认值。

| 设置 | 环境变量 | CLI 参数 |
|---|---|---|
| API 地址 | `JMAPI_BASE` | `--api-base` |
| 项目目录 | `JMAPI_PROJECT_DIR` | `--project-dir` |
| 输出目录 | `JMAPI_OUT_DIR` | `--out` |
| 随机关键词池 | `JMAPI_RANDOM_KEYWORDS` | `--keywords`（random 子命令） |

示例 `config.local.json`：

```json
{
  "api_base": "http://127.0.0.1:8699",
  "project_dir": "D:/lumia/Desktop/claude_workspace/JMComic-Api",
  "out": "D:/lumia/Desktop/claude_workspace/koishi-skills/jmcomic/downloads",
  "random_keywords": "全彩,短篇,同人,校园,恋爱"
}
```

## When to Use

- `jm12345` / `JM12345` / `jm号12345`
- `我要看 jm12345` / `我要看jm12345`
- `给我 jm12345`
- `我要看禁漫` / `来个禁漫本子` / `我要看禁漫本子`
- `搜xxx本子` / `搜xxx漫画`
- `我要看本子，搜一下xxx`
- `随便来个本子` / `给我整个本子` / `来个本子` / `我要看本子`（无关键词随机）

## Conversation Flow

### 1. 随机 casual 请求

"随便来个本子"、"给我整个本子看"、"来个本子"等不含具体关键词时，不要询问，直接：

```bash
python scripts/jm_lookup.py random --out ./downloads
```

脚本从 `random_keywords` 配置池随机挑词搜索，未配置则从日榜随机选一本，生成加密 ZIP。发送 ZIP 并告知解压密码。

### 2. 直接给 JM 号

用户给出 JM 号（如 `jm12345`、`JM12345`、`12345`）时，直接：

```bash
python scripts/jm_lookup.py zip 12345 --out ./downloads
```

发送生成的 ZIP 文件，并告知解压密码。

### 3. 关键词搜索

```bash
python scripts/jm_lookup.py search "关键词" --limit 10
python scripts/jm_lookup.py search "关键词" --limit 10 --json
```

只把纯文本列表发给用户，内部保留 JSON 以便序号映射到 ID。

示例用户侧输出：

```text
找到 8 个和「keyword」相关的结果：

1. [12345] 某本子标题
2. [67890] 另一本标题
...

你要哪一本？可以回复 1-8 的序号或 JM 号。
```

### 4. 用户选定后下载

```bash
python scripts/jm_lookup.py zip <album_id> --out ./downloads
```

发送生成的 ZIP 文件，并告知解压密码。

## Reusable Helper Script

```bash
python scripts/jm_lookup.py doctor
python scripts/jm_lookup.py search "关键词" --limit 10
python scripts/jm_lookup.py search "关键词" --limit 10 --json
python scripts/jm_lookup.py zip 12345 --out ./downloads
python scripts/jm_lookup.py random --out ./downloads
```

`doctor` 检查服务状态、uv 是否安装、项目目录是否存在，不打印密码。

## Output Rules

- 搜索结果发纯文本列表。
- 不要返回图片 URL。
- 不要返回页面 URL。
- 不要直接发送 JSON 给用户。
- 下载结果只发送带随机密码的 ZIP 文件。
- 发送 ZIP 时明确告诉用户解压密码。
- ZIP 加密由 helper 脚本内置实现，不需要额外 pip 依赖。

## Error Handling

| 错误 | 回复 |
|---|---|
| uv 未安装 | `需要先安装 uv` |
| 项目目录不存在 | `找不到 JMComic-Api 项目目录，请检查 project_dir 配置` |
| 服务 30s 内未启动 | `服务启动超时，请检查日志` |
| 专辑不存在 (404) | `没找到这个 JM 号，可能已下架或号码有误` |
| 下载超时 | `下载超时，稍后重试` |
| 搜索无结果 | `没找到相关结果，换个关键词试试？` |
| 用户序号超出范围 | `只找到 N 个结果，请回复 1-N 的序号` |
