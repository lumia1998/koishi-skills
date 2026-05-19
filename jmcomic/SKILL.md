---
name: jmcomic
description: Use when a user requests JMComic/禁漫天堂 comics by ID or keyword, including jmxxxxx, JMxxxxx, jm号, 禁漫, 禁漫本子, 我要看本子, 我要看jm, 我要看禁漫, 搜xxx本子, 给我jm, 下载jm, 来个禁漫, 随便来个本子, or any request to search or download a comic from JMComic and receive a password-protected ZIP file.
---

# JMComic ZIP Bot

## Overview

搜索和下载 JMComic/禁漫天堂 专辑，打包成带随机密码的 ZIP 文件发送给用户。

不要返回图片 URL、页面链接、PDF 链接。只发送 ZIP 文件和解压密码。

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

### 1. 随机模式（casual 无关键词请求）

"随便来个本子"、"给我整个本子看"等不含关键词时，不要询问，直接运行：

```bash
python scripts/jm_lookup.py random
```

### 2. 直接给 JM 号

用户给出 JM 号（如 `jm12345`、`JM12345`、`12345`）时，直接运行：

```bash
python scripts/jm_lookup.py zip 12345
```

### 3. 关键词搜索

```bash
python scripts/jm_lookup.py search "关键词" --limit 10
python scripts/jm_lookup.py search "关键词" --limit 10 --json
```

把纯文本列表发给用户，内部保留 JSON，等用户回复序号后取对应 ID 下载。序号必须在 1-N 范围内，超出则提示重新选。

### 4. 用户选定后下载

```bash
python scripts/jm_lookup.py zip <album_id>
```

## 处理下载输出

`zip` 和 `random` 命令成功后 stdout 输出：

```
zip_path=/absolute/path/to/[12345] title_1234567890.zip
zip_password=Xy7kQ2mR9n4L
album_id=12345
filename=[12345] title_1234567890.zip
```

取 `zip_path=` 后面的路径，发送该文件给用户，并告知 `zip_password=` 的值作为解压密码。

## Service Auto-Deploy

脚本自动检测后端，未运行时自动安装依赖并启动，等待最多 30 秒。

```bash
python scripts/jm_lookup.py doctor
```

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
