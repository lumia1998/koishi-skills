---
name: jmcomic
description: Use when a user requests JMComic/禁漫天堂 comics by ID or keyword, including jmxxxxx, JMxxxxx, jm号, 禁漫, 禁漫本子, 我要看本子, 我要看jm, 我要看禁漫, 搜xxx本子, 给我jm, 下载jm, 来个禁漫, 随便来个本子, or any request to search or download a comic from JMComic and receive a password-protected ZIP file.
---

# JMComic ZIP Bot

## Overview

Use this skill for JMComic/禁漫天堂搜索和下载。  
后端自动检测服务状态并按需启动，下载专辑并打包成带随机密码的 ZIP 文件。  
不要返回图片 URL，只发 ZIP 文件和解压密码。

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

**默认值**：api_base = `http://127.0.0.1:8699`，project_dir 指向工作区中的 `JMComic-Api`，out 指向 skill 目录下的 `downloads/`。

## When to Use

- `jm12345` / `JM12345` / `jm号12345`
- `我要看 jm12345` / `我要看jm12345`
- `给我 jm12345`
- `我要看禁漫` / `来个禁漫本子` / `我要看禁漫本子`
- `搜xxx本子` / `搜xxx漫画`
- `我要看本子，搜一下xxx`
- `下载 JMComic xxx`
- `随便来个本子` / `给我整个本子` / `来个本子` / `我要看本子`（无关键词随机）

## Conversation Flow

### 1. 随机模式（无关键词 casual 请求）

用户说"随便来个本子"、"给我整个本子看"、"来个本子"等不含具体关键词时，**不要问关键词，直接随机**：

```bash
python scripts/jm_lookup.py random
```

脚本从 `random_keywords` 配置池里随机挑一个关键词搜索，若未配置则直接从日榜随机选一本，下载打包后返回。

### 2. 直接给 JM 号 → 直接下载

如果用户输入中包含纯数字 JM 号（如 `jm12345`、`JM12345`、`12345`），**不要搜索，直接下载**：

```bash
python scripts/jm_lookup.py zip 12345
```

脚本输出格式（逐行）：
```
zip_path=/absolute/path/to/file.zip
zip_password=Xy7kQ2mR9n4L
album_id=12345
filename=[12345] title.zip
```

解析以上输出后，发送 ZIP 文件并告诉用户解压密码。

### 3. 关键词搜索 → 列出结果让用户选

调用：
```bash
python scripts/jm_lookup.py search "关键词" --limit 10
python scripts/jm_lookup.py search "关键词" --limit 10 --json
```

发纯文本列表给用户，内部保留 JSON 以便后续步骤用序号或 ID 对应。

示例用户侧输出：
```
找到 8 个和「keyword」相关的结果：

1. [12345] 某本子标题
2. [67890] 另一本标题
...

你要哪一本？回复序号或 JM 号。
```

### 4. 用户选定后 → 下载打包

```bash
python scripts/jm_lookup.py zip <album_id>
```

发送 ZIP 文件并告知密码。

## Service Auto-Deploy

脚本会自动检测后端是否运行：
- 运行中 → 直接使用
- 未运行 → 自动 `uv pip install` + 后台启动 uvicorn，等待最多 30 秒

若 `uv` 未安装或 `JMComic-Api` 项目目录不存在，脚本会明确报错。

诊断命令：
```bash
python scripts/jm_lookup.py doctor
```

## Output Rules

- 搜索结果只发纯文本，不发 URL
- 下载结果只发带随机密码的 ZIP 文件
- 每次下载密码不同（随机生成），发送时明确告知用户
- 不要发裸图、页面链接、PDF 链接
- 不要把 config.local.json 中的配置内容打印给用户

## Error Handling

| 错误 | 回复 |
|---|---|
| uv 未安装 | `需要先安装 uv，参考 https://github.com/astral-sh/uv` |
| JMComic-Api 项目目录不存在 | `找不到 JMComic-Api 项目目录，请检查 project_dir 配置` |
| 服务 30s 内未启动 | `服务启动超时，请检查 JMComic-Api 日志` |
| 专辑不存在 | `没找到这个 JM 号，可能已下架或号码有误` |
| 下载超时 | `下载超时，稍后重试或换一个专辑` |
| 搜索无结果 | `没找到相关结果，换个关键词试试？` |
