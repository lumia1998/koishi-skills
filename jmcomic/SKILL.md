---
name: jmcomic
description: Use when a bot or assistant needs JMComic/禁漫天堂 comic search or encrypted PDF downloads, including jmxxxxx, JMxxxxx, jm号, 禁漫, 禁漫本子, 我要看本子, 我要看jm, 我要看禁漫, 搜xxx本子, 给我jm, 下载jm, 来个禁漫, 随便来个本子, or any request to search or download a comic from JMComic and receive a password-protected PDF file.
---

# JMComic PDF Bot

## Overview

搜索和下载 JMComic/禁漫天堂 专辑，发送带密码的加密 PDF 文件给用户。

不要返回图片 URL、页面链接。只发送加密 PDF 和解压密码。

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
- `随便来个本子` / `给我整个本子` / `来个本子` / `我要看本子`（无关键词随机）

## Conversation Flow

### 1. 随机 casual 请求

"随便来个本子"、"给我整个本子看"等不含具体关键词时，直接：

```bash
python scripts/jm_lookup.py random --out ./downloads
```

### 2. 直接给 JM 号

用户给出 JM 号（如 `jm12345`、`JM12345`、`12345`）时，直接：

```bash
python scripts/jm_lookup.py get 12345 --out ./downloads
```

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
python scripts/jm_lookup.py get <album_id> --out ./downloads
```

## 处理下载输出

`get` 和 `random` 命令成功后 stdout 输出：

```
pdf_path=/absolute/path/to/[12345] title.pdf
pdf_password=12345
album_id=12345
filename=[12345] title.pdf
```

发送 `pdf_path` 的文件给用户，并告知 `pdf_password`（即专辑 ID）作为解压密码。

## Reusable Helper Script

```bash
python scripts/jm_lookup.py doctor
python scripts/jm_lookup.py search "关键词" --limit 10
python scripts/jm_lookup.py search "关键词" --limit 10 --json
python scripts/jm_lookup.py get 12345 --out ./downloads
python scripts/jm_lookup.py random --out ./downloads
```

`doctor` 检查服务状态、uv、venv、Ghostscript，不打印密码。

## Service Auto-Deploy

脚本自动检测 `.venv` 是否存在：
- **首次运行**：执行 `uv sync --no-dev` 安装依赖（只跑一次）
- **后续运行**：跳过安装，直接启动 uvicorn

服务已在跑则完全跳过启动流程，每次调用只需 1-2 秒开销。

## Output Rules

- 搜索结果发纯文本列表，不发 URL。
- 下载结果只发加密 PDF 文件。
- 发送 PDF 时明确告诉用户解压密码（= JM 号，如 `12345`）。
- 超过 100MB 的 PDF 自动用 Ghostscript 压缩（未安装则跳过）。

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
