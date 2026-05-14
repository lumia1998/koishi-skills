import argparse
import hashlib
import hmac
import importlib.util
import json
import random
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "pica_lookup.py"
sys.path.insert(0, str(SCRIPT_PATH.parent))


def load_module():
    spec = importlib.util.spec_from_file_location("pica_lookup", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config_args(**overrides):
    values = {
        "config": None,
        "username": None,
        "password": None,
        "zip_password": None,
        "api_host": None,
        "api_key": None,
        "hmac_key": None,
        "timeout": None,
        "retries": None,
        "concurrency": None,
        "random_keywords": None,
        "random_chapter": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_signature_matches_original_plugin_algorithm():
    pica = load_module()
    config = pica.PicaConfig(
        username="user",
        password="secret",
        zip_password="zip-secret",
        api_host="https://example.test",
        api_key="api-key",
        hmac_key="hmac-key",
    )
    client = pica.PicaClient(config)

    signature = client.create_signature("comics/search?page=1&q=test", "nonce", "1234567890", "GET")

    raw = "comics/search?page=1&q=test1234567890nonceGETapi-key".lower()
    expected = hmac.new(b"hmac-key", raw.encode(), hashlib.sha256).hexdigest()
    assert signature == expected


def test_build_headers_contains_required_fields_without_leaking_password():
    pica = load_module()
    config = pica.PicaConfig(
        username="user",
        password="secret-password",
        zip_password="zip-secret",
        api_host="https://example.test",
        api_key="api-key",
        hmac_key="hmac-key",
    )
    client = pica.PicaClient(config)

    headers = client.build_headers("GET", "comics/abc", "token-value")

    assert headers["api-key"] == "api-key"
    assert headers["authorization"] == "token-value"
    assert headers["accept"] == "application/vnd.picacomic.com.v1+json"
    assert headers["app-platform"] == "android"
    assert "secret-password" not in json.dumps(headers, ensure_ascii=False)


def test_format_search_results_is_plain_text_without_urls_or_secrets():
    pica = load_module()
    comics = [
        {
            "_id": "comic-1",
            "title": "测试本子",
            "author": "作者A",
            "thumb": {"fileServer": "https://img.example", "path": "cover.jpg"},
        }
    ]

    text = pica.format_search_results("测试", comics, total=1)

    assert "1. 测试本子" in text
    assert "作者：作者A" in text
    assert "ID：comic-1" in text
    assert "https://" not in text
    assert "password" not in text.lower()


def test_load_config_reads_local_config_file(tmp_path, monkeypatch):
    pica = load_module()
    local_config = tmp_path / "config.local.json"
    local_config.write_text(json.dumps({
        "username": "local-user",
        "password": "local-password",
        "zip_password": "local-zip-password",
        "random_keywords": ["百合", "纯爱"],
        "random_chapter": "random",
        "timeout": 33,
        "retries": 2,
        "concurrency": 1,
    }, ensure_ascii=False), encoding="utf-8")

    config = pica.load_config(config_args(config=local_config))

    assert config.username == "local-user"
    assert config.password == "local-password"
    assert config.zip_password == "local-zip-password"
    assert config.random_keywords == ("百合", "纯爱")
    assert config.random_chapter == "random"
    assert config.timeout == 33
    assert config.retries == 2
    assert config.concurrency == 1


    pica = load_module()
    monkeypatch.setenv("PICA_USERNAME", "env-user")
    monkeypatch.setenv("PICA_PASSWORD", "env-password")
    monkeypatch.setenv("PICA_ZIP_PASSWORD", "env-zip-password")

    config = pica.load_config(config_args())
    doctor_text = pica.format_doctor(config, pyzipper_available=True)

    assert config.username == "env-user"
    assert config.password == "env-password"
    assert config.zip_password == "env-zip-password"
    assert "env-password" not in doctor_text
    assert "env-zip-password" not in doctor_text
    assert "PICA_PASSWORD：已配置" in doctor_text
    assert "PICA_ZIP_PASSWORD：已配置" in doctor_text


def test_load_config_reads_random_keywords_and_chapter_mode(monkeypatch):
    pica = load_module()
    monkeypatch.setenv("PICA_RANDOM_KEYWORDS", "校园, 短篇,全彩")
    monkeypatch.setenv("PICA_RANDOM_CHAPTER", "random")

    config = pica.load_config(config_args())

    assert config.random_keywords == ("校园", "短篇", "全彩")
    assert config.random_chapter == "random"


def test_create_encrypted_zip_requires_password_and_preserves_page_order(tmp_path):
    pica = load_module()
    first = tmp_path / "0001.jpg"
    second = tmp_path / "0002.jpg"
    first.write_bytes(b"page-one")
    second.write_bytes(b"page-two")
    zip_path = tmp_path / "chapter.zip"

    pica.create_encrypted_zip([second, first], zip_path, "zip-secret")

    with zipfile.ZipFile(zip_path) as archive:
        assert archive.namelist() == ["0001.jpg", "0002.jpg"]
        with pytest.raises(RuntimeError):
            archive.read("0001.jpg")
        assert archive.read("0001.jpg", pwd=b"zip-secret") == b"page-one"


def test_doctor_reports_builtin_zip_encryption_without_external_dependency():
    pica = load_module()
    config = pica.PicaConfig(username="user", password="pass", zip_password="zip-pass")

    doctor_text = pica.format_doctor(config)

    assert "ZIP 加密：内置可用" in doctor_text
    assert "pyzipper" not in doctor_text


def test_build_random_zip_uses_configured_keyword_and_first_chapter(tmp_path):
    pica = load_module()

    class FakeClient:
        def __init__(self):
            self.config = pica.PicaConfig(zip_password="zip-secret", random_keywords=("校园",), random_chapter="first")
            self.searches = []
            self.selected_order = None

        def search(self, keyword, limit=10):
            self.searches.append((keyword, limit))
            return ([{"_id": "comic-1", "title": "随机漫画", "author": "作者"}], 1)

        def comic_info(self, comic_id):
            return {"title": "随机漫画"}

        def chapters(self, comic_id):
            return [{"order": 1}, {"order": 2}]

        def image_urls_for_chapter(self, comic_id, order):
            self.selected_order = order
            return ["https://example.test/page1.jpg"]

        def download_image(self, url, index):
            return b"page-one"

    fake = FakeClient()

    zip_path, selection = pica.build_random_zip(fake, tmp_path, random.Random(0), limit=5)

    assert fake.searches == [("校园", 5)]
    assert fake.selected_order == 1
    assert selection["keyword"] == "校园"
    assert selection["comic_id"] == "comic-1"
    assert selection["chapter"] == "1"
    assert zip_path.exists()




def test_gitignore_ignores_pica_local_config():
    gitignore_text = (ROOT.parent / ".gitignore").read_text(encoding="utf-8")

    assert "pica/config.local.json" in gitignore_text


def test_pica_template_config_is_safe_and_documented():
    template_path = ROOT / "config.local.example.json"
    template = json.loads(template_path.read_text(encoding="utf-8"))
    skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert {"username", "password", "zip_password"}.issubset(template)
    assert template["username"] != ""
    assert template["password"] != ""
    assert template["zip_password"] != ""
    assert "config.local.example.json" in skill_text
    assert "config.local.json" in skill_text


def test_repository_readme_lists_available_skills():
    readme_text = (ROOT.parent / "README.md").read_text(encoding="utf-8")

    for skill_name in ["music", "javbus", "pica"]:
        assert skill_name in readme_text
    assert "config.local.example.json" in readme_text
    assert "ZIP" in readme_text

    pica = load_module()
    parser = pica.build_parser()
    subparser_actions = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
    choices = set(subparser_actions[0].choices)

    assert {"doctor", "search", "chapters", "zip", "random"}.issubset(choices)


def test_skill_description_mentions_pica_triggers_random_and_password_output():
    skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    for phrase in ["搜xxx漫画", "搜xxxx本子", "我要看本子", "给我整个本子看", "随便来个本子", "pica", "哔咔"]:
        assert phrase in skill_text
    assert "PICA_RANDOM_KEYWORDS" in skill_text
    assert "解压密码" in skill_text
    assert "不要返回图片 URL" in skill_text
