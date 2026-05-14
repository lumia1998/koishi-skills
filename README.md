# koishi-skills

这个仓库放的是给 Koishi-ChatLuna / Open Terminal 后端使用的 bot skills。每个目录都是一个独立 skill，通常包含：

- `SKILL.md`：给 bot/assistant 读取的使用说明和触发规则。
- `scripts/`：可复用的确定性脚本。
- `tests/`：脚本和文档规则的回归测试。

## Skills

### music

用于点歌、搜歌、下载并发送音频文件。

典型触发：

- `我想听 alanwalker 的歌`
- `点一首周杰伦`
- `我要听 The Spectre 2.0`
- 用户看完候选列表后回复序号、歌名或“随便”

主要流程：先搜索网易云候选，给用户纯文本列表；用户选择后解析播放直链，下载音频，用 ffmpeg 转成 MP3，再发送文件。宽泛请求不会默认播放第一首，会先让用户选。

常用脚本：

```bash
python music/scripts/meting_music.py search "alanwalker" --limit 10
python music/scripts/meting_music.py format-list "alanwalker" --limit 10
python music/scripts/meting_music.py download <songId> --out ./downloads/song.mp3
python music/scripts/meting_music.py doctor
```

### javbus

用于 JavBus 风格的影片元数据查询和随机推荐。只返回文本、磁链、封面 URL、预览图 URL，不下载或直接发送图片。

典型触发：

- `查 ABP-123`
- `搜女优 xxx`
- `搜影片关键词 xxx`
- `给我来个无码影片`
- `随机推荐个女优`

常用脚本：

```bash
python javbus/scripts/javbus_lookup.py detail "ABP-123"
python javbus/scripts/javbus_lookup.py search "keyword" --limit 10
python javbus/scripts/javbus_lookup.py latest --uncensored --limit 10
python javbus/scripts/javbus_lookup.py random --uncensored --magnet-limit 5
python javbus/scripts/javbus_lookup.py random-actor
```

### pica

用于 Pica / 哔咔漫画搜索、章节选择、随机来本，并把漫画页下载后打包成带密码 ZIP 文件发送。搜索阶段只给纯文本候选，不返回图片 URL、页面 URL 或封面 URL。

典型触发：

- `搜xxx漫画`
- `搜xxxx本子`
- `我要看本子`
- `给我整个本子看`
- `随便来个本子`
- `pica 搜一下 xxx`
- `哔咔 搜 xxx`

首次使用前复制配置模板：

```bash
cp pica/config.local.example.json pica/config.local.json
```

然后编辑 `pica/config.local.json`：

```json
{
  "username": "你的哔咔账号",
  "password": "你的哔咔密码",
  "zip_password": "ZIP解压密码",
  "random_keywords": ["全彩", "短篇", "同人", "校园", "恋爱"],
  "random_chapter": "first"
}
```

`pica/config.local.json` 已被 `.gitignore` 忽略，不要提交真实账号和密码。发送 ZIP 时需要把 `zip_password` 对应的解压密码告诉用户。

常用脚本：

```bash
python pica/scripts/pica_lookup.py doctor
python pica/scripts/pica_lookup.py search "关键词" --limit 10
python pica/scripts/pica_lookup.py chapters "comicId"
python pica/scripts/pica_lookup.py zip "comicId" 1 --out ./downloads
python pica/scripts/pica_lookup.py random --out ./downloads
```

## 验证

运行单个 skill 的测试：

```bash
python -m pytest pica/tests/test_pica_lookup.py
python -m pytest javbus/tests/test_javbus_lookup.py
python -m pytest music/tests/test_meting_music.py
```

Pica 还可以运行：

```bash
python -m py_compile pica/scripts/pica_lookup.py
python pica/scripts/pica_lookup.py doctor
```
