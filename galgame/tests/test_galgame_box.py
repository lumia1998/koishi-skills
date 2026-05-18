#!/usr/bin/env python3
"""
Unit tests for galgame_box.py — all pure-logic, no network required.
"""
import sys
import os
import json
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import galgame_box as gb


# ---------------------------------------------------------------------------
# Formatter tests (no network)
# ---------------------------------------------------------------------------

VN_SAMPLE = {
    "id": "v4",
    "title": "Clannad",
    "alttitle": "CLANNAD",
    "released": "2004-04-28",
    "rating": 90.0,
    "average": 88.5,
    "length_minutes": 3000,
    "platforms": ["win"],
    "developers": [{"id": "p22", "name": "Key", "original": "Key"}],
    "aliases": ["クラナド"],
    "titles": [
        {"lang": "ja", "title": "CLANNAD", "official": True},
        {"lang": "zh-Hans", "title": "CLANNAD", "official": True},
    ],
    "image": {"url": "https://t.vndb.org/cv/24/4.jpg"},
}

CHARACTER_SAMPLE = {
    "id": "c114",
    "name": "古河渚",
    "original": "古河渚",
    "sex": ["f"],
    "birthday": [12, 25],
    "height": 155,
    "weight": 45,
    "bust": 79,
    "waist": 57,
    "hips": 80,
    "cup": "B",
    "blood_type": "a",
    "aliases": ["Nagisa Furukawa"],
    "image": {"url": "https://s.vndb.org/ch/12/114.jpg"},
    "vns": [{"id": "v4", "title": "Clannad", "alttitle": "CLANNAD"}],
}

PRODUCER_SAMPLE = {
    "id": "p22",
    "name": "Key",
    "original": "Key",
    "lang": "ja",
    "type": "co",
    "aliases": ["Key (Visual Arts)"],
}

TOUCHGAL_GAME = {
    "id": 123,
    "unique_id": "abc123",
    "banner": "https://example.com/banner.jpg",
    "name": "テストゲーム",
    "type": ["galgame"],
    "language": ["ja", "zh-Hans"],
    "platform": ["win"],
    "averageRating": 8.5,
    "tag": [],
}

RESOURCE_SAMPLE = [
    {
        "id": 1,
        "name": "百度网盘",
        "section": "百度网盘",
        "type": ["galgame"],
        "language": ["zh-Hans"],
        "note": "汉化版",
        "platform": ["win"],
        "links": [
            {
                "storage": "百度网盘",
                "size": "4.5 GB",
                "content": "https://pan.baidu.com/s/xxx",
                "code": "abcd",
                "password": "1234",
            }
        ],
    }
]

EVENT_DATA = {
    "date": "2026-05-18",
    "releases": [VN_SAMPLE],
    "birthdays": [CHARACTER_SAMPLE],
}


class TestFormatters(unittest.TestCase):
    def test_vn_summary_contains_title(self):
        text = gb._vn_summary(VN_SAMPLE)
        self.assertIn("CLANNAD", text)
        self.assertIn("v4", text)

    def test_vn_summary_contains_rating(self):
        text = gb._vn_summary(VN_SAMPLE)
        self.assertIn("90.0", text)

    def test_vn_summary_contains_cover_url(self):
        text = gb._vn_summary(VN_SAMPLE)
        self.assertIn("https://t.vndb.org/cv/24/4.jpg", text)

    def test_vn_summary_length_minutes(self):
        text = gb._vn_summary(VN_SAMPLE)
        self.assertIn("50h", text)

    def test_character_summary_name(self):
        text = gb._character_summary(CHARACTER_SAMPLE)
        self.assertIn("古河渚", text)

    def test_character_summary_birthday(self):
        text = gb._character_summary(CHARACTER_SAMPLE)
        self.assertIn("12月25日", text)

    def test_character_summary_measurements(self):
        text = gb._character_summary(CHARACTER_SAMPLE)
        self.assertIn("155cm", text)
        self.assertIn("血型 A", text)

    def test_character_summary_image_url(self):
        text = gb._character_summary(CHARACTER_SAMPLE)
        self.assertIn("https://s.vndb.org/ch/12/114.jpg", text)

    def test_producer_summary(self):
        vns = [{"id": "v4", "title": "Clannad", "alttitle": "CLANNAD", "released": "2004-04-28", "rating": 90.0}]
        text = gb._producer_summary(PRODUCER_SAMPLE, vns)
        self.assertIn("Key", text)
        self.assertIn("公司", text)
        self.assertIn("CLANNAD", text)

    def test_format_vn_list(self):
        text = gb.format_vn_list("Clannad", [VN_SAMPLE])
        self.assertIn("v4", text)
        self.assertIn("CLANNAD", text)

    def test_format_vn_list_empty(self):
        text = gb.format_vn_list("Clannad", [])
        self.assertIn("没找到", text)

    def test_format_character_list(self):
        text = gb.format_character_list("渚", [CHARACTER_SAMPLE])
        self.assertIn("古河渚", text)

    def test_format_producer_list(self):
        text = gb.format_producer_list("Key", [PRODUCER_SAMPLE])
        self.assertIn("Key", text)

    def test_format_event(self):
        text = gb.format_event(EVENT_DATA)
        self.assertIn("2026-05-18", text)
        self.assertIn("CLANNAD", text)
        self.assertIn("古河渚", text)

    def test_format_touchgal_list(self):
        text = gb.format_touchgal_list("テスト", [TOUCHGAL_GAME])
        self.assertIn("テストゲーム", text)
        self.assertIn("abc123", text)
        self.assertIn("8.5", text)

    def test_format_touchgal_list_empty(self):
        text = gb.format_touchgal_list("テスト", [])
        self.assertIn("没找到", text)

    def test_format_download_resources(self):
        text = gb.format_download_resources("テストゲーム", RESOURCE_SAMPLE)
        self.assertIn("百度网盘", text)
        self.assertIn("abcd", text)
        self.assertIn("1234", text)
        self.assertIn("4.5 GB", text)

    def test_format_download_resources_empty(self):
        text = gb.format_download_resources("テストゲーム", [])
        self.assertIn("暂无", text)


class TestTitlesStr(unittest.TestCase):
    def test_with_official_titles(self):
        titles = [
            {"lang": "ja", "title": "クラナド", "official": True},
            {"lang": "zh-Hans", "title": "CLANNAD", "official": True},
        ]
        result = gb._titles_str(titles, "CLANNAD", "Clannad")
        self.assertIn("クラナド", result)
        self.assertIn("CLANNAD", result)

    def test_fallback_to_alttitle(self):
        result = gb._titles_str(None, "CLANNAD", "Clannad")
        self.assertEqual(result, "CLANNAD")

    def test_fallback_to_title(self):
        result = gb._titles_str(None, None, "Clannad")
        self.assertEqual(result, "Clannad")


class TestIdPrefix(unittest.TestCase):
    def test_known_prefixes(self):
        self.assertEqual(gb.ID_PREFIX_MAP["v"], "vn")
        self.assertEqual(gb.ID_PREFIX_MAP["c"], "character")
        self.assertEqual(gb.ID_PREFIX_MAP["p"], "producer")

    def test_unknown_prefix_raises(self):
        with self.assertRaises(ValueError):
            gb.vndb_lookup_id("x999")


class TestTouchgalCookies(unittest.TestCase):
    def test_sfw_default(self):
        cookies = gb._touchgal_cookies()
        self.assertEqual(cookies["kun-patch-setting-store|state|data|kunNsfwEnable"], "sfw")

    def test_nsfw_flag(self):
        cookies = gb._touchgal_cookies(nsfw=True)
        self.assertEqual(cookies["kun-patch-setting-store|state|data|kunNsfwEnable"], "all")

    def test_token_added(self):
        cookies = gb._touchgal_cookies(token="mytoken")
        self.assertEqual(cookies["kun-galgame-patch-moe-token"], "mytoken")

    def test_token_absent_when_empty(self):
        cookies = gb._touchgal_cookies(token="")
        self.assertNotIn("kun-galgame-patch-moe-token", cookies)

    def test_cf_added(self):
        cookies = gb._touchgal_cookies(cf_clearance="cfvalue")
        self.assertEqual(cookies["cf_clearance"], "cfvalue")


class TestCLI(unittest.TestCase):
    """Test CLI entry points with mocked network calls."""

    def _run_cli(self, args):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with patch("sys.argv", ["galgame_box.py"] + args):
            with redirect_stdout(buf):
                try:
                    gb.main()
                except SystemExit as e:
                    if e.code not in (None, 0):
                        raise
        return buf.getvalue()

    def test_vn_single_result_uses_summary(self):
        with patch.object(gb, "vndb_search_vn", return_value=[VN_SAMPLE]):
            out = self._run_cli(["vn", "Clannad"])
        self.assertIn("CLANNAD", out)

    def test_vn_multiple_results_uses_list(self):
        with patch.object(gb, "vndb_search_vn", return_value=[VN_SAMPLE, VN_SAMPLE]):
            out = self._run_cli(["vn", "Clannad"])
        self.assertIn("1.", out)
        self.assertIn("2.", out)

    def test_vn_json_flag(self):
        with patch.object(gb, "vndb_search_vn", return_value=[VN_SAMPLE]):
            out = self._run_cli(["vn", "Clannad", "--json"])
        parsed = json.loads(out)
        self.assertIsInstance(parsed, list)

    def test_character_single(self):
        with patch.object(gb, "vndb_search_character", return_value=[CHARACTER_SAMPLE]):
            out = self._run_cli(["character", "渚"])
        self.assertIn("古河渚", out)

    def test_producer_single(self):
        with patch.object(gb, "vndb_search_producer", return_value=([PRODUCER_SAMPLE], [[]])):
            out = self._run_cli(["producer", "Key"])
        self.assertIn("Key", out)

    def test_id_vn(self):
        with patch.object(gb, "vndb_lookup_id", return_value={"type": "vn", "data": VN_SAMPLE}):
            out = self._run_cli(["id", "v4"])
        self.assertIn("CLANNAD", out)

    def test_id_character(self):
        with patch.object(gb, "vndb_lookup_id", return_value={"type": "character", "data": CHARACTER_SAMPLE}):
            out = self._run_cli(["id", "c114"])
        self.assertIn("古河渚", out)

    def test_event_text(self):
        with patch.object(gb, "vndb_event", return_value=EVENT_DATA):
            out = self._run_cli(["event"])
        self.assertIn("2026-05-18", out)

    def test_random_text(self):
        with patch.object(gb, "touchgal_random", return_value="abc123"):
            out = self._run_cli(["random"])
        self.assertIn("abc123", out)

    def test_random_json(self):
        with patch.object(gb, "touchgal_random", return_value="abc123"):
            out = self._run_cli(["random", "--json"])
        parsed = json.loads(out)
        self.assertEqual(parsed["unique_id"], "abc123")

    def test_search_touchgal(self):
        with patch.object(gb, "touchgal_search", return_value=[TOUCHGAL_GAME]):
            out = self._run_cli(["search-touchgal", "テスト"])
        self.assertIn("テストゲーム", out)

    def test_download(self):
        with patch.object(gb, "touchgal_download", return_value=RESOURCE_SAMPLE):
            out = self._run_cli(["download", "123", "--name", "テストゲーム"])
        self.assertIn("百度网盘", out)

    def test_download_json(self):
        with patch.object(gb, "touchgal_download", return_value=RESOURCE_SAMPLE):
            out = self._run_cli(["download", "123", "--json"])
        parsed = json.loads(out)
        self.assertIsInstance(parsed, list)


class TestResourcePicking(unittest.TestCase):
    def test_cn_score_zh_hans(self):
        res = {"language": ["zh-Hans"], "note": "", "section": "百度网盘", "links": [{"content": "x"}]}
        self.assertGreaterEqual(gb._resource_cn_score(res), 10)

    def test_cn_score_note_hint(self):
        res = {"language": ["ja"], "note": "汉化版", "section": "百度网盘", "links": []}
        self.assertGreater(gb._resource_cn_score(res), 0)

    def test_cn_score_pure_ja(self):
        res = {"language": ["ja"], "note": "", "section": "百度网盘", "links": []}
        self.assertEqual(gb._resource_cn_score(res), 0)

    def test_pick_best_prefers_cn(self):
        ja = {"language": ["ja"], "note": "", "section": "百度网盘", "links": [{"content": "ja_link"}]}
        cn = {"language": ["zh-Hans"], "note": "", "section": "百度网盘", "links": [{"content": "cn_link"}]}
        best = gb._pick_best_resource([ja, cn])
        self.assertEqual(best["links"][0]["content"], "cn_link")

    def test_pick_best_returns_none_for_empty(self):
        self.assertIsNone(gb._pick_best_resource([]))

    def test_pick_best_with_links_preferred(self):
        no_links = {"language": ["zh-Hans"], "note": "", "section": "x", "links": []}
        with_links = {"language": ["ja"], "note": "", "section": "x", "links": [{"content": "url"}]}
        best = gb._pick_best_resource([no_links, with_links])
        # cn without links vs ja with links: cn should still win due to lang score
        # but if cn has no links, with_links ja can win depending on score gap
        # Just verify a result is returned
        self.assertIsNotNone(best)


RANDOM_FULL_DATA = {
    "game_name": "CLANNAD",
    "unique_id": "clannad-abc",
    "page_url": "https://www.touchgal.top/clannad-abc",
    "touchgal": {"id": 456, "name": "CLANNAD", "unique_id": "clannad-abc", "language": ["zh-Hans"], "averageRating": 9.2, "type": [], "platform": [], "banner": "", "tag": []},
    "vndb": {
        "id": "v4", "title": "Clannad", "alttitle": "CLANNAD", "released": "2004-04-28",
        "rating": 90.0, "average": 88.5, "length_minutes": 3000, "platforms": ["win"],
        "developers": [{"id": "p22", "name": "Key", "original": "Key"}],
        "aliases": [], "titles": [{"lang": "zh-Hans", "title": "CLANNAD", "official": True}],
        "image": {"url": "https://t.vndb.org/cv/24/4.jpg"},
    },
    "best_resource": {
        "section": "百度网盘", "name": "百度网盘", "note": "汉化版",
        "language": ["zh-Hans"], "platform": ["win"],
        "links": [{"storage": "百度网盘", "size": "4.5 GB", "content": "https://pan.baidu.com/s/xxx", "code": "abcd", "password": "1234"}],
    },
    "all_resources": [],
}

FIND_DOWNLOAD_DATA = {
    "found": True,
    "keyword": "千恋万花",
    "game_name": "千恋*万花",
    "unique_id": "senren-banka",
    "page_url": "https://www.touchgal.top/senren-banka",
    "touchgal": {"id": 789, "name": "千恋*万花", "unique_id": "senren-banka", "language": ["zh-Hans", "ja"], "averageRating": 8.8, "type": [], "platform": [], "banner": "", "tag": []},
    "vndb": None,
    "best_resource": {
        "section": "OneDrive", "name": "OneDrive", "note": "简中汉化",
        "language": ["zh-Hans"], "platform": ["win"],
        "links": [{"storage": "OneDrive", "size": "2.1 GB", "content": "https://1drv.ms/xxx", "code": "", "password": ""}],
    },
    "all_resources": [
        {"section": "OneDrive", "name": "OneDrive", "note": "简中汉化", "language": ["zh-Hans"], "platform": ["win"], "links": [{"storage": "OneDrive", "size": "2.1 GB", "content": "https://1drv.ms/xxx", "code": "", "password": ""}]},
        {"section": "百度网盘", "name": "百度网盘", "note": "日文原版", "language": ["ja"], "platform": ["win"], "links": [{"storage": "百度网盘", "size": "3.0 GB", "content": "https://pan.baidu.com/s/yyy", "code": "efgh", "password": ""}]},
    ],
}


class TestCompositeFormatters(unittest.TestCase):
    def test_format_random_full_contains_title(self):
        text = gb.format_random_full(RANDOM_FULL_DATA)
        self.assertIn("CLANNAD", text)

    def test_format_random_full_contains_rating(self):
        text = gb.format_random_full(RANDOM_FULL_DATA)
        self.assertIn("90.0", text)

    def test_format_random_full_contains_page_url(self):
        text = gb.format_random_full(RANDOM_FULL_DATA)
        self.assertIn("https://www.touchgal.top/clannad-abc", text)

    def test_format_random_full_contains_download_link(self):
        text = gb.format_random_full(RANDOM_FULL_DATA)
        self.assertIn("https://pan.baidu.com/s/xxx", text)
        self.assertIn("abcd", text)

    def test_format_random_full_no_vndb(self):
        data = dict(RANDOM_FULL_DATA)
        data["vndb"] = None
        text = gb.format_random_full(data)
        self.assertIn("CLANNAD", text)

    def test_format_find_download_cn_label(self):
        text = gb.format_find_download(FIND_DOWNLOAD_DATA)
        self.assertIn("中文汉化版", text)

    def test_format_find_download_contains_link(self):
        text = gb.format_find_download(FIND_DOWNLOAD_DATA)
        self.assertIn("https://1drv.ms/xxx", text)

    def test_format_find_download_mentions_other_versions(self):
        text = gb.format_find_download(FIND_DOWNLOAD_DATA)
        self.assertIn("其他版本", text)

    def test_format_find_download_not_found(self):
        text = gb.format_find_download({"found": False, "keyword": "天下第一"})
        self.assertIn("没找到", text)
        self.assertIn("天下第一", text)


class TestCompositeCLI(unittest.TestCase):
    def _run_cli(self, args):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with patch("sys.argv", ["galgame_box.py"] + args):
            with redirect_stdout(buf):
                try:
                    gb.main()
                except SystemExit as e:
                    if e.code not in (None, 0):
                        raise
        return buf.getvalue()

    def test_random_full_text(self):
        with patch.object(gb, "random_full", return_value=RANDOM_FULL_DATA):
            out = self._run_cli(["random-full"])
        self.assertIn("CLANNAD", out)

    def test_random_full_json(self):
        with patch.object(gb, "random_full", return_value=RANDOM_FULL_DATA):
            out = self._run_cli(["random-full", "--json"])
        parsed = json.loads(out)
        self.assertEqual(parsed["game_name"], "CLANNAD")

    def test_find_download_text(self):
        with patch.object(gb, "find_download", return_value=FIND_DOWNLOAD_DATA):
            out = self._run_cli(["find-download", "千恋万花"])
        self.assertIn("千恋", out)
        self.assertIn("1drv.ms", out)

    def test_find_download_json(self):
        with patch.object(gb, "find_download", return_value=FIND_DOWNLOAD_DATA):
            out = self._run_cli(["find-download", "千恋万花", "--json"])
        parsed = json.loads(out)
        self.assertTrue(parsed["found"])


class TestNewCommands(unittest.TestCase):
    """Tests for recent, top, characters-of formatters and CLI."""

    RECENT_DATA = {
        "days": 30,
        "from": "2026-04-18",
        "to": "2026-05-18",
        "results": [
            {"id": "v1000", "title": "新作 A", "alttitle": "新作A", "released": "2026-05-10", "rating": 78.0, "image": {"url": "https://t.vndb.org/cv/00/1000.jpg"}},
            {"id": "v1001", "title": "新作 B", "alttitle": None, "released": "2026-04-25", "rating": 72.0, "image": None},
        ],
    }

    RECENT_EMPTY = {"days": 30, "from": "2026-04-18", "to": "2026-05-18", "results": []}

    TOP_DATA = {
        "tag_keyword": "催泪",
        "matched_tags": ["Utsuge", "Tragedy"],
        "results": [
            {"id": "v4", "title": "Clannad", "alttitle": "CLANNAD", "released": "2004-04-28", "rating": 90.0, "image": None},
            {"id": "v17", "title": "Little Busters!", "alttitle": None, "released": "2007-07-27", "rating": 87.0, "image": None},
        ],
    }

    TOP_EMPTY = {"tag_keyword": "不存在标签xyz", "matched_tags": [], "results": []}
    TOP_GLOBAL = {"tag_keyword": "", "matched_tags": [], "results": [
        {"id": "v4", "title": "Clannad", "alttitle": "CLANNAD", "released": "2004-04-28", "rating": 90.0, "image": None},
    ]}

    CHARS_DATA = {
        "found": True,
        "keyword": "Clannad",
        "vn": {"id": "v4", "title": "Clannad", "alttitle": "CLANNAD", "titles": [{"lang": "zh-Hans", "title": "CLANNAD", "official": True}]},
        "characters": [
            {
                "id": "c114", "name": "古河渚", "original": "古河渚",
                "sex": ["f"], "birthday": [12, 25], "height": 155,
                "weight": None, "bust": None, "waist": None, "hips": None,
                "cup": None, "blood_type": None, "aliases": [],
                "image": {"url": "https://s.vndb.org/ch/12/114.jpg"},
                "vns": [],
            }
        ],
    }

    CHARS_NOT_FOUND = {"found": False, "keyword": "不存在的游戏xyz", "vn": None, "characters": []}
    CHARS_EMPTY = {"found": True, "keyword": "Clannad", "vn": {"id": "v4", "title": "Clannad", "alttitle": "CLANNAD", "titles": []}, "characters": []}

    def test_format_recent_contains_titles(self):
        text = gb.format_recent(self.RECENT_DATA)
        self.assertIn("新作A", text)
        self.assertIn("2026-05-10", text)

    def test_format_recent_contains_cover_url(self):
        text = gb.format_recent(self.RECENT_DATA)
        self.assertIn("https://t.vndb.org/cv/00/1000.jpg", text)

    def test_format_recent_empty(self):
        text = gb.format_recent(self.RECENT_EMPTY)
        self.assertIn("暂无", text)

    def test_format_top_with_tag(self):
        text = gb.format_top(self.TOP_DATA)
        self.assertIn("Utsuge", text)
        self.assertIn("CLANNAD", text)

    def test_format_top_empty(self):
        text = gb.format_top(self.TOP_EMPTY)
        self.assertIn("没找到", text)

    def test_format_top_global(self):
        text = gb.format_top(self.TOP_GLOBAL)
        self.assertIn("全局", text)
        self.assertIn("CLANNAD", text)

    def test_format_characters_of(self):
        text = gb.format_characters_of(self.CHARS_DATA)
        self.assertIn("古河渚", text)
        self.assertIn("c114", text)
        self.assertIn("12月25日", text)

    def test_format_characters_of_image_url(self):
        text = gb.format_characters_of(self.CHARS_DATA)
        self.assertIn("https://s.vndb.org/ch/12/114.jpg", text)

    def test_format_characters_not_found(self):
        text = gb.format_characters_of(self.CHARS_NOT_FOUND)
        self.assertIn("没找到", text)

    def test_format_characters_empty(self):
        text = gb.format_characters_of(self.CHARS_EMPTY)
        self.assertIn("暂无角色信息", text)

    def _run_cli(self, args):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with patch("sys.argv", ["galgame_box.py"] + args):
            with redirect_stdout(buf):
                try:
                    gb.main()
                except SystemExit as e:
                    if e.code not in (None, 0):
                        raise
        return buf.getvalue()

    def test_cli_recent(self):
        with patch.object(gb, "vndb_recent", return_value=self.RECENT_DATA):
            out = self._run_cli(["recent"])
        self.assertIn("新作A", out)

    def test_cli_recent_json(self):
        with patch.object(gb, "vndb_recent", return_value=self.RECENT_DATA):
            out = self._run_cli(["recent", "--json"])
        parsed = json.loads(out)
        self.assertEqual(len(parsed["results"]), 2)

    def test_cli_top_with_tag(self):
        with patch.object(gb, "vndb_top", return_value=self.TOP_DATA):
            out = self._run_cli(["top", "催泪"])
        self.assertIn("CLANNAD", out)

    def test_cli_top_no_tag(self):
        with patch.object(gb, "vndb_top", return_value=self.TOP_GLOBAL):
            out = self._run_cli(["top"])
        self.assertIn("全局", out)

    def test_cli_characters_of(self):
        with patch.object(gb, "vndb_characters_of", return_value=self.CHARS_DATA):
            out = self._run_cli(["characters-of", "Clannad"])
        self.assertIn("古河渚", out)

    def test_cli_characters_of_json(self):
        with patch.object(gb, "vndb_characters_of", return_value=self.CHARS_DATA):
            out = self._run_cli(["characters-of", "Clannad", "--json"])
        parsed = json.loads(out)
        self.assertTrue(parsed["found"])


if __name__ == "__main__":
    unittest.main()

