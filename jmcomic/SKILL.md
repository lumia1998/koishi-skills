---
name: jmcomic
description: Use this as the default skill for generic 本子 requests and for all JMComic/禁漫天堂 comic search or encrypted PDF downloads. Trigger on 推荐点本子, 推荐本子, 我要看本子, 我要看xxx的本子, 搜xxx本子, 搜xxx漫画, 随便来个本子, 来个本子, 给我整个本子, jmxxxxx, jmidxxxxx, JMxxxxx, jm号, 禁漫, 禁漫xxx, 禁漫搜xxx, 我要看jm, 我要看禁漫, 给我jm, 下载jm, or any request that should return a password-protected JMComic PDF. Prefer this over pica unless the user explicitly says 哔咔/pica, 章节/第几话, ZIP, or wants a Pica comic.
---

# JMComic PDF Bot

## Overview

搜索和下载 JMComic/禁漫天堂 专辑，发送带密码的加密 PDF 文件给用户。

脚本调用 Linux 宿主机上的新版 FastAPI `JMComic-Api`。如果 API 没有运行，脚本会在 Ubuntu/Debian 等 Linux 宿主机本地自动部署和启动服务，不使用 Docker。

不要返回图片 URL、页面链接。只发送加密 PDF 和解压密码。

## Configuration

通过 `jmcomic/config.local.json`、环境变量或 CLI 参数配置，优先级：CLI > 环境变量 > config.local.json > 默认值。

| 设置 | 环境变量 | CLI 参数 |
|---|---|---|
| API 地址 | `JMAPI_BASE` | `--api-base` |
| 项目目录 | `JMAPI_PROJECT_DIR` | `--project-dir` |
| API 仓库 | `JMAPI_REPO` | `--api-repo` |
| API 分支/提交 | `JMAPI_REF` | `--api-ref` |
| 绑定地址 | `JMAPI_BIND_HOST` | `--bind-host` |
| 启动超时秒数 | `JMAPI_START_TIMEOUT` | `--start-timeout` |
| 自动部署开关 | `JMAPI_AUTO_DEPLOY` | `--no-auto-deploy` |
| 输出目录 | `JMAPI_OUT_DIR` | `--out` |
| 随机关键词池 | `JMAPI_RANDOM_KEYWORDS` | `--keywords`（random 子命令） |

示例 `config.local.json`：

```json
{
  "api_base": "http://127.0.0.1:8699",
  "project_dir": "~/services/JMComic-Api",
  "api_repo": "https://github.com/FfmpegZZZ/JMComic-Api",
  "auto_deploy": true,
  "random_keywords": "全彩,短篇,同人,校园,恋爱"
}
```

默认值：`api_base = http://127.0.0.1:8699`，`project_dir` 和 `out` 根据脚本位置自动推导，只有 `random_keywords` 需要按需修改。

`JMAPI_REPO` 必须指向新版 FastAPI 项目仓库，仓库内应包含 `src/jmcomic_api/__main__.py`。如果你把改好的 API 发布到自己的 fork，需要把这里改成你的 fork 地址。

如果 Bot 和 API 在同一台宿主机运行，保持 `JMAPI_BASE=http://127.0.0.1:8699` 即可。如果 Bot 运行在容器里，`127.0.0.1` 指容器自身，需要把 `JMAPI_BASE` 配成宿主机或服务名地址。

Ubuntu 宿主机建议先确保这些命令可用：

```bash
sudo apt update
sudo apt install -y git python3.12 python3.12-venv curl
curl -LsSf https://astral.sh/uv/install.sh | sh
```

如果系统没有 `python3.12` 包，可以用 deadsnakes PPA、源码安装，或直接让 `uv` 管理 Python，但 API 项目要求 Python 3.12+。

## When to Use

- 通用本子请求默认用此 skill：`推荐点本子` / `推荐本子` / `我要看本子`
- `jm12345` / `jmid12345` / `JM12345` / `jm号12345`
- `我要看 jm12345` / `我要看jm12345`
- `给我 jm12345`
- `禁漫12345` / `禁漫 12345` / `禁漫搜xxx`
- `我要看禁漫` / `来个禁漫本子` / `我要看禁漫本子`
- `我要看xxx的本子` / `搜xxx本子` / `搜xxx漫画`
- `随便来个本子` / `给我整个本子` / `来个本子` / `我要看本子`（无关键词随机）

只有当用户明确说 `哔咔`、`pica`、`章节`、`第几话`、`zip` 或要求 Pica 漫画时，才改用 `pica` skill。

## Conversation Flow

### 1. 随机 casual 请求

"推荐点本子"、"推荐本子"、"随便来个本子"、"给我整个本子看"等不含具体关键词时，直接：

```bash
python scripts/jm_lookup.py random --out ./downloads
```

### 2. 直接给 JM 号

用户给出 JM 号（如 `jm12345`、`jmid12345`、`JM12345`、`禁漫12345`、`12345`）时，直接提取数字并调用：

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

`doctor` 检查服务状态、宿主机自动部署配置、uv、venv、Ghostscript，不打印密码。

## Service Auto-Deploy

脚本自动检测 `JMAPI_BASE` 的 `/health/live`：
- **服务已运行**：直接调用 FastAPI 接口
- **服务未运行且启用自动部署**：在 Linux 宿主机本地启动，不使用 Docker
- **项目目录不存在**：`git clone JMAPI_REPO` 到 `JMAPI_PROJECT_DIR`
- **首次运行**：在项目目录执行 `uv sync --no-dev` 安装依赖
- **后续运行**：复用 `.venv`，后台启动 `python -m jmcomic_api`

服务已在跑则完全跳过启动流程，每次调用只需 1-2 秒开销。

启动日志写入 API 项目目录下的 `jmcomic-api.log`。

Linux 后台启动使用独立 session，Koishi 调用结束后 API 进程会继续留在宿主机上运行。如果需要长期守护，建议后续把同一启动命令迁移到 systemd；skill 仍然会优先复用已经运行的服务。

新版 FastAPI 接口：
- 探活：`GET /health/live`
- 搜索：`GET /search?query=<关键词>&page=1`
- 下载 PDF：`GET /get_pdf/<album_id>?pdf=true&passwd=true&Titletype=2`

## Output Rules

- 搜索结果发纯文本列表，不发 URL。
- 下载结果只发加密 PDF 文件。
- 发送 PDF 时明确告诉用户解压密码（= JM 号，如 `12345`）。
- 超过 100MB 的 PDF 自动用 Ghostscript 压缩（未安装则跳过）。

## Error Handling

| 错误 | 回复 |
|---|---|
| git 未安装且项目目录不存在 | `需要先安装 git` |
| uv 未安装 | `需要先安装 uv` |
| 项目目录不存在 | 自动 `git clone JMAPI_REPO` 后继续 |
| API 仓库不是新版 FastAPI 项目 | `project dir exists but is not JMComic-Api` 或启动日志报错 |
| 服务 30s 内未启动 | `服务启动超时，请检查日志` |
| 专辑不存在 (404) | `没找到这个 JM 号，可能已下架或号码有误` |
| 下载超时 | `下载超时，稍后重试` |
| 搜索无结果 | `没找到相关结果，换个关键词试试？` |
| 用户序号超出范围 | `只找到 N 个结果，请回复 1-N 的序号` |
