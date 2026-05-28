#!/usr/bin/env python3
"""comic_lookup.py — Koishi skill helper for the local comic-api aggregator.

Talks to the FastAPI service at http://127.0.0.1:8699 (comic-api, lumia1998/comic-api).
If the service is not running, the script auto-clones and starts it.

Usage:
    python scripts/comic_lookup.py doctor
    python scripts/comic_lookup.py search "花火" [--source jm|bika|all] [--limit 10]
    python scripts/comic_lookup.py detail jm 123456
    python scripts/comic_lookup.py detail bika <comic_id>
    python scripts/comic_lookup.py download <source> <comic_id> [--chapter <ch_id>] [--out ./downloads]
    python scripts/comic_lookup.py leaderboard [--source jm|bika] [--mode day|week|month|total]
    python scripts/comic_lookup.py category [--source jm|bika] [--name 同人]
    python scripts/comic_lookup.py latest [--source jm|bika]
    python scripts/comic_lookup.py random [--source jm|bika]
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

DEFAULT_API_BASE = "http://127.0.0.1:8699"
DEFAULT_PROJECT_DIR = str(Path(__file__).resolve().parents[3] / "comic-api")
DEFAULT_OUT_DIR = str(Path(__file__).resolve().parents[1] / "downloads")
DEFAULT_API_REPO = "https://github.com/lumia1998/comic-api"
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_BIND_PORT = 8699
DEFAULT_START_TIMEOUT = 90

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.local.json"

# ZIP: 6-digit pure-numeric password derived from chapter id
PAGES_PER_10MB = 50          # approx 50 pages ≈ 10 MB; split threshold
MAX_PAGES_PER_PART = 50      # chapter slice size for ZIP parts

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_local_config(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else CONFIG_PATH
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"config read error: {p}") from e
    if not isinstance(data, dict):
        raise RuntimeError("config.local.json must be a JSON object")
    return data


def config_value(
    args: argparse.Namespace,
    local: dict,
    attr: str,
    env: str,
    default: Any,
) -> Any:
    v = getattr(args, attr, None)
    if v is not None and v != "":
        return v
    v = os.environ.get(env, "")
    if v:
        return v
    return local.get(attr, default)


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def auto_deploy_enabled(args: argparse.Namespace, local: dict) -> bool:
    if getattr(args, "no_auto_deploy", False):
        return False
    if "COMIC_API_AUTO_DEPLOY" in os.environ:
        return _as_bool(os.environ["COMIC_API_AUTO_DEPLOY"], default=True)
    if "auto_deploy" in local:
        return _as_bool(local["auto_deploy"], default=True)
    return True


def normalize_source(src: str) -> str:
    """将源标识符归一化为 'jm' 或 'bika'"""
    if not src:
        return src
    src_lower = src.strip().lower()
    if src_lower in ("jm", "禁漫", "禁漫天堂"):
        return "jm"
    if src_lower in ("bika", "哔咔", "哔咔漫画", "pica"):
        return "bika"
    return src_lower

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def api_url(base: str, path: str, query: dict[str, Any] | None = None) -> str:
    url = base.rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return url


def _http_error(e: urllib.error.HTTPError) -> RuntimeError:
    body = e.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(body)
        msg = payload.get("detail") or payload.get("message") or body
    except Exception:
        msg = body
    return RuntimeError(f"HTTP {e.code}: {msg}")


def _get_json(url: str, timeout: int = 20) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise _http_error(e) from e


def _download_bytes(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise _http_error(e) from e

# ---------------------------------------------------------------------------
# Service management
# ---------------------------------------------------------------------------

def is_service_running(base: str) -> bool:
    try:
        data = _get_json(api_url(base, "/health"), timeout=3)
        return isinstance(data, dict) and data.get("status") == "ok"
    except Exception:
        # Fallback: try the root endpoint for a 200
        try:
            urllib.request.urlopen(base.rstrip("/") + "/", timeout=3)
            return True
        except Exception:
            return False


def _venv_python(project_dir: str) -> Path:
    pd = Path(project_dir)
    if os.name == "nt":
        for candidate in [
            pd / ".venv" / "Scripts" / "python.exe",
            pd / "venv" / "Scripts" / "python.exe",
        ]:
            if candidate.exists():
                return candidate
        return pd / ".venv" / "Scripts" / "python.exe"
    for candidate in [
        pd / ".venv" / "bin" / "python",
        pd / "venv" / "bin" / "python",
    ]:
        if candidate.exists():
            return candidate
    return pd / ".venv" / "bin" / "python"


def _run_checked(cmd: list[str], *, cwd: str | Path | None = None, label: str) -> None:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout or "").strip()[-2000:]
    raise RuntimeError(f"{label} failed" + (f": {detail}" if detail else ""))


def _ensure_project(project_dir: str, api_repo: str) -> None:
    pd = Path(project_dir)
    if pd.exists() and (pd / "main.py").exists():
        return
    if pd.exists() and not (pd / "main.py").exists():
        raise RuntimeError(
            f"目录已存在但不像 comic-api 项目: {project_dir}，请检查 project_dir 配置"
        )
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git 未安装，无法自动克隆 comic-api")
    print(f"[comic] 正在克隆 comic-api 到 {project_dir} ...", flush=True)
    pd.parent.mkdir(parents=True, exist_ok=True)
    _run_checked([git, "clone", api_repo, str(pd)], label="git clone")


def _ensure_deps(project_dir: str) -> None:
    pd = Path(project_dir)
    python = _venv_python(project_dir)
    if python.exists():
        # Already installed
        return
    # Try uv first
    uv = shutil.which("uv")
    pip = shutil.which("pip") or shutil.which("pip3")
    req = pd / "requirements.txt"
    if uv:
        print("[comic] uv sync 安装依赖 ...", flush=True)
        _run_checked([uv, "venv"], cwd=pd, label="uv venv")
        _run_checked([uv, "pip", "install", "-r", str(req)], cwd=pd, label="uv pip install")
    elif pip:
        import venv as venv_mod
        print("[comic] 使用 pip 安装依赖 ...", flush=True)
        venv_mod.create(str(pd / ".venv"), with_pip=True)
        _run_checked(
            [str(_venv_python(project_dir)), "-m", "pip", "install", "-r", str(req)],
            cwd=pd,
            label="pip install",
        )
    else:
        raise RuntimeError("未找到 uv 或 pip，无法安装 comic-api 依赖")


def start_service(
    project_dir: str,
    base: str,
    *,
    api_repo: str,
    bind_host: str = DEFAULT_BIND_HOST,
    start_timeout: int = DEFAULT_START_TIMEOUT,
) -> None:
    _ensure_project(project_dir, api_repo)
    _ensure_deps(project_dir)

    pd = Path(project_dir)
    python = _venv_python(project_dir)
    port = str(DEFAULT_BIND_PORT)
    parsed = urllib.parse.urlparse(base)
    if parsed.port:
        port = str(parsed.port)

    log_path = pd / "comic-api.log"
    print(f"[comic] 正在启动 comic-api 服务 {bind_host}:{port} ...", flush=True)

    env = os.environ.copy()
    creationflags = 0
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        popen_kwargs["start_new_session"] = True

    # comic-api uses: uvicorn main:app --host ... --port ...
    uvicorn = shutil.which("uvicorn") or str(python.parent / "uvicorn")
    cmd: list[str]
    if str(python) != "python" and python.exists():
        cmd = [str(python), "-m", "uvicorn", "main:app",
               "--host", bind_host, "--port", port]
    else:
        cmd = [str(uvicorn), "main:app", "--host", bind_host, "--port", port]

    with open(log_path, "ab") as log:
        subprocess.Popen(
            cmd,
            cwd=str(pd),
            stdout=log,
            stderr=log,
            env=env,
            creationflags=creationflags,
            **popen_kwargs,
        )

    print("[comic] 等待服务启动 ...", flush=True)
    deadline = time.monotonic() + start_timeout
    while time.monotonic() < deadline:
        time.sleep(2)
        if is_service_running(base):
            print("[comic] 服务已就绪。", flush=True)
            return
    raise RuntimeError(f"服务在 {start_timeout}s 内未能启动，请查看日志: {log_path}")


def ensure_service(base: str, project_dir: str, args: argparse.Namespace, local: dict) -> None:
    if is_service_running(base):
        return
    if not auto_deploy_enabled(args, local):
        raise RuntimeError(f"comic-api 未运行且自动部署已禁用: {base}")
    api_repo = config_value(args, local, "api_repo", "COMIC_API_REPO", DEFAULT_API_REPO)
    bind_host = config_value(args, local, "bind_host", "COMIC_API_BIND_HOST", DEFAULT_BIND_HOST)
    start_timeout = int(config_value(args, local, "start_timeout", "COMIC_API_START_TIMEOUT", DEFAULT_START_TIMEOUT))
    print("[comic] 服务未运行，正在自动部署 ...", flush=True)
    start_service(project_dir, base, api_repo=api_repo, bind_host=bind_host, start_timeout=start_timeout)

# ---------------------------------------------------------------------------
# API calls (comic-api endpoints)
# ---------------------------------------------------------------------------

def api_search(base: str, keyword: str) -> dict[str, Any]:
    """GET /api/search?keyword=..."""
    url = api_url(base, "/api/search", {"keyword": keyword})
    return _get_json(url)


def api_comic_detail(base: str, source: str, comic_id: str) -> dict[str, Any]:
    """GET /api/comic/{source}/{comic_id}"""
    url = api_url(base, f"/api/comic/{source}/{urllib.parse.quote(str(comic_id), safe='')}")
    return _get_json(url, timeout=30)


def api_chapter_images(base: str, source: str, comic_id: str, chapter_id: str) -> list[str]:
    """GET /api/chapter/{source}/{comic_id}/{chapter_id}"""
    url = api_url(base, f"/api/chapter/{source}/{urllib.parse.quote(str(comic_id), safe='')}/{urllib.parse.quote(str(chapter_id), safe='')}")
    data = _get_json(url, timeout=60)
    return data.get("images", [])


def api_leaderboard(base: str, source: str, mode: str = "day", page: int = 1) -> dict[str, Any]:
    """GET /api/{source}/leaderboard?mode=..."""
    url = api_url(base, f"/api/{source}/leaderboard", {"mode": mode, "page": page})
    return _get_json(url, timeout=30)


def api_category(base: str, source: str, name: str, page: int = 1, sort: str = "dd") -> dict[str, Any]:
    """GET /api/{source}/category?name=...&sort=..."""
    url = api_url(base, f"/api/{source}/category", {"name": name, "page": page, "sort": sort})
    return _get_json(url, timeout=30)


def api_latest(base: str, source: str, page: int = 1, sort: str = "dd") -> dict[str, Any]:
    """GET /api/{source}/latest?page=...&sort=..."""
    url = api_url(base, f"/api/{source}/latest", {"page": page, "sort": sort})
    return _get_json(url, timeout=30)


def api_random(base: str, source: str) -> dict[str, Any]:
    """GET /api/{source}/random"""
    url = api_url(base, f"/api/{source}/random")
    return _get_json(url, timeout=30)

# ---------------------------------------------------------------------------
# ZIP creation helpers (pure stdlib, AES-128 ZipCrypto password)
# ---------------------------------------------------------------------------

CRC_TABLE: list[int] | None = None


def _crc_table() -> list[int]:
    global CRC_TABLE
    if CRC_TABLE is None:
        table = []
        for v in range(256):
            crc = v
            for _ in range(8):
                if crc & 1:
                    crc = ((crc >> 1) ^ 0xEDB88320) & 0xFFFFFFFF
                else:
                    crc >>= 1
            table.append(crc)
        CRC_TABLE = table
    return CRC_TABLE


def _zcrc(val: int, b: int) -> int:
    t = _crc_table()
    return ((val >> 8) ^ t[(val ^ b) & 0xFF]) & 0xFFFFFFFF


def _zkeys(pwd: bytes) -> list[int]:
    keys = [0x12345678, 0x23456789, 0x34567890]
    for b in pwd:
        _zupdate(keys, b)
    return keys


def _zupdate(keys: list[int], b: int) -> None:
    keys[0] = _zcrc(keys[0], b)
    keys[1] = (keys[1] + (keys[0] & 0xFF)) & 0xFFFFFFFF
    keys[1] = (keys[1] * 134775813 + 1) & 0xFFFFFFFF
    keys[2] = _zcrc(keys[2], (keys[1] >> 24) & 0xFF)


def _zbyte(keys: list[int], b: int) -> int:
    t = (keys[2] | 2) & 0xFFFFFFFF
    mask = ((t * (t ^ 1)) >> 8) & 0xFF
    out = b ^ mask
    _zupdate(keys, b)
    return out


def _zencrypt(data: bytes, pwd: bytes, crc: int) -> bytes:
    keys = _zkeys(pwd)
    header = bytearray([0] * 11 + [(crc >> 24) & 0xFF])
    enc_header = bytearray(_zbyte(keys, v) for v in header)
    enc_data = bytearray(_zbyte(keys, b) for b in data)
    return bytes(enc_header) + bytes(enc_data)


def _dos_datetime() -> tuple[int, int]:
    t = time.localtime()
    dt = (t.tm_hour << 11) | (t.tm_min << 5) | (t.tm_sec // 2)
    dd = ((t.tm_year - 1980) << 9) | (t.tm_mon << 5) | t.tm_mday
    return dt, dd


def _zip_entry(name: str, data: bytes, pwd: str, offset: int) -> tuple[bytes, bytes]:
    name_b = name.encode("utf-8")
    crc = zlib.crc32(data) & 0xFFFFFFFF
    comp = zlib.compressobj(level=6, method=zlib.DEFLATED, wbits=-15)
    comp_data = comp.compress(data) + comp.flush()
    enc = _zencrypt(comp_data, pwd.encode(), crc)
    cs = len(enc)
    us = len(data)
    flags = 0x1 | 0x800
    method = 8
    dt, dd = _dos_datetime()

    local = (
        b"PK\x03\x04"
        + (20).to_bytes(2, "little")
        + flags.to_bytes(2, "little")
        + method.to_bytes(2, "little")
        + dt.to_bytes(2, "little")
        + dd.to_bytes(2, "little")
        + crc.to_bytes(4, "little")
        + cs.to_bytes(4, "little")
        + us.to_bytes(4, "little")
        + len(name_b).to_bytes(2, "little")
        + (0).to_bytes(2, "little")
        + name_b
        + enc
    )
    central = (
        b"PK\x01\x02"
        + (20).to_bytes(2, "little")
        + (20).to_bytes(2, "little")
        + flags.to_bytes(2, "little")
        + method.to_bytes(2, "little")
        + dt.to_bytes(2, "little")
        + dd.to_bytes(2, "little")
        + crc.to_bytes(4, "little")
        + cs.to_bytes(4, "little")
        + us.to_bytes(4, "little")
        + len(name_b).to_bytes(2, "little")
        + (0).to_bytes(2, "little")
        + (0).to_bytes(2, "little")
        + (0).to_bytes(2, "little")
        + (0).to_bytes(2, "little")
        + (0).to_bytes(4, "little")
        + offset.to_bytes(4, "little")
        + name_b
    )
    return local, central


def create_encrypted_zip(image_paths: list[Path], zip_path: Path, password: str) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[bytes] = []
    centrals: list[bytes] = []
    offset = 0
    for p in sorted(image_paths, key=lambda x: x.name):
        data = p.read_bytes()
        local, central = _zip_entry(p.name, data, password, offset)
        records.append(local)
        centrals.append(central)
        offset += len(local)
    central_dir = b"".join(centrals)
    eocd = (
        b"PK\x05\x06"
        + (0).to_bytes(2, "little")
        + (0).to_bytes(2, "little")
        + len(records).to_bytes(2, "little")
        + len(records).to_bytes(2, "little")
        + len(central_dir).to_bytes(4, "little")
        + offset.to_bytes(4, "little")
        + (0).to_bytes(2, "little")
    )
    zip_path.write_bytes(b"".join(records) + central_dir + eocd)

# ---------------------------------------------------------------------------
# Password generation (6-digit pure numeric)
# ---------------------------------------------------------------------------

def make_password(seed: str) -> str:
    """Derive a 6-digit numeric password from the chapter/comic id."""
    import hashlib
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    return str(h % 1_000_000).zfill(6)

# ---------------------------------------------------------------------------
# Image download
# ---------------------------------------------------------------------------

def _image_suffix(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for ext in [".png", ".webp", ".gif", ".jpg", ".jpeg"]:
        if path.endswith(ext):
            return ext
    return ".jpg"


def _dl_image(url: str, idx: int, retries: int = 3, timeout: int = 30) -> bytes:
    last: Exception = RuntimeError("no attempt")
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7 Build/TQ1A.230305.002) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36",
                "Referer": url,
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(2)
    raise RuntimeError(f"图片 {idx+1} 下载失败: {last}")


def download_images_parallel(
    urls: list[str],
    out_dir: Path,
    concurrency: int = 4,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[int, Path] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(_dl_image, url, idx): idx
            for idx, url in enumerate(urls)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            data = fut.result()
            suffix = _image_suffix(urls[idx])
            p = out_dir / f"{idx+1:04d}{suffix}"
            p.write_bytes(data)
            results[idx] = p
    if len(results) != len(urls):
        raise RuntimeError("部分图片下载失败")
    return [results[i] for i in sorted(results)]

# ---------------------------------------------------------------------------
# High-level download: chapter → split ZIPs if > MAX_PAGES_PER_PART pages
# ---------------------------------------------------------------------------

def sanitize(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "comic"


def download_chapter(
    base: str,
    source: str,
    comic_id: str,
    chapter_id: str,
    chapter_name: str,
    comic_title: str,
    out_dir: Path,
    concurrency: int = 4,
) -> list[Path]:
    """下载章节并生成一个或多个加密 ZIP 文件。

    返回生成的 ZIP 文件路径列表。
    密码是根据 chapter_id 派生的 6 位纯数字。
    自适应分卷逻辑：
    - 首先尝试打包为单个 ZIP 文件。
    - 判断单文件大小是否符合限制：每 50 页对应 10MB (limit_mb = 10 * math.ceil(total_pages / 50))。
    - 如果单文件大小未超限，则直接返回单文件，不进行分拆（如：90 页文件若小于 20MB 则直接发送单文件）。
    - 如果单文件大小超限，则根据页数及体积限制自动分割成多份（分卷）打包发送。
    """
    print(f"[comic] 获取章节图片列表: {source}/{comic_id}/{chapter_id} ...", flush=True)
    images = api_chapter_images(base, source, comic_id, chapter_id)
    if not images:
        raise RuntimeError("该章节没有图片，或平台限制访问")

    password = make_password(chapter_id)
    safe_title = sanitize(comic_title)
    safe_ch = sanitize(chapter_name)
    total = len(images)

    with tempfile.TemporaryDirectory(prefix="comic_dl_") as tmp:
        tmp_dir = Path(tmp)
        print(f"[comic] 共 {total} 页，正在并行下载 ...", flush=True)
        # 下载所有图片到临时目录
        all_paths = download_images_parallel(images, tmp_dir, concurrency=concurrency)

        # 尝试先打包成单个 ZIP
        single_zip_name = f"{safe_title}_{safe_ch}.zip"
        single_zip_path = out_dir / single_zip_name
        print(f"[comic] 尝试打包为单文件: {single_zip_name} ...", flush=True)
        create_encrypted_zip(all_paths, single_zip_path, password)

        # 限制规格：每 50 页对应 10MB
        # <=50页：限制 10MB
        # 51-100页：限制 20MB
        # 101-150页：限制 30MB
        # 依此类推：limit_mb = 10 * math.ceil(total / 50)
        limit_mb = 10 * math.ceil(total / 50)
        file_size_mb = single_zip_path.stat().st_size / (1024 * 1024)

        print(f"[comic] 单文件大小: {file_size_mb:.1f}MB, 限制上限: {limit_mb}MB", flush=True)

        if file_size_mb <= limit_mb:
            print(f"[comic] 大小未超限({file_size_mb:.1f}MB <= {limit_mb}MB)，直接发送单文件。", flush=True)
            return [single_zip_path]
        else:
            # 超过了限制体积，分卷压缩发送
            try:
                single_zip_path.unlink()
            except Exception:
                pass

            # 分卷份数计算
            parts = math.ceil(total / 50)
            if parts < 2:
                parts = 2  # 哪怕页数小于50，但体积超10M了，也必须至少分两份

            # 计算每份页数
            pages_per_part = math.ceil(total / parts)
            print(f"[comic] 文件大小超限({file_size_mb:.1f}MB > {limit_mb}MB)，将分卷为 {parts} 份打包发送（每份约 {pages_per_part} 页）...", flush=True)

            zip_paths: list[Path] = []
            for part_idx in range(parts):
                start = part_idx * pages_per_part
                end = min(start + pages_per_part, total)
                part_paths = all_paths[start:end]

                zip_name = f"{safe_title}_{safe_ch}_part{part_idx+1:02d}.zip"
                zip_path = out_dir / zip_name
                print(f"[comic] 打包加密 ZIP 分卷 {part_idx+1}/{parts}: {zip_name} ...", flush=True)
                create_encrypted_zip(part_paths, zip_path, password)
                zip_paths.append(zip_path)

            return zip_paths

# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def fmt_comics(comics: list[dict], source_label: str = "") -> str:
    if not comics:
        return "没有找到相关漫画。"
    lines = []
    for i, c in enumerate(comics, 1):
        title = c.get("title", "未知标题")
        author = c.get("author") or "佚名"
        cid = c.get("id", "")
        src = c.get("source", source_label)
        lines.append(f"{i}. [{src}|{cid}] {title}  作者:{author}")
    return "\n".join(lines)


def fmt_search(result: dict, limit: int = 10, source: str = "all") -> str:
    best = result.get("best_match") or {}
    all_res = result.get("all_results") or {}
    jm_list = all_res.get("jm", [])
    bika_list = all_res.get("bika", [])

    parts: list[str] = []
    # 只有当最佳匹配的源符合筛选源时，才显示最佳匹配
    if best and best.get("title"):
        best_source = best.get("source")
        if source == "all" or best_source == source:
            src_label = "禁漫" if best_source == "jm" else "哔咔"
            parts.append(f"[最佳] [{src_label}|{best.get('id')}]:\n  {best.get('title')}  作者:{best.get('author','佚名')}")

    combined: list[dict] = []
    if source in ("all", "jm"):
        for item in jm_list:
            item = dict(item); item.setdefault("source", "jm"); combined.append(item)
    if source in ("all", "bika"):
        for item in bika_list:
            item = dict(item); item.setdefault("source", "bika"); combined.append(item)

    if limit is not None and limit > 0:
        combined = combined[:limit]

    if combined:
        parts.append(f"\n找到 {len(combined)} 个结果：")
        for i, c in enumerate(combined, 1):
            src = "禁漫" if c.get("source") == "jm" else "哔咔"
            parts.append(f"{i}. [{src}|{c.get('id','')}] {c.get('title','?')}  作者:{c.get('author','佚名')}")
        parts.append(f"\n回复序号或「禁漫/哔咔|ID」下载。")

    if not parts:
        return "没有找到任何结果。"
    return "\n".join(parts)

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _common_cfg(args: argparse.Namespace, local: dict) -> tuple[str, str]:
    base = config_value(args, local, "api_base", "COMIC_API_BASE", DEFAULT_API_BASE)
    proj = config_value(args, local, "project_dir", "COMIC_API_PROJECT_DIR", DEFAULT_PROJECT_DIR)
    return str(base), str(Path(proj).expanduser())


def cmd_doctor(args: argparse.Namespace, local: dict) -> None:
    base, project_dir = _common_cfg(args, local)
    api_repo = config_value(args, local, "api_repo", "COMIC_API_REPO", DEFAULT_API_REPO)
    running = is_service_running(base)
    pd = Path(project_dir)
    lines = [
        f"API base:      {base}",
        f"Service:       {'[OK] running' if running else '[!!] not running'}",
        f"Auto deploy:   {'enabled' if auto_deploy_enabled(args, local) else 'disabled'}",
        f"API repo:      {api_repo}",
        f"git:           {'found' if shutil.which('git') else 'not found'}",
        f"Project dir:   {project_dir} ({'exists' if pd.exists() else 'not found'})",
        f"main.py:       {'found' if (pd / 'main.py').exists() else 'not found'}",
    ]
    if running:
        # Quick endpoint test
        try:
            r = api_search(base, "test")
            lines.append("Search API:    [OK]")
        except Exception as e:
            lines.append(f"Search API:    [ERROR] {e}")
    print("\n".join(lines))


def cmd_search(args: argparse.Namespace, local: dict) -> None:
    base, project_dir = _common_cfg(args, local)
    ensure_service(base, project_dir, args, local)
    keyword = args.keyword
    result = api_search(base, keyword)
    if getattr(args, "json_out", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    source = normalize_source(getattr(args, "source", "all"))
    limit = getattr(args, "limit", 10)
    print(fmt_search(result, limit=limit, source=source))


def cmd_detail(args: argparse.Namespace, local: dict) -> None:
    base, project_dir = _common_cfg(args, local)
    ensure_service(base, project_dir, args, local)
    source = normalize_source(args.source)
    comic_id = args.comic_id
    detail = api_comic_detail(base, source, comic_id)
    if getattr(args, "json_out", False):
        print(json.dumps(detail, ensure_ascii=False, indent=2))
        return
    title = detail.get("title", "未知")
    author = detail.get("author", "佚名")
    desc = (detail.get("description") or "无描述")[:200]
    chapters = detail.get("chapters", [])
    ch_count = len(chapters)
    src_label = "禁漫" if source == "jm" else "哔咔"
    lines = [
        f"[漫画] {title}",
        f"来源: {src_label} | ID: {comic_id}",
        f"作者: {author}",
        f"简介: {desc}",
        f"章节数: {ch_count}",
    ]
    if chapters:
        first = chapters[0]
        lines.append(f"\n第一话: [{first.get('id','')}] {first.get('name','第1话')}")
        if ch_count > 1:
            lines.append(f"（共 {ch_count} 话，只显示第一话。如需其他话请指定章节 ID）")
    print("\n".join(lines))


def cmd_download(args: argparse.Namespace, local: dict) -> None:
    base, project_dir = _common_cfg(args, local)
    ensure_service(base, project_dir, args, local)

    source = normalize_source(args.source)
    comic_id = args.comic_id
    chapter_id = getattr(args, "chapter", None)
    out_dir = Path(config_value(args, local, "out", "COMIC_API_OUT_DIR", DEFAULT_OUT_DIR)).expanduser()

    # Get comic detail first
    print(f"[comic] 获取漫画详情: {source}/{comic_id} ...", flush=True)
    detail = api_comic_detail(base, source, comic_id)
    title = detail.get("title", comic_id)
    chapters = detail.get("chapters", [])

    if not chapters:
        raise RuntimeError("该漫画没有可下载的章节")

    # If no chapter specified, use first chapter; warn if multiple chapters exist
    first_ch = chapters[0]
    total_chs = len(chapters)

    if chapter_id is None:
        chapter_id = str(first_ch.get("id", ""))
        chapter_name = str(first_ch.get("name", "第1话"))
        if total_chs > 1:
            print(f"[comic] 该漫画共 {total_chs} 话，只下载第一话: 「{chapter_name}」", flush=True)
            print(f"提示: 如需其他话，请指定 --chapter <chapter_id>", flush=True)
            # Print chapter list
            ch_lines = ["章节列表:"]
            for i, ch in enumerate(chapters[:20], 1):
                ch_lines.append(f"  {i}. [{ch.get('id','')}] {ch.get('name', f'第{i}话')}")
            if total_chs > 20:
                ch_lines.append(f"  ... 共 {total_chs} 话")
            print("\n".join(ch_lines), flush=True)
    else:
        # Find chapter name
        chapter_name = chapter_id
        for ch in chapters:
            if str(ch.get("id", "")) == str(chapter_id):
                chapter_name = ch.get("name", chapter_id)
                break

    concurrency = int(config_value(args, local, "concurrency", "COMIC_API_CONCURRENCY", 4))
    zip_paths = download_chapter(
        base, source, comic_id, chapter_id, chapter_name, title, out_dir, concurrency=concurrency
    )

    password = make_password(chapter_id)
    print("\n✅ 下载完成！")
    for zp in zip_paths:
        size_mb = zp.stat().st_size / (1024 * 1024)
        print(f"zip_path={zp}")
        print(f"zip_size={size_mb:.1f}MB")
    print(f"zip_password={password}")
    print(f"comic_title={title}")
    print(f"chapter_name={chapter_name}")
    if total_chs > 1 and not getattr(args, "chapter", None):
        print(f"total_chapters={total_chs}")
        print(f"tip=这是第一话，共 {total_chs} 话，如需其他话请告知章节序号")


def cmd_leaderboard(args: argparse.Namespace, local: dict) -> None:
    base, project_dir = _common_cfg(args, local)
    ensure_service(base, project_dir, args, local)
    source = normalize_source(getattr(args, "source", "jm"))
    mode = getattr(args, "mode", "day")
    page = getattr(args, "page", 1)
    result = api_leaderboard(base, source, mode, page)
    if getattr(args, "json_out", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    comics = result.get("data", [])
    src_label = "禁漫" if source == "jm" else "哔咔"
    mode_map = {"day": "日榜", "week": "周榜", "month": "月榜", "total": "总榜"}
    print(f"[排行] {src_label} {mode_map.get(mode, mode)} (第{page}页):")
    print(fmt_comics(comics, source))


def cmd_category(args: argparse.Namespace, local: dict) -> None:
    base, project_dir = _common_cfg(args, local)
    ensure_service(base, project_dir, args, local)
    source = normalize_source(getattr(args, "source", "jm"))
    name = getattr(args, "name", "doujin")
    page = getattr(args, "page", 1)
    sort_raw = getattr(args, "sort", "") or ""
    sort = sort_raw if sort_raw else ("new" if source == "jm" else "dd")
    result = api_category(base, source, name, page, sort)
    if getattr(args, "json_out", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    comics = result.get("data", [])
    src_label = "禁漫" if source == "jm" else "哔咔"
    sort_map = {
        "new": "最新", "dd": "最新",
        "mv": "最多观看", "vd": "最多观看",
        "tf": "最多喜欢", "ld": "最多喜欢",
        "mp": "最多指名", "da": "最旧",
    }
    sort_label = sort_map.get(sort, sort)
    print(f"[分类] {src_label} 分类「{name}」| {sort_label} (第{page}页):")
    print(fmt_comics(comics, source))


def cmd_latest(args: argparse.Namespace, local: dict) -> None:
    base, project_dir = _common_cfg(args, local)
    ensure_service(base, project_dir, args, local)
    source = normalize_source(getattr(args, "source", "jm"))
    page = getattr(args, "page", 1)
    sort_raw = getattr(args, "sort", "") or ""
    sort = sort_raw if sort_raw else ("new" if source == "jm" else "dd")
    result = api_latest(base, source, page, sort)
    if getattr(args, "json_out", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    comics = result.get("data", [])
    src_label = "禁漫" if source == "jm" else "哔咔"
    sort_map = {
        "new": "最新", "dd": "最新",
        "mv": "最多观看", "vd": "最多观看",
        "tf": "最多喜欢", "ld": "最多喜欢",
        "mp": "最多指名",
    }
    sort_label = sort_map.get(sort, sort)
    print(f"[浏览] {src_label} | {sort_label} (第{page}页):")
    print(fmt_comics(comics, source))


def cmd_random(args: argparse.Namespace, local: dict) -> None:
    base, project_dir = _common_cfg(args, local)
    ensure_service(base, project_dir, args, local)
    source = normalize_source(getattr(args, "source", "jm"))
    result = api_random(base, source)
    if getattr(args, "json_out", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    comics = result.get("data", [])
    if not isinstance(comics, list):
        comics = [comics] if comics else []
    src_label = "禁漫" if source == "jm" else "哔咔"
    print(f"[随机] {src_label} 随机推荐:")
    print(fmt_comics(comics, source))

# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Comic aggregator Koishi skill helper (comic-api)")
    p.add_argument("--api-base", dest="api_base", default="")
    p.add_argument("--project-dir", dest="project_dir", default="")
    p.add_argument("--api-repo", dest="api_repo", default="")
    p.add_argument("--bind-host", dest="bind_host", default="")
    p.add_argument("--start-timeout", dest="start_timeout", default="")
    p.add_argument("--no-auto-deploy", action="store_true")
    p.add_argument("--concurrency", type=int, default=None)

    sub = p.add_subparsers(dest="cmd", required=True)

    # doctor
    sub.add_parser("doctor", help="检查服务和配置状态")

    # search
    s = sub.add_parser("search", help="聚合搜索 (禁漫+哔咔)")
    s.add_argument("keyword")
    s.add_argument("--source", choices=["jm", "bika", "all", "禁漫", "哔咔"], default="all")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--json", dest="json_out", action="store_true")

    # detail
    d = sub.add_parser("detail", help="查看漫画详情和章节列表")
    d.add_argument("source", choices=["jm", "bika", "禁漫", "哔咔"])
    d.add_argument("comic_id")
    d.add_argument("--json", dest="json_out", action="store_true")

    # download
    dl = sub.add_parser("download", help="下载章节为加密 ZIP")
    dl.add_argument("source", choices=["jm", "bika", "禁漫", "哔咔"])
    dl.add_argument("comic_id")
    dl.add_argument("--chapter", default=None, help="章节 ID，不填则下载第一话")
    dl.add_argument("--out", default="")

    # leaderboard
    lb = sub.add_parser("leaderboard", help="排行榜")
    lb.add_argument("--source", choices=["jm", "bika", "禁漫", "哔咔"], default="jm")
    lb.add_argument("--mode", choices=["day", "week", "month", "total"], default="day")
    lb.add_argument("--page", type=int, default=1)
    lb.add_argument("--json", dest="json_out", action="store_true")

    # category
    cat = sub.add_parser("category", help="分类浏览")
    cat.add_argument("--source", choices=["jm", "bika", "禁漫", "哔咔"], default="jm")
    cat.add_argument("--name", default="doujin")
    cat.add_argument("--page", type=int, default=1)
    cat.add_argument("--sort", default="",
                     help="禁漫: new/mv/tf/mp | 哔咔: dd/ld/vd/da (不填则默认最新)")
    cat.add_argument("--json", dest="json_out", action="store_true")

    # latest
    lat = sub.add_parser("latest", help="浏览漫画列表")
    lat.add_argument("--source", choices=["jm", "bika", "禁漫", "哔咔"], default="jm")
    lat.add_argument("--page", type=int, default=1)
    lat.add_argument("--sort", default="",
                     help="禁漫: new/mv/tf/mp | 哔咔: dd/ld/vd/da (不填则默认最新)")
    lat.add_argument("--json", dest="json_out", action="store_true")

    # random
    rnd = sub.add_parser("random", help="随机推荐")
    rnd.add_argument("--source", choices=["jm", "bika", "禁漫", "哔咔"], default="jm")
    rnd.add_argument("--json", dest="json_out", action="store_true")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    local = load_local_config()

    dispatch = {
        "doctor": cmd_doctor,
        "search": cmd_search,
        "detail": cmd_detail,
        "download": cmd_download,
        "leaderboard": cmd_leaderboard,
        "category": cmd_category,
        "latest": cmd_latest,
        "random": cmd_random,
    }
    fn = dispatch.get(args.cmd)
    if fn:
        fn(args, local)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("error=interrupted", file=sys.stderr)
        sys.exit(130)
    except RuntimeError as e:
        print(f"error={e}", file=sys.stderr)
        sys.exit(1)
