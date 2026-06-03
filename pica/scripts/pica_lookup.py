#!/usr/bin/env python3
import argparse
import hashlib
import hmac
import json
import os
import random
import re
import shutil
import sys
import tempfile
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_API_HOST = "https://picaapi.picacomic.com"
DEFAULT_API_KEY = "C69BAF41DA5ABD1FFEDC6D2FEA56B"
DEFAULT_HMAC_KEY = "~d}$Q7$eIni=V)9\\RK/P.RM4;9[7|@/CA}b~OW!3?EV`:<>M7pddUBL5n|0/*Cn"
USER_AGENT = "okhttp/3.8.1"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.local.json"
DOWNLOAD_ROOT = Path("/download")
DOWNLOAD_MAX_AGE_SECONDS = 24 * 60 * 60


def download_root() -> Path:
    return DOWNLOAD_ROOT.expanduser().resolve()


def resolve_download_dir(value: Any = "") -> Path:
    text = str(value or "").strip()
    root = download_root()
    if not text:
        return root

    raw_path = Path(text).expanduser()
    if raw_path.is_absolute():
        target = raw_path.resolve()
    else:
        target = (root / raw_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PicaError("download output directory must be under /download") from exc
    return target


def cleanup_download_root(max_age_seconds: int = DOWNLOAD_MAX_AGE_SECONDS) -> None:
    root = download_root()
    root.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - max_age_seconds
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        if path.is_file() and stat.st_mtime < cutoff:
            path.unlink(missing_ok=True)
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass


@dataclass
class PicaConfig:
    username: str = ""
    password: str = ""
    zip_password: str = ""
    api_host: str = DEFAULT_API_HOST
    api_key: str = DEFAULT_API_KEY
    hmac_key: str = DEFAULT_HMAC_KEY
    timeout: int = 20
    retries: int = 3
    concurrency: int = 4
    random_keywords: tuple[str, ...] = ("全彩", "短篇", "同人", "校园", "恋爱")
    random_chapter: str = "first"


class PicaError(RuntimeError):
    pass


class PicaClient:
    def __init__(self, config: PicaConfig):
        self.config = config
        self.token = ""
        self.token_expiry = 0.0

    def create_signature(self, path: str, nonce: str, timestamp: str, method: str) -> str:
        raw = path + timestamp + nonce + method + self.config.api_key
        return hmac.new(self.config.hmac_key.encode(), raw.lower().encode(), hashlib.sha256).hexdigest()

    def build_headers(self, method: str, path: str, auth_token: str | None = None) -> dict[str, str]:
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        headers = {
            "api-key": self.config.api_key,
            "accept": "application/vnd.picacomic.com.v1+json",
            "app-channel": "2",
            "time": timestamp,
            "nonce": nonce,
            "signature": self.create_signature(path, nonce, timestamp, method),
            "app-version": "2.2.1.3.3.4",
            "app-uuid": "defaultUuid",
            "image-quality": "original",
            "app-platform": "android",
            "app-build-version": "45",
            "Content-Type": "application/json; charset=UTF-8",
            "user-agent": USER_AGENT,
        }
        if auth_token:
            headers["authorization"] = auth_token
        return headers

    def request_json(self, method: str, path: str, body: dict[str, Any] | None = None, auth: bool = False) -> dict[str, Any]:
        token = self.ensure_token() if auth else None
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self.config.api_host.rstrip('/')}/{path}",
            data=data,
            headers=self.build_headers(method, path, token),
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise PicaError(f"Pica API HTTP {error.code}: {detail[:200]}") from error
        except Exception as error:
            raise PicaError(f"Pica API request failed: {error}") from error

    def login(self) -> str:
        if not self.config.username or not self.config.password:
            raise PicaError("PICA_USERNAME and PICA_PASSWORD are required")
        payload = self.request_json("POST", "auth/sign-in", {
            "email": self.config.username,
            "password": self.config.password,
        })
        token = payload.get("data", {}).get("token") if isinstance(payload, dict) else None
        if not token:
            raise PicaError("Pica login failed: missing token")
        self.token = str(token)
        self.token_expiry = time.time() + 24 * 60 * 60
        return self.token

    def ensure_token(self) -> str:
        if self.token and time.time() < self.token_expiry:
            return self.token
        return self.login()

    def search(self, keyword: str, limit: int = 10) -> tuple[list[dict[str, Any]], int]:
        request_path = f"comics/search?page=1&q={urllib.parse.quote(keyword)}"
        payload = self.request_json("GET", request_path, auth=True)
        comics = payload.get("data", {}).get("comics", {}) if isinstance(payload, dict) else {}
        docs = comics.get("docs") or []
        total = int(comics.get("total") or len(docs))
        return docs[:limit], total

    def comic_info(self, comic_id: str) -> dict[str, Any]:
        payload = self.request_json("GET", f"comics/{urllib.parse.quote(comic_id)}", auth=True)
        return payload.get("data", {}).get("comic", {}) if isinstance(payload, dict) else {}

    def chapters(self, comic_id: str) -> list[dict[str, Any]]:
        chapters: list[dict[str, Any]] = []
        current_page = 1
        total_pages = 1
        path = f"comics/{urllib.parse.quote(comic_id)}/eps"
        while current_page <= total_pages:
            request_path = f"{path}?page={current_page}"
            payload = self.request_json("GET", request_path, auth=True)
            eps = payload.get("data", {}).get("eps", {}) if isinstance(payload, dict) else {}
            docs = eps.get("docs") or []
            if current_page == 1:
                total_pages = int(eps.get("pages") or 1)
            chapters.extend({"order": item.get("order"), "id": item.get("_id"), "title": item.get("title", "")} for item in docs)
            current_page += 1
            if current_page <= total_pages:
                time.sleep(0.5)
        return sorted(chapters, key=lambda item: int(item.get("order") or 0))

    def image_urls_for_chapter(self, comic_id: str, order: int) -> list[str]:
        urls: list[str] = []
        current_page = 1
        total_pages = 1
        path = f"comics/{urllib.parse.quote(comic_id)}/order/{order}/pages"
        while current_page <= total_pages:
            request_path = f"{path}?page={current_page}"
            payload = self.request_json("GET", request_path, auth=True)
            pages = payload.get("data", {}).get("pages", {}) if isinstance(payload, dict) else {}
            docs = pages.get("docs") or []
            if current_page == 1:
                total_pages = int(pages.get("pages") or 1)
                if int(pages.get("total") or len(docs)) == 0:
                    return []
            for doc in docs:
                media = doc.get("media") or {}
                file_server = media.get("fileServer")
                media_path = media.get("path")
                if file_server and media_path:
                    urls.append(f"{file_server}/static/{media_path}")
            current_page += 1
            if current_page <= total_pages:
                time.sleep(0.5)
        return urls

    def download_image(self, url: str, index: int) -> bytes:
        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                request = urllib.request.Request(url, headers={"user-agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                    return response.read()
            except Exception as error:
                last_error = error
                if attempt < self.config.retries:
                    time.sleep(2)
        raise PicaError(f"image {index + 1} download failed: {last_error}")


def sanitize_filename(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value).strip()
    return value or "pica"


def format_search_results(keyword: str, comics: list[dict[str, Any]], total: int | None = None) -> str:
    if not comics:
        return f"没找到和「{keyword}」相关的漫画。"
    count_text = total if total is not None else len(comics)
    lines = [f"我找到了 {count_text} 个和「{keyword}」相关的结果，先显示前 {len(comics)} 个："]
    for index, comic in enumerate(comics, 1):
        lines.extend([
            f"{index}. {comic.get('title', '')}",
            f"作者：{comic.get('author') or '未知'}",
            f"ID：{comic.get('_id', '')}",
        ])
    lines.append("你要哪一本？可以回复序号或漫画 ID。")
    return "\n".join(lines)


def format_chapters(chapters: list[dict[str, Any]]) -> str:
    if not chapters:
        return "没有获取到章节列表。"
    lines = ["章节列表："]
    for chapter in chapters:
        title = chapter.get("title") or f"第 {chapter.get('order')} 话"
        lines.append(f"{chapter.get('order')}. {title}")
    lines.append("你要哪一话？也可以说 full 打包全本。")
    return "\n".join(lines)


CRC_TABLE = None


def zip_crc_table() -> list[int]:
    global CRC_TABLE
    if CRC_TABLE is None:
        table = []
        for value in range(256):
            crc = value
            for _ in range(8):
                if crc & 1:
                    crc = ((crc >> 1) ^ 0xEDB88320) & 0xFFFFFFFF
                else:
                    crc >>= 1
            table.append(crc)
        CRC_TABLE = table
    return CRC_TABLE


def zip_crypto_crc32(value: int, byte: int) -> int:
    table = zip_crc_table()
    return ((value >> 8) ^ table[(value ^ byte) & 0xFF]) & 0xFFFFFFFF


def zip_crypto_header(password: bytes, crc: int) -> tuple[bytes, list[int]]:
    keys = zip_crypto_keys(password)
    header = bytearray([0] * 11 + [(crc >> 24) & 0xFF])
    encrypted = bytearray()
    for value in header:
        encrypted.append(zip_crypto_transform_byte(keys, value))
    return bytes(encrypted), keys


def zip_crypto_keys(password: bytes) -> list[int]:
    keys = [0x12345678, 0x23456789, 0x34567890]
    for value in password:
        zip_crypto_update_keys(keys, value)
    return keys


def zip_crypto_update_keys(keys: list[int], value: int) -> None:
    keys[0] = zip_crypto_crc32(keys[0], value)
    keys[1] = (keys[1] + (keys[0] & 0xFF)) & 0xFFFFFFFF
    keys[1] = (keys[1] * 134775813 + 1) & 0xFFFFFFFF
    keys[2] = zip_crypto_crc32(keys[2], (keys[1] >> 24) & 0xFF)


def zip_crypto_transform_byte(keys: list[int], value: int) -> int:
    temp = (keys[2] | 2) & 0xFFFFFFFF
    mask = ((temp * (temp ^ 1)) >> 8) & 0xFF
    output = value ^ mask
    zip_crypto_update_keys(keys, value)
    return output


def zip_crypto_encrypt(data: bytes, password: bytes, crc: int) -> bytes:
    header, keys = zip_crypto_header(password, crc)
    encrypted = bytearray(header)
    for value in data:
        encrypted.append(zip_crypto_transform_byte(keys, value))
    return bytes(encrypted)


def dos_datetime(timestamp: float | None = None) -> tuple[int, int]:
    current = time.localtime(timestamp or time.time())
    dos_time = (current.tm_hour << 11) | (current.tm_min << 5) | (current.tm_sec // 2)
    dos_date = ((current.tm_year - 1980) << 9) | (current.tm_mon << 5) | current.tm_mday
    return dos_time, dos_date


def make_zip_record(name: str, data: bytes, password: str, offset: int) -> tuple[bytes, bytes]:
    name_bytes = name.encode("utf-8")
    crc = zlib.crc32(data) & 0xFFFFFFFF
    compressed = zlib.compressobj(level=6, method=zlib.DEFLATED, wbits=-15)
    compressed_data = compressed.compress(data) + compressed.flush()
    encrypted_data = zip_crypto_encrypt(compressed_data, password.encode(), crc)
    compressed_size = len(encrypted_data)
    uncompressed_size = len(data)
    flags = 0x1 | 0x800
    method = 8
    dos_time, dos_date = dos_datetime()
    local_header = (
        b"PK\x03\x04"
        + (20).to_bytes(2, "little")
        + flags.to_bytes(2, "little")
        + method.to_bytes(2, "little")
        + dos_time.to_bytes(2, "little")
        + dos_date.to_bytes(2, "little")
        + crc.to_bytes(4, "little")
        + compressed_size.to_bytes(4, "little")
        + uncompressed_size.to_bytes(4, "little")
        + len(name_bytes).to_bytes(2, "little")
        + (0).to_bytes(2, "little")
        + name_bytes
    )
    central_header = (
        b"PK\x01\x02"
        + (20).to_bytes(2, "little")
        + (20).to_bytes(2, "little")
        + flags.to_bytes(2, "little")
        + method.to_bytes(2, "little")
        + dos_time.to_bytes(2, "little")
        + dos_date.to_bytes(2, "little")
        + crc.to_bytes(4, "little")
        + compressed_size.to_bytes(4, "little")
        + uncompressed_size.to_bytes(4, "little")
        + len(name_bytes).to_bytes(2, "little")
        + (0).to_bytes(2, "little")
        + (0).to_bytes(2, "little")
        + (0).to_bytes(2, "little")
        + (0).to_bytes(2, "little")
        + (0).to_bytes(4, "little")
        + offset.to_bytes(4, "little")
        + name_bytes
    )
    return local_header + encrypted_data, central_header


def pyzipper_is_available() -> bool:
    return True


def create_encrypted_zip(image_paths: list[Path], zip_path: Path, password: str) -> Path:
    if not password:
        raise PicaError("ZIP password is required")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[bytes] = []
    central_records: list[bytes] = []
    offset = 0
    for path in sorted(image_paths, key=lambda item: item.name):
        record, central = make_zip_record(path.name, path.read_bytes(), password, offset)
        records.append(record)
        central_records.append(central)
        offset += len(record)
    central_dir = b"".join(central_records)
    end_record = (
        b"PK\x05\x06"
        + (0).to_bytes(2, "little")
        + (0).to_bytes(2, "little")
        + len(records).to_bytes(2, "little")
        + len(records).to_bytes(2, "little")
        + len(central_dir).to_bytes(4, "little")
        + offset.to_bytes(4, "little")
        + (0).to_bytes(2, "little")
    )
    zip_path.write_bytes(b"".join(records) + central_dir + end_record)
    return zip_path


def download_images(client: PicaClient, urls: list[str], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[int, Path] = {}
    with ThreadPoolExecutor(max_workers=max(1, client.config.concurrency)) as executor:
        futures = {executor.submit(client.download_image, url, index): index for index, url in enumerate(urls)}
        for future in as_completed(futures):
            index = futures[future]
            data = future.result()
            suffix = image_suffix(urls[index])
            image_path = out_dir / f"{index + 1:04d}{suffix}"
            image_path.write_bytes(data)
            results[index] = image_path
    if len(results) != len(urls):
        raise PicaError("some pages failed to download")
    return [results[index] for index in sorted(results)]


def image_suffix(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for suffix in [".png", ".webp", ".gif", ".jpg", ".jpeg"]:
        if path.endswith(suffix):
            return suffix
    return ".jpg"


def parse_random_keywords(value: str | list[Any] | tuple[Any, ...] | None) -> tuple[str, ...]:
    if not value:
        return ("全彩", "短篇", "同人", "校园", "恋爱")
    if isinstance(value, (list, tuple)):
        keywords = tuple(str(item).strip() for item in value if str(item).strip())
    else:
        keywords = tuple(item.strip() for item in str(value).split(",") if item.strip())
    return keywords or ("全彩", "短篇", "同人", "校园", "恋爱")


def normalize_random_chapter(value: str | None) -> str:
    mode = (value or "first").strip().lower()
    if mode not in {"first", "random"}:
        raise PicaError('PICA_RANDOM_CHAPTER must be "first" or "random"')
    return mode


def load_local_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as error:
        raise PicaError(f"failed to read local config: {config_path}") from error
    if not isinstance(data, dict):
        raise PicaError("local config must be a JSON object")
    return data


def config_value(args: argparse.Namespace, local_config: dict[str, Any], attr: str, env_name: str, default: Any = "") -> Any:
    arg_value = getattr(args, attr, None)
    if arg_value is not None:
        return arg_value
    env_value = os.getenv(env_name)
    if env_value is not None:
        return env_value
    return local_config.get(attr, default)


def load_config(args: argparse.Namespace) -> PicaConfig:
    local_config = load_local_config(getattr(args, "config", None))
    random_keywords = parse_random_keywords(config_value(args, local_config, "random_keywords", "PICA_RANDOM_KEYWORDS", None))
    random_chapter = normalize_random_chapter(config_value(args, local_config, "random_chapter", "PICA_RANDOM_CHAPTER", None))
    return PicaConfig(
        username=str(config_value(args, local_config, "username", "PICA_USERNAME", "")),
        password=str(config_value(args, local_config, "password", "PICA_PASSWORD", "")),
        zip_password=str(config_value(args, local_config, "zip_password", "PICA_ZIP_PASSWORD", "")),
        api_host=str(config_value(args, local_config, "api_host", "PICA_API_HOST", DEFAULT_API_HOST)),
        api_key=str(config_value(args, local_config, "api_key", "PICA_API_KEY", DEFAULT_API_KEY)),
        hmac_key=str(config_value(args, local_config, "hmac_key", "PICA_HMAC_KEY", DEFAULT_HMAC_KEY)),
        timeout=int(config_value(args, local_config, "timeout", "PICA_TIMEOUT", 20)),
        retries=int(config_value(args, local_config, "retries", "PICA_RETRIES", 3)),
        concurrency=int(config_value(args, local_config, "concurrency", "PICA_CONCURRENCY", 4)),
        random_keywords=random_keywords,
        random_chapter=random_chapter,
    )


def format_doctor(config: PicaConfig, pyzipper_available: bool | None = None) -> str:
    return "\n".join([
        "Pica skill doctor:",
        f"PICA_USERNAME：{'已配置' if config.username else '未配置'}",
        f"PICA_PASSWORD：{'已配置' if config.password else '未配置'}",
        f"PICA_ZIP_PASSWORD：{'已配置' if config.zip_password else '未配置'}",
        "ZIP 加密：内置可用",
        f"API Host：{config.api_host}",
    ])


def build_zip(client: PicaClient, comic_id: str, chapter: str, out_dir: Path) -> Path:
    if not client.config.zip_password:
        raise PicaError("PICA_ZIP_PASSWORD is required")
    comic_info = client.comic_info(comic_id)
    title = sanitize_filename(str(comic_info.get("title") or comic_id))
    if chapter.lower() == "full":
        chapters = client.chapters(comic_id)
        if not chapters:
            raise PicaError("no chapters found")
        chapter_orders = [int(item["order"]) for item in chapters if item.get("order") is not None]
        chapter_label = "full"
    elif chapter.isdigit():
        chapter_orders = [int(chapter)]
        chapter_label = f"chapter-{int(chapter):03d}"
    else:
        raise PicaError('chapter must be a number or "full"')
    timestamp = int(time.time())
    zip_path = out_dir / f"{title}_{chapter_label}_{timestamp}.zip"
    with tempfile.TemporaryDirectory(prefix="pica_zip_") as temp:
        temp_dir = Path(temp)
        image_paths: list[Path] = []
        page_index = 1
        for order in chapter_orders:
            urls = client.image_urls_for_chapter(comic_id, order)
            if not urls:
                raise PicaError(f"chapter {order} has no pages")
            chapter_dir = temp_dir / f"chapter_{order:03d}"
            downloaded = download_images(client, urls, chapter_dir)
            for downloaded_path in downloaded:
                target = temp_dir / f"{page_index:04d}{downloaded_path.suffix}"
                shutil.move(str(downloaded_path), target)
                image_paths.append(target)
                page_index += 1
        return create_encrypted_zip(image_paths, zip_path, client.config.zip_password)


def build_random_zip(client: PicaClient, out_dir: Path, rng: random.Random | None = None, limit: int = 10) -> tuple[Path, dict[str, str]]:
    rng = rng or random.Random()
    keywords = client.config.random_keywords
    if not keywords:
        raise PicaError("PICA_RANDOM_KEYWORDS is empty")
    keyword = rng.choice(keywords)
    comics, _ = client.search(keyword, limit)
    if not comics:
        raise PicaError(f"no comics found for random keyword: {keyword}")
    comic = rng.choice(comics)
    comic_id = str(comic.get("_id") or "")
    if not comic_id:
        raise PicaError("selected random comic has no id")
    chapters = client.chapters(comic_id)
    if not chapters:
        raise PicaError("selected random comic has no chapters")
    if client.config.random_chapter == "random":
        chapter_order = int(rng.choice(chapters).get("order") or 1)
    else:
        chapter_order = int(chapters[0].get("order") or 1)
    zip_path = build_zip(client, comic_id, str(chapter_order), out_dir)
    return zip_path, {
        "keyword": keyword,
        "comic_id": comic_id,
        "title": str(comic.get("title") or comic_id),
        "chapter": str(chapter_order),
    }


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=None)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--zip-password")
    parser.add_argument("--api-host")
    parser.add_argument("--api-key")
    parser.add_argument("--hmac-key")
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--retries", type=int)
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--random-keywords")
    parser.add_argument("--random-chapter", choices=["first", "random"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search and download Pica comics as encrypted ZIP files.")
    add_common_options(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor")

    search_parser = sub.add_parser("search")
    search_parser.add_argument("keyword")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("--json", action="store_true")

    chapters_parser = sub.add_parser("chapters")
    chapters_parser.add_argument("comic_id")

    zip_parser = sub.add_parser("zip")
    zip_parser.add_argument("comic_id")
    zip_parser.add_argument("chapter")
    zip_parser.add_argument("--out", default="/download", help="Output directory under /download.")

    random_parser = sub.add_parser("random")
    random_parser.add_argument("--out", default="/download", help="Output directory under /download.")
    random_parser.add_argument("--limit", type=int, default=10)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(args)
    try:
        if args.command == "doctor":
            print(format_doctor(config))
            return 0
        client = PicaClient(config)
        if args.command == "search":
            comics, total = client.search(args.keyword, args.limit)
            print(json.dumps(comics, ensure_ascii=False, indent=2) if args.json else format_search_results(args.keyword, comics, total))
            return 0
        if args.command == "chapters":
            print(format_chapters(client.chapters(args.comic_id)))
            return 0
        if args.command == "zip":
            cleanup_download_root()
            zip_path = build_zip(client, args.comic_id, args.chapter, resolve_download_dir(args.out))
            print(f"ZIP 文件已生成：{zip_path}")
            print("解压密码：使用已配置的 PICA_ZIP_PASSWORD")
            return 0
        if args.command == "random":
            cleanup_download_root()
            zip_path, selection = build_random_zip(client, resolve_download_dir(args.out), limit=args.limit)
            print(f"随机关键词：{selection['keyword']}")
            print(f"随机选择：{selection['title']} / 第 {selection['chapter']} 话")
            print(f"ZIP 文件已生成：{zip_path}")
            print("解压密码：使用已配置的 PICA_ZIP_PASSWORD")
            return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding.lower() != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
    if sys.stderr.encoding.lower() != 'utf-8':
        try:
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass
    raise SystemExit(main())
