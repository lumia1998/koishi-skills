# koishi-skills

给 Koishi-ChatLuna / Open Terminal 后端使用的 bot skill 集合。每个 skill 目录包含：

- `SKILL.md` — bot/assistant 在对话时读取的使用说明，定义触发规则、意图映射和调用方式。
- `scripts/` — 纯 Python 确定性脚本，CLI 接口，bot 通过 `python scripts/xxx.py <subcommand>` 调用。
- `tests/` — 单元测试，覆盖格式化逻辑和 CLI 入口，不依赖真实网络。

## 工作方式

```
用户消息
    ↓
bot 读取 SKILL.md（触发条件 + 意图表）
    ↓
识别意图 → 调用对应脚本命令
    ↓
脚本返回纯文本或 JSON → bot 直接发送给用户
```

脚本只做数据获取和格式化，不含对话逻辑。对话决策（何时调用、如何回复）全部在 SKILL.md 里描述。

## 依赖

所有脚本只使用 Python 标准库，**无需 pip install** 任何第三方包（music skill 的 ffmpeg 会在首次运行时自动下载到 `.cache/` 目录）。

Python 版本要求：3.10+

## Skills

### music

用于点歌、搜歌、下载并发送音频文件。**需要用户从候选列表中选择**，宽泛请求（"xxx 的歌"）不会自动播放第一首。

典型触发：`我想听 alanwalker 的歌` / `点一首周杰伦` / `我要听 Faded 2.0`

流程：搜索网易云 → 给用户纯文本候选列表 → 用户选择 → 解析 Meting API 直链 → ffmpeg 转 MP3 → 发送文件。

```bash
python music/scripts/meting_music.py search "alanwalker" --limit 10
python music/scripts/meting_music.py format-list "alanwalker" --limit 10
python music/scripts/meting_music.py download <songId> --out ./downloads/song.mp3
python music/scripts/meting_music.py doctor
```

---

### javbus

用于 JavBus 风格的影片元数据查询和随机推荐。只返回文本、磁链、封面 URL、预览图 URL，不下载或发送图片。

典型触发：`查 ABP-123` / `搜女优 xxx` / `给我来个无码影片` / `随机推荐个女优`

```bash
python javbus/scripts/javbus_lookup.py detail "ABP-123"
python javbus/scripts/javbus_lookup.py search "keyword" --limit 10
python javbus/scripts/javbus_lookup.py latest --uncensored --limit 10
python javbus/scripts/javbus_lookup.py random --uncensored --magnet-limit 5
python javbus/scripts/javbus_lookup.py random-actor
```

---

### pica

用于哔咔漫画搜索、章节选择、随机来本，把漫画页下载后打包成带密码 ZIP 发送。搜索阶段只返回纯文本候选，不暴露图片/页面 URL。通用“本子”请求默认交给 `jmcomic`；只有用户明确说 `哔咔` / `pica`，或明确要章节、第一话、第几话、ZIP 打包时，才使用此 skill。

典型触发：`哔咔 搜 xxx` / `pica 随便来个本子` / `下载这个哔咔漫画第一话` / `把这本漫画打包 zip`

首次使用需要配置账号：

```bash
cp pica/config.local.example.json pica/config.local.json
# 编辑填入 username / password / zip_password
```

`pica/config.local.json` 已在 `.gitignore`，不要提交真实凭据。

```bash
python pica/scripts/pica_lookup.py doctor
python pica/scripts/pica_lookup.py search "关键词" --limit 10
python pica/scripts/pica_lookup.py chapters "comicId"
python pica/scripts/pica_lookup.py zip "comicId" 1 --out ./downloads
python pica/scripts/pica_lookup.py random --out ./downloads
```

---

### jmcomic

用于 JMComic / 禁漫天堂搜索、随机推荐和 JM 号下载，把漫画生成带密码 PDF 发送。通用“本子”请求默认走这个 skill；只有明确说 `哔咔` / `pica` / 章节 / ZIP 时才交给 `pica`。

典型触发：`推荐点本子` / `我要看 xxx 的本子` / `jm12345` / `jmid12345` / `禁漫12345` / `禁漫搜 xxx`

首次使用会在 Linux 宿主机自动部署新版 FastAPI `JMComic-Api`，不使用 Docker。需要 `git`、`uv`、Python 3.12+，并确保 `JMAPI_REPO` 指向新版 API 仓库。

```bash
cp jmcomic/config.local.example.json jmcomic/config.local.json
# 编辑 api_repo / project_dir / random_keywords 等配置
```

`jmcomic/config.local.json` 已在 `.gitignore`，不要提交本地配置。

```bash
python jmcomic/scripts/jm_lookup.py doctor
python jmcomic/scripts/jm_lookup.py search "关键词" --limit 10
python jmcomic/scripts/jm_lookup.py get 12345 --out ./downloads
python jmcomic/scripts/jm_lookup.py random --out ./downloads
```

---

### galgame

用于 Galgame / 视觉小说信息查询，整合 VNDB 数据库和 TouchGal 资源站。**bot 根据自然语言意图直接执行，无需用户选命令或选版本**。

典型触发及对应行为：

| 用户说 | bot 执行 |
| --- | --- |
| `随便推荐一个 Gal` / `再来一个` | 随机推荐 + VNDB 信息 + 最佳下载链接 |
| `今天有什么 Gal 发售` / `Gal 日历` | 今日发售 + 角色生日 |
| `最近有什么好 Gal 出` / `近期新作` | 最近 N 天新发售榜 |
| `有没有催泪向推荐` / `推荐几部百合 Gal` | 按标签高分榜 |
| `有没有千恋万花的资源` / `帮我找 CLANNAD 的下载` | 搜索并自动选中文汉化版，直接给下载链接 |
| `CLANNAD 是什么游戏` / `多久打完` / `查 v4` | VNDB 作品详情 |
| `CLANNAD 里有哪些角色` / `女主叫什么` | 作品角色列表 |
| `查古河渚` / `查 c114` | VNDB 角色详情 |
| `Key 出了哪些游戏` | 厂商信息 + 代表作 |

```bash
python galgame/scripts/galgame_box.py random-full              # 随机推荐
python galgame/scripts/galgame_box.py event                    # 今日资讯
python galgame/scripts/galgame_box.py recent                   # 最近新作（默认 30 天）
python galgame/scripts/galgame_box.py recent --days 7          # 近一周
python galgame/scripts/galgame_box.py top                      # 全局高分榜
python galgame/scripts/galgame_box.py top "催泪"               # 按标签筛选
python galgame/scripts/galgame_box.py find-download "千恋万花"  # 找资源（自动选中文版）
python galgame/scripts/galgame_box.py vn "白色相簿2"
python galgame/scripts/galgame_box.py characters-of "CLANNAD"
python galgame/scripts/galgame_box.py character "古河渚"
python galgame/scripts/galgame_box.py producer "Key"
python galgame/scripts/galgame_box.py id v4
python galgame/scripts/galgame_box.py doctor
```

TouchGal 可选参数：`--token <token>` / `--cf <cf_clearance>` / `--nsfw`

---

## 验证

运行各 skill 的单元测试：

```bash
python -m pytest galgame/tests/test_galgame_box.py
python -m pytest javbus/tests/test_javbus_lookup.py
python -m pytest music/tests/test_meting_music.py
python -m pytest pica/tests/test_pica_lookup.py
python -m pytest jmcomic/tests/test_jm_lookup.py
```

一次性跑全部：

```bash
python -m pytest --tb=short
```

---

## 新增 skill

1. 新建目录 `<name>/scripts/` 和 `<name>/tests/`。
2. 写 `<name>/scripts/<name>.py`：标准库 CLI，子命令风格，`--json` 输出原始数据，`--help` 可用。
3. 写 `<name>/SKILL.md`：frontmatter 含 `name` 和 `description`；正文描述触发场景、意图表、调用示例、错误处理。
4. 写 `<name>/tests/test_<name>.py`：mock 网络，覆盖格式化函数和 CLI 入口。
5. 在本文件 `## Skills` 下补一节，格式与上方保持一致。
