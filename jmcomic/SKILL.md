---
name: jmcomic
description: Use when a user requests JMComic/禁漫天堂 comics by ID or keyword, including jmxxxxx, JMxxxxx, jm号, 禁漫, 禁漫本子, 我要看本子, 我要看jm, 我要看禁漫, 搜xxx本子, 给我jm, 下载jm, 来个禁漫, 随便来个本子, or any request to search or download a comic from JMComic and receive a password-protected ZIP file.
---

# JMComic ZIP Bot

## Overview

This skill runs on **OpenTerminal** — you execute shell commands and send the resulting local file back to the user via Koishi/ChatLuna.

**CRITICAL**: The script outputs a local file path (`zip_path=...`). You MUST send that local file using OpenTerminal's file-sending capability. Do NOT invent download links, do NOT use file.io or any upload service, do NOT paste the path as text. The file already exists on disk — just send it.

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

### 3. 关键词搜索 → 列出结果让用户选

```bash
python scripts/jm_lookup.py search "关键词" --limit 10
python scripts/jm_lookup.py search "关键词" --limit 10 --json
```

把纯文本列表发给用户，**内部记住 JSON 数据**，等用户回复序号后用对应 ID 下载。

**序号必须在列表范围内。** 脚本输出"找到 N 个结果"，用户只能选 1-N，超出范围要提示重新选。

### 4. 用户选定后 → 下载打包

```bash
python scripts/jm_lookup.py zip <album_id>
```

## 解析脚本输出并发送文件

脚本 stdout 包含以下几行（`zip` 和 `random` 命令共用）：

```
zip_path=/absolute/path/to/[12345] title_1234567890.zip
zip_password=Xy7kQ2mR9n4L
album_id=12345
filename=[12345] title_1234567890.zip
```

**处理步骤（严格按此执行）**：

1. 从 stdout 提取 `zip_path=` 后面的完整绝对路径
2. 用 OpenTerminal 把该路径的文件发送给用户
3. 同时告诉用户解压密码（`zip_password=` 的值）
4. **不要上传到任何第三方服务**，不要生成下载链接，文件就在本地磁盘

## Service Auto-Deploy

脚本会自动检测后端是否运行：
- 运行中 → 直接调用
- 未运行 → 自动安装依赖并后台启动 uvicorn，等待最多 30 秒

诊断命令：
```bash
python scripts/jm_lookup.py doctor
```

## Output Rules

- 搜索结果只发纯文本列表，不发 URL
- 下载结果：用 OpenTerminal 发本地 ZIP 文件 + 告诉用户解压密码
- 绝对不要发裸图、页面链接、PDF 链接、上传链接
- 不要把配置文件内容打印给用户

## Error Handling

| 错误 | 回复 |
|---|---|
| uv 未安装 | `需要先安装 uv` |
| 项目目录不存在 | `找不到 JMComic-Api 项目目录，请检查 project_dir 配置` |
| 服务 30s 内未启动 | `服务启动超时，请检查日志` |
| 专辑不存在 (404) | `没找到这个 JM 号，可能已下架或号码有误` |
| 下载超时 | `下载超时，稍后重试` |
| 搜索无结果 | `没找到相关结果，换个关键词试试？` |
| 用户选的序号超出范围 | `只找到 N 个结果，请回复 1-N 的序号` |
