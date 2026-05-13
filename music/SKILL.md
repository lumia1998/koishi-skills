---
name: music
description: Use when a bot or assistant needs to satisfy music listening requests, song search, 点歌, 听歌, broad artist requests like “xxx 的歌”, Meting API, NetEase music lookup, selecting a song from search results, downloading a song URL, converting audio with ffmpeg, or sending an mp3/audio file to a user.
---

# Music Bot via Meting API

## Overview

Use this skill to implement a conversational music request flow: infer a song query, search NetEase Music, show up to 10 choices, accept a follow-up selection by number/name/random intent, resolve the selected song through a Meting API backend, download it, convert it to MP3 with ffmpeg, and send the resulting audio/file.

The Meting API endpoint resolves song IDs to playable resources; it is not the search endpoint. Search NetEase first, then call Meting with the selected song ID.

## When to Use

Use this when the user asks a bot to play or find music, for example:

- “我想听 alanwalker 的歌”
- “点一首周杰伦”
- “搜一下 faded，给我听第二首”
- “随便选一首你喜欢的” after a song list was shown
- Any bot feature that needs `api.injahow.cn/meting`, Meting API, NetEase song IDs, ffmpeg conversion, mp3 output, or voice/audio sending

Do not use this for music theory, lyrics explanation, playlist writing, or recommendations that do not need actual audio retrieval.

## Conversation State

Keep a short-lived per-user or per-channel state after search:

```ts
interface MusicSearchState {
  query: string
  results: Array<{ id: number; name: string; artists: string; albumName: string; duration: number }>
  createdAt: number
}
```

Expire the state after 2-5 minutes. Every follow-up selection must refer to the latest unexpired state for that user/channel.

## Request Modes

Classify the user request before deciding whether to play directly or show choices:

| User message | Mode | Bot behavior |
| --- | --- | --- |
| “我要听 Faded Alan Walker” | Specific song + artist | Search, choose high-confidence match, play directly |
| “我要听 The Spectre 2.0” | Specific title with version qualifier | Play only an exact/qualified match; otherwise show choices |
| “我要听 alanwalker 的歌” | Broad artist request | Must show up to 10 choices and wait for user selection before resolving/downloading |
| “随便来首 alanwalker” | Random request | Search and pick one result |

Broad artist/style requests are not specific enough to auto-play. Phrases such as “xxx 的歌”, “xxx 歌手”, “来点 xxx”, or “我想听 xxx 的歌” should run `format-list`, send the list to the user, store the latest result state, and stop until the user replies with a number/name/random intent.

### 2. Search NetEase Music

Use the NetEase search API, not Meting, to get candidate song IDs:

```text
GET http://music.163.com/api/search/get/web?csrf_token=hlpretag=&hlposttag=&s=<encoded query>&type=1&offset=0&total=true&limit=10
```

Map each result to:

```ts
{
  id: song.id,
  name: song.name,
  artists: song.artists.map(a => a.name).join('/'),
  albumName: song.album.name,
  duration: song.duration
}
```

Show at most 10 results:

```text
我搜到了这些：
1. Faded - Alan Walker
2. Alone - Alan Walker
3. The Spectre - Alan Walker
你想听哪首？可以回复序号、歌名，或者说“随便”。
```

### 3. Auto-play exact song requests or resolve selection

Only auto-play when the request contains a concrete song title or title+artist, such as “我要听 Faded Alan Walker” or “播放 晴天”. Do not auto-play broad artist/style requests.

If the request contains version/variant qualifiers such as `2.0`, `remix`, `live`, `DJ`, `伴奏`, or `cover`, do not drop those words during matching. The original song is not a high-confidence match for a qualified request unless the title itself includes the requested qualifier.

For broad requests such as “我要听 alanwalker 的歌”, do this instead:

1. Run `search "alanwalker" --limit 10` to get JSON candidates with numeric song IDs for internal state.
2. Run `format-list "alanwalker" --limit 10` and send the returned plain text list to the user.
3. Save the `search` JSON as the latest per-user/per-channel state so numbers and titles map back to song IDs.
4. Wait for the user to reply with a number, title, or random intent.
5. Only after the selection, call `download <songId> --out <file.mp3>` or resolve the chosen `id` and convert it.

If the initial user message is broad and does not include “随便/你选/随机/都行”, asking the user to choose is the correct behavior even if the search result has a clear first item.

If the initial user message contains a specific song title, search first and then decide whether to ask for confirmation:

| Search result situation | Behavior |
| --- | --- |
| One high-confidence match: exact title match, or song title plus artist match, or one clear top title match that preserves every requested version/variant qualifier | Play it directly without asking another question |
| Multiple likely versions: original/live/remix/DJ/伴奏/cover, or several same-title songs | Show up to 10 candidates and ask the user to choose |
| Query is only an artist or broad style, such as “alanwalker 的歌” | Show candidates and ask the user to choose, unless the user asked for random |
| User says “随便/你选/随机” in the initial request | Search and pick one candidate, preferably not always index 0 |

When auto-playing, still send a short confirmation before audio processing:

```text
我找到最匹配的是：Faded - Alan Walker，开始处理音频。
```

For follow-up selection after a list, accept these forms:

| Input | Behavior |
| --- | --- |
| `1`, `第一个`, `第二首` | Select by ordinal |
| exact or partial song title | Select the best matching result by title/artist text |
| `随便`, `你选`, `随机`, `都行` | Pick one result, preferably not always index 0 |

If ambiguous, ask one clarification instead of guessing. If no active search state exists, ask the user what they want to hear.

### 4. Get playable URL via Meting

For the selected `id`, request:

```text
GET https://api.injahow.cn/meting/?type=url&id=<songId>
```

The response may be either a plain URL or JSON containing `url`. Accept only `http:` or `https:` URLs.

Other useful Meting calls:

```text
GET https://api.injahow.cn/meting/?type=song&id=<songId>
GET https://api.injahow.cn/meting/?type=pic&id=<songId>
GET https://api.injahow.cn/meting/?type=lrc&id=<songId>
```

### 5. Download and convert to MP3

Download the playable URL to a temp file, then convert with ffmpeg:

```bash
ffmpeg -y -hide_banner -loglevel error -i "input_file" -vn -acodec libmp3lame -b:a 192k "output.mp3"
```

The reusable helper first checks `ffmpeg` in `PATH`. If it is missing, it downloads a platform-specific ffmpeg build into `music/.cache/ffmpeg/` and reuses that cached binary for later conversions.

Use timeouts and file size limits appropriate for the bot platform. Always clean up temporary files after sending or failure.

### 6. Send result

Send a short confirmation and attach or upload the converted MP3:

```text
给你放：Faded - Alan Walker
```

If the bot platform supports voice messages only for specific codecs, convert again as required by that adapter; otherwise send the MP3 as an audio/file attachment.

## Reusable Helper Script

If you can run Python, use `scripts/meting_music.py` for deterministic operations instead of rewriting the flow:

```bash
python scripts/meting_music.py doctor
python scripts/meting_music.py search "alanwalker" --limit 10
python scripts/meting_music.py format-list "alanwalker" --limit 10
python scripts/meting_music.py choose-best "Faded Alan Walker" --limit 10
python scripts/meting_music.py resolve 36990266
python scripts/meting_music.py download 36990266 --out song.mp3
python scripts/meting_music.py play "Faded Alan Walker" --out song.mp3
```

`resolve` only returns the playable direct URL and the Meting API that worked. Use `download` or `play` when the bot needs an actual MP3 file.

Use `search` together with `format-list` for broad artist/style requests: keep the JSON from `search` internally for song IDs, send only the `format-list` text to the user, then stop and wait for selection. Do not immediately call `play` for “xxx 的歌” unless the user also says “随便/随机/你选”. It returns plain chat text, not JSON:

```text
我搜到了这些和「alanwalker」相关的歌曲：
1. Faded - Alan Walker (3:32)
2. Alone - Alan Walker (2:41)
你想听哪首？可以回复序号、歌名，或者说“随便”。
```

Use `play` only when the user gave a specific enough song request, or explicitly asked for random selection. If the result is ambiguous, it returns JSON with `ambiguous: true` and a `prompt` string; send only the prompt text to the user. If it is not ambiguous, it writes the MP3 file and returns the file path.

For ChatLuna/open-terminal style backends, set the command timeout to at least 120 seconds for `download` or `play`. The first run may need extra time to download ffmpeg, and normal song download + conversion can exceed 30 seconds. If the backend cannot change timeout, tell the user you are processing audio before running the command and tolerate a delayed file publish step instead of treating a 30-second timeout as failure when JSON output and the MP3 path are present.

`resolve`, `download`, and `play` use multiple preset Meting APIs as fallback. To override or add priority APIs:

```bash
python scripts/meting_music.py resolve 36990266 --api https://api.injahow.cn/meting/ --api https://api.qijieya.cn/meting/
```

`doctor` checks Python, ffmpeg auto-setup, NetEase search, and Meting API availability before deploying the bot.

## Error Handling

| Failure | Bot response |
| --- | --- |
| Search returns empty | “没搜到相关歌曲，换个关键词试试？” |
| Search/API timeout | “音乐服务暂时没响应，稍后再试。” |
| Selection invalid | “这个序号/歌名不在刚才的列表里，请重新选。” |
| Meting URL missing | “这首歌暂时拿不到播放链接，换一首？” |
| All Meting fallback APIs fail | “音乐直链服务暂时不可用，稍后再试。” |
| ffmpeg auto-setup failed | “音频转换环境自动配置失败，需要手动安装 ffmpeg。” |
| Download/ffmpeg failed | “音频处理失败，换一首或稍后再试。” |
| Song too long or file too large | “这首太长了，可能发不出去，换一首短一点的？” |

## Common Mistakes

- Do not call `?type=url&id=<keyword>` with a search keyword. Meting URL lookup requires a numeric song ID.
- Do not show more than 10 results in chat; long lists make follow-up selection unreliable.
- Do not lose the search state before the user chooses; selection by number needs the previous result list.
- Do not assume the user will only reply with a number; support song name and random choice.
- Do not send arbitrary remote URLs as final output when the requirement is an MP3/audio file; download and convert first.
- Do not drop version or variant qualifiers such as `2.0`, `remix`, `live`, `DJ`, `伴奏`, or `cover`; if the matched title lacks the qualifier, show choices instead of auto-playing.
- Do not treat a 30-second open-terminal timeout as failure if the command output contains valid JSON with a generated MP3 path.
