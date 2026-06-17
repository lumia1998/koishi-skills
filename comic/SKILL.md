---
name: comic
description: 聚合漫画 skill，同时覆盖禁漫天堂(JM)和哔咔漫画(Bika)。通过本地 comic-api 服务的命令行工具提供漫画搜索、下载、排行榜、分类浏览、随机推荐等功能。触发词包含我要看本子、排行榜、分类本子、随机本子、直接下载等请求。
---

# Comic 聚合漫画 Skill

## Overview

通过本地运行的 **comic-api** (FastAPI 聚合服务，同时接入禁漫天堂和哔咔漫画) 为用户提供：

- 🔍 **聚合搜索**：一次搜索同时匹配禁漫 + 哔咔，返回最佳匹配和完整列表
- 📥 **章节下载**：下载指定章节为加密 PDF 文件，多章节时只下第一话并提示总话数
- 🏆 **排行榜**：查看日榜/周榜/月榜/总榜
- 📂 **分类浏览**：按分类（同人/全彩/人妻等）浏览漫画
- ⚡ **最近更新**：获取最新上架/更新 of 漫画
- 🎲 **随机推荐**：随机抽取一本好书

**大文件自适应压缩**：所有章节均生成为一个完整的单文件 PDF，不进行分卷分割。根据总页数智能限制 PDF 文件体积上限（比例为每 50 页限 10MB）：
- **≤ 50 页**：PDF 体积限制 10MB。如果超限，则自动通过降低图片质量重新压缩。
- **50 ~ 100 页（如 90 页）**：PDF 体积限制 20MB。如果超限，则自动降低图片质量重新压缩，小于限额直接发送。
- **200 ~ 250 页（如 203 页）**：PDF 体积限制 50MB。如果超限，则自动降低图片质量重新压缩。

## When to Use

- `jm12345` / `jmid12345` / `JM12345` / `禁漫12345`（JM 号数字 > 100 直接下载，否则搜索确认）
- `我要看花火的本子` / `花火本子` / `花火漫画`
- `高岛老师的 ba 本子` / `关于碧蓝档案的本子`（需先联网搜索作者/作品信息再调用 API）
- `给我来个崩铁同人本子` / `人妻全彩本子` / `我要看单行本`
- `推荐本子` / `随便来个本子` / `来个随机本子`
- `排行榜` / `日榜` / `周榜` / `月榜`
- `最近更新` / `新出的本子`

## Configuration

通过 `comic/config.local.json`、环境变量或 CLI 参数配置：

| 设置 | 环境变量 | CLI 参数 | 默认值 |
|---|---|---|---|
| API 地址 | `COMIC_API_BASE` | `--api-base` | `http://127.0.0.1:8699` |
| 项目目录 | `COMIC_API_PROJECT_DIR` | `--project-dir` | 自动计算（koishi-skills 同级目录下的 comic-api） |
| API 仓库 | `COMIC_API_REPO` | `--api-repo` | `https://github.com/lumia1998/comic-api` |
| 绑定地址 | `COMIC_API_BIND_HOST` | `--bind-host` | `127.0.0.1` |
| 启动超时 | `COMIC_API_START_TIMEOUT` | `--start-timeout` | `90` |
| 自动部署 | `COMIC_API_AUTO_DEPLOY` | `--no-auto-deploy` | `true` |
| 输出目录 | `COMIC_API_OUT_DIR` | `--out` | `/download` |
| 并发数 | `COMIC_API_CONCURRENCY` | `--concurrency` | `4` |

示例 `config.local.json`：

```json
{
  "api_base": "http://127.0.0.1:8699",
  "api_repo": "https://github.com/lumia1998/comic-api",
  "auto_deploy": true
}
```

## Conversation Flow

### 核心调用准则 (Core Rules)

> [!IMPORTANT]
> 1. **严禁无谓联网**：在处理排行榜、分类浏览、最新更新、随机推荐等请求时，底层的 `comic-api` 本地命令行工具已经自动实现了实时在线拉取的功能，**模型侧严禁调用 Google 等外部浏览器/联网搜索工具**，直接运行对应的 `leaderboard`、`category`、`latest` 或 `random` 本地子命令即可！
> 2. **分类匹配优先级最高**：用户请求某种题材/类型时，**必须优先检查**是否能匹配官方分类标签（如 `同人`、`全彩`、`耽美`、`少女漫畫`、`cosplay` 等）。若能匹配，必须优先调用 `category` 命令进行分类浏览；只有在官方分类完全不包含时，才退而使用 `search` 普通关键词搜索。

### 1. JM 号直接下载（数字 > 100）

用户说 `jm123456` 或 `禁漫123456`，提取数字 `123456`，直接下载第一话：

```bash
python scripts/comic_lookup.py download jm 123456
```

### 2. 明确关键词搜索

```bash
python scripts/comic_lookup.py search "关键词" --limit 10
```

返回带序号的列表（禁漫+哔咔混合），让用户选择后再下载：

```
🏆 最佳匹配 [禁漫|123456]:
  花火的故事  作者:某某某

找到 8 个结果：
1. [禁漫|123456] 花火的故事  作者:某某某
2. [哔咔|abc123] 花火同人志  作者:佚名
...

回复序号或「禁漫/哔咔|ID」下载。
```

### 3. 模糊描述 / 需要补充知识的搜索

用户说「高岛老师的 ba 本子」、「找个粉色头发女孩的本子」或「未亡人雪女的本子」等模糊/概念性请求时：

1. **对于画师/作品缩写（如“高岛 ba”）**：先用模型知识识别（「高岛老师」= 热门同人作者高岛，「ba」= 碧蓝档案/Blue Archive）。若不确定，联网搜索补充知识，对齐黑话与简写，构造精确的搜索词。
2. **对于视觉/特征描述（如“粉色头发女孩”）**：因为漫画数据库不支持直接检索视觉属性，模型必须先通过模型知识或联网搜索，转换提取出符合该视觉特征的热门二次元角色名称（例如：崩铁的“花火”、原神的“八重神子”、崩三的“爱莉希雅”或“后藤一里”等），再以角色名作为关键词进行检索。
3. **对于疑似标题、别名、短语或梗名（如“未亡人雪女”）**：先直接用原短语搜索 comic-api；如果无结果或结果明显不相关，必须联网搜索该短语，提取正式标题、日文/中文别名、作者、社团、角色名或作品名，再用 2-4 个精炼候选关键词依次回搜 comic-api。不要在这种情况下直接改走随机推荐。
4. **构造关键词并调用搜索**：
   * `python scripts/comic_lookup.py search "高岛 碧蓝档案" --limit 10`
   * `python scripts/comic_lookup.py search "花火 崩铁" --limit 10`
   * `python scripts/comic_lookup.py search "未亡人 雪女" --limit 10`
   * `python scripts/comic_lookup.py search "<联网查到的正式标题或作者>" --limit 10`
5. 返回列表让用户确认。

### 3.1 搜索无结果兜底

当 `search` 返回「没有找到任何结果」时，按请求类型处理：

- **具体标题/别名/短语/作者/角色请求**：先联网搜索补充背景，再把查到的正式标题、别名、作者、社团、角色、作品名拆成候选关键词，逐个调用 `search`。最多尝试 4 个候选关键词，并把最相关的结果列表给用户确认。
- **分类/题材请求**：优先检查分类映射并调用 `category`，分类不存在时再用关键词 `search`。
- **排行榜/分类浏览/最新/随机请求**：不要联网，直接调用本地 `leaderboard`、`category`、`latest` 或 `random` 子命令。
- **多轮仍无结果**：告诉用户「没找到准确结果」，并给出你已尝试的关键词，让用户补充作者、标题、角色或平台来源。

### 4. 分类/类型请求

用户说「来个全彩同人本子」、「人妻本子」、「单行本」：

```bash
# 禁漫分类: latest, doujin, single, short, hanman, meishi, cosplay, 3d
python scripts/comic_lookup.py category --source jm --name doujin

# 哔咔分类: 嗶咔漢化, 同人, 全彩, 少女漫畫, 耽美, 妹子, 治癒, 都市, 冒險
python scripts/comic_lookup.py category --source bika --name 全彩
```

常用分类映射：
- 同人 → jm:`doujin`, bika:`同人`
- 全彩 → bika:`全彩`
- 单行本/单本 → jm:`single`
- 短篇 → jm:`short`
- 人妻 → 搜索关键词 `人妻`
- 韩漫 → jm:`hanman`
- Cosplay/真人 → jm:`cosplay`
- 3D/CG → jm:`3d`
- 哔咔汉化 → bika:`嗶咔漢化`
- 少女漫画 → bika:`少女漫畫`
- 耽美/腐/BL → bika:`耽美`
- 妹子/萌妹 → bika:`妹子`
- 治愈 → bika:`治癒`
- 都市 → bika:`都市`
- 冒险 → bika:`冒險`

### 5. 排行榜推荐

```bash
python scripts/comic_lookup.py leaderboard --source jm --mode day
python scripts/comic_lookup.py leaderboard --source bika --mode week
```

返回前N名，让用户选择后再下载。

### 6. 随机推荐

```bash
python scripts/comic_lookup.py random --source jm
python scripts/comic_lookup.py random --source bika
```

### 7. 用户选择后下载

```bash
# 用户选了列表第2项，是 [禁漫|123456]
python scripts/comic_lookup.py download jm 123456

# 用户要第3话
python scripts/comic_lookup.py download jm 123456 --chapter <chapter_id>
```

## Download Output

`download` 命令成功后 stdout 输出（每行一个 KV）：

```
✅ 下载完成！
pdf_path=/absolute/path/to/123456.pdf
pdf_size=8.3MB
pdf_password=123456
comic_title=漫画标题
chapter_name=第1话
total_chapters=12
tip=这是第一话，共 12 话，如需其他话请告知章节序号
```

- 下载生成的 PDF 必须写入 `/download`。使用 `--out /download` 或省略 `--out`；脚本会拒绝 `/download` 之外的输出目录，并在每次下载前删除 `/download` 下超过 24 小时的旧文件。
- 发送 `pdf_path` 对应的 PDF 文件给用户
- PDF 文件有密码保护，发送文件时必须告知 `pdf_password`
- PDF 文件名必须使用密码本身，例如 `123456.pdf`
- 如果 `total_chapters > 1`，告知用户「这是第一话，共 N 话，需要其他话请告诉我」

## Multi-Chapter Handling

- 有多话时：**只下载第一话**，并列出所有章节 ID 供用户选择
- 用户说「下第3话」→ 先 `detail` 获取章节列表，找到第3话的 `chapter_id`，再 `download --chapter <id>`
- 禁止一次性下载全本（避免超大文件/超时）

## Adaptive PDF Compression

- **单文件体积限制规则**：单 PDF 文件大小限制为 `10 * math.ceil(total_pages / 50)` MB。
- **不分卷与自适应压缩逻辑**：
  - 必须将整话漫画打包为一个单一的 PDF 文件，**绝对禁止**进行分卷拆分发送。
  - 首先尝试以较好质量（JPEG quality=85）打包为 PDF。
  - 如果打包后的 PDF 体积超限（例如 90 页文件大小超限为 23MB，而 90 页的限制是 20MB），则程序会自动降低图片质量（例如从 85 到 60, 40, 20）进行 JPEG 重压缩，直到文件大小降至限制以内。
  - 命名规范：打包为 `<pdf_password>.pdf`，例如 `123456.pdf`。

## Service Auto-Deploy

检测 `COMIC_API_BASE` 服务健康状态：
- **运行中**：直接调用 API
- **未运行 + 自动部署启用**：
  1. `git clone` comic-api 仓库到 `project_dir`（若不存在）
  2. 检测本地运行环境；若 `.venv` 不存在，优先用 `uv venv` 创建环境
  3. 若 `.venv` 存在但缺少 `pypdf/curl_cffi/fastapi/uvicorn` 等关键依赖，自动用 `uv pip install -r requirements.txt` 修复（包含 `pypdf` 加密依赖）
  4. 如果宿主机没有 `uv`，回退为 Python 内置 `venv` + `pip install -r requirements.txt`
  5. 后台启动 `uvicorn main:app --host 127.0.0.1 --port 8699`
  6. 等待最多 90s 直到服务就绪

`doctor` 会检查服务、项目目录、`git`、`uv`、`.venv`、以及 `pypdf/curl_cffi/fastapi/uvicorn` 等运行依赖状态。若本地环境缺失或依赖不完整且自动部署启用，实际搜索/下载命令会触发上述 uv 部署/修复流程。

## Available Scripts

```bash
python scripts/comic_lookup.py doctor
python scripts/comic_lookup.py search "花火" [--source all|jm|bika] [--limit 10]
python scripts/comic_lookup.py detail jm 123456
python scripts/comic_lookup.py detail bika <comic_id>
python scripts/comic_lookup.py download jm 123456 [--chapter <ch_id>] [--out /download]
python scripts/comic_lookup.py download bika <comic_id> [--chapter <ch_id>]
python scripts/comic_lookup.py leaderboard [--source jm|bika] [--mode day|week|month|total] [--page 1]
python scripts/comic_lookup.py category [--source jm|bika] [--name doujin|同人|全彩...]
python scripts/comic_lookup.py latest [--source jm|bika] [--page 1]
python scripts/comic_lookup.py random [--source jm|bika]
```

## Error Handling

| 错误 | 处理 |
|---|---|
| 服务未运行 + 自动部署启用 | 自动克隆，优先用 uv 创建/修复 `.venv` 并安装 requirements，启动服务，最多等 90s |
| git 未安装 | 提示「需要先安装 git」 |
| 章节无图片 | 提示「该章节暂无图片，可能已下架」 |
| 搜索无结果 | 提示「没有找到结果，换个关键词或联网补充背景信息后再搜索」 |
| 下载超时 | 提示「下载超时，稍后重试」 |
| 哔咔未登录 | 提示「哔咔功能需要先在 comic-api 后台绑定账号」 |

## Output Rules

- 搜索结果发**纯文本列表**，不发图片 URL、Web 链接
- 下载结果只发 **单文件加密 PDF**，文件名为 `<pdf_password>.pdf`，并明确告知 `pdf_password`
- 多章节只下第一话，并告知总话数
