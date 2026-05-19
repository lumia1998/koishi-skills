#!/usr/bin/env python3
"""JMComic-Api helper — auto-deploy, search, download, zip."""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import re
import secrets
import shutil
import string
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_API_BASE = "http://127.0.0.1:8699"
DEFAULT_PROJECT_DIR = str(Path(__file__).resolve().parents[3] / "JMComic-Api")
DEFAULT_OUT_DIR = str(Path(__file__).resolve().parents[1] / "downloads")
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.local.json"

CRC_TABLE: list[int] | None = None


def load_local_config(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else CONFIG_PATH
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"config read failed: {p}") from e
    if not isinstance(data, dict):
        raise RuntimeError("config.local.json must be a JSON object")
    return data


def config_value(args: argparse.Namespace, local: dict, attr: str, env: str, default: Any) -> Any:
    v = getattr(args, attr, None)
    if v is not None and v != "":
        return v
    v = os.environ.get(env, "")
    if v:
        return v
    return local.get(attr, default)


# ---------------------------------------------------------------------------
# Encrypted ZIP (stdlib-only, same algorithm as pica skill)
# ---------------------------------------------------------------------------

def _crc_table() -> list[int]:
    global CRC_TABLE
    if CRC_TABLE is None:
        table = []
        for v in range(256):
            crc = v
            for _ in range(8):
                crc = ((crc >> 1) ^ 0xEDB88320) if (crc & 1) else (crc >> 1)
            table.append(crc & 0xFFFFFFFF)
        CRC_TABLE = table
    return CRC_TABLE


def _crc32b(val: int, byte: int) -> int:
    t = _crc_table()
    return ((val >> 8) ^ t[(val ^ byte) & 0xFF]) & 0xFFFFFFFF


def _zip_keys(password: bytes) -> list[int]:
    keys = [0x12345678, 0x23456789, 0x34567890]
    for b in password:
        _update_keys(keys, b)
    return keys


def _update_keys(keys: list[int], b: int) -> None:
    keys[0] = _crc32b(keys[0], b)
    keys[1] = (keys[1] + (keys[0] & 0xFF)) & 0xFFFFFFFF
    keys[1] = (keys[1] * 134775813 + 1) & 0xFFFFFFFF
    keys[2] = _crc32b(keys[2], (keys[1] >> 24) & 0xFF)


def _xbyte(keys: list[int], b: int) -> int:
    t = (keys[2] | 2) & 0xFFFFFFFF
    out = b ^ (((t * (t ^ 1)) >> 8) & 0xFF)
    _update_keys(keys, b)
    return out


def _encrypt(data: bytes, password: bytes, crc: int) -> bytes:
    keys = _zip_keys(password)
    hdr = bytearray([0] * 11 + [(crc >> 24) & 0xFF])
    out = bytearray()
    for b in hdr:
        out.append(_xbyte(keys, b))
    for b in data:
        out.append(_xbyte(keys, b))
    return bytes(out)


def _dos_dt(ts: float | None = None) -> tuple[int, int]:
    lt = time.localtime(ts or time.time())
    return (
        (lt.tm_hour << 11) | (lt.tm_min << 5) | (lt.tm_sec // 2),
        ((lt.tm_year - 1980) << 9) | (lt.tm_mon << 5) | lt.tm_mday,
    )


def _make_record(name: str, data: bytes, pw: str, offset: int) -> tuple[bytes, bytes]:
    nb = name.encode("utf-8")
    crc = zlib.crc32(data) & 0xFFFFFFFF
    co = zlib.compressobj(level=6, method=zlib.DEFLATED, wbits=-15)
    compressed = co.compress(data) + co.flush()
    enc = _encrypt(compressed, pw.encode(), crc)
    t, d = _dos_dt()
    lh = (
        b"PK\x03\x04"
        + (20).to_bytes(2, "little")
        + (0x1 | 0x800).to_bytes(2, "little")
        + (8).to_bytes(2, "little")
        + t.to_bytes(2, "little")
        + d.to_bytes(2, "little")
        + crc.to_bytes(4, "little")
        + len(enc).to_bytes(4, "little")
        + len(data).to_bytes(4, "little")
        + len(nb).to_bytes(2, "little")
        + (0).to_bytes(2, "little")
        + nb
    )
    ch = (
        b"PK\x01\x02"
        + (20).to_bytes(2, "little") * 2
        + (0x1 | 0x800).to_bytes(2, "little")
        + (8).to_bytes(2, "little")
        + t.to_bytes(2, "little")
        + d.to_bytes(2, "little")
        + crc.to_bytes(4, "little")
        + len(enc).to_bytes(4, "little")
        + len(data).to_bytes(4, "little")
        + len(nb).to_bytes(2, "little")
        + (0).to_bytes(2, "little") * 4
        + offset.to_bytes(4, "little")
        + nb
    )
    return lh + enc, ch


def create_encrypted_zip(files: list[Path], out: Path, password: str) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    records: list[bytes] = []
    centrals: list[bytes] = []
    offset = 0
    for f in sorted(files, key=lambda p: p.name):
        rec, cen = _make_record(f.name, f.read_bytes(), password, offset)
        records.append(rec)
        centrals.append(cen)
        offset += len(rec)
    cd = b"".join(centrals)
    eocd = (
        b"PK\x05\x06"
        + (0).to_bytes(2, "little") * 2
        + len(records).to_bytes(2, "little") * 2
        + len(cd).to_bytes(4, "little")
        + offset.to_bytes(4, "little")
        + (0).to_bytes(2, "little")
    )
    out.write_bytes(b"".join(records) + cd + eocd)
    return out


def random_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ---------------------------------------------------------------------------
# Service management
# ---------------------------------------------------------------------------

def api_url(base: str, path: str) -> str:
    return base.rstrip("/") + path


def _get(url: str, timeout: int = 15) -> Any:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body}") from e


def is_service_running(base: str) -> bool:
    try:
        r = _get(api_url(base, "/health"), timeout=3)
        return isinstance(r, dict) and r.get("status") in ("ok", "healthy", True, "up")
    except Exception:
        return False


def _find_uv() -> str | None:
    return shutil.which("uv")


def start_service(project_dir: str, base: str) -> None:
    """Start uvicorn in background, wait up to 30 s."""
    pd = Path(project_dir)
    if not pd.exists():
        raise RuntimeError(f"JMComic-Api project not found at {project_dir}")

    uv = _find_uv()
    if uv is None:
        raise RuntimeError("uv is not installed — install from https://github.com/astral-sh/uv")

    # Ensure venv + deps
    print(f"[jm] Installing dependencies in {project_dir} ...", flush=True)
    subprocess.run(
        [uv, "pip", "install", "-e", ".[dev]"],
        cwd=project_dir,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    port_match = re.search(r":(\d+)$", base)
    port = port_match.group(1) if port_match else "8699"

    kwargs: dict = dict(
        cwd=project_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if platform.system() == "Windows":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True

    subprocess.Popen(
        [uv, "run", "uvicorn", "jmcomic_api.app:app", "--host", "0.0.0.0", "--port", port],
        **kwargs,
    )

    print("[jm] Waiting for service to start ...", flush=True)
    for _ in range(30):
        time.sleep(1)
        if is_service_running(base):
            print("[jm] Service is up.", flush=True)
            return
    raise RuntimeError("Service did not start within 30 seconds — check JMComic-Api logs.")


def ensure_service(base: str, project_dir: str) -> None:
    if is_service_running(base):
        return
    print(f"[jm] Service not running at {base}, auto-deploying ...", flush=True)
    start_service(project_dir, base)


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def search(base: str, query: str, page: int = 1) -> list[dict]:
    url = api_url(base, f"/search?query={urllib.request.quote(query)}&page={page}")
    r = _get(url)
    if not r.get("success"):
        raise RuntimeError(r.get("message", "search failed"))
    return r["data"]["results"]  # list of {id, title}


def categories(base: str, order_by: str = "day_rank", page: int = 1) -> list[dict]:
    url = api_url(base, f"/categories?order_by={order_by}&page={page}")
    r = _get(url)
    if not r.get("success"):
        raise RuntimeError(r.get("message", "categories failed"))
    return r["data"]["results"]


def random_album(
    base: str,
    *,
    keywords: tuple[str, ...] = (),
    rng: random.Random | None = None,
) -> dict:
    """Pick a random album. If keywords provided, search one at random; else use day_rank."""
    rng = rng or random.Random()
    if keywords:
        kw = rng.choice(keywords)
        results = search(base, kw)
    else:
        results = categories(base, order_by="day_rank")
    if not results:
        raise RuntimeError("No albums returned for random pick")
    return rng.choice(results)


def get_pdf(base: str, album_id: str, out_dir: Path, timeout: int = 900) -> Path:
    """Stream the PDF from the API to a local file."""
    clean = album_id.removeprefix("JM").removeprefix("jm")
    url = api_url(base, f"/get_pdf/{clean}?pdf=true&passwd=false&Titletype=2")
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f"_tmp_{clean}_{int(time.time())}.pdf"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cd = resp.headers.get("Content-Disposition", "")
            m = re.search(r'filename="([^"]+)"', cd)
            fname = m.group(1) if m else f"{clean}.pdf"
            dest = out_dir / fname
            with open(tmp, "wb") as f:
                shutil.copyfileobj(resp, f)
        tmp.rename(dest)
        return dest
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_doctor(args: argparse.Namespace, local: dict) -> None:
    base = config_value(args, local, "api_base", "JMAPI_BASE", DEFAULT_API_BASE)
    project_dir = config_value(args, local, "project_dir", "JMAPI_PROJECT_DIR", DEFAULT_PROJECT_DIR)
    running = is_service_running(base)
    uv = _find_uv()
    pd = Path(project_dir)
    lines = [
        f"API base:      {base}",
        f"Service:       {'running ✓' if running else 'not running ✗'}",
        f"uv:            {'found ✓' if uv else 'not found ✗'}",
        f"Project dir:   {project_dir} ({'exists ✓' if pd.exists() else 'not found ✗'})",
    ]
    print("\n".join(lines))


def cmd_search(args: argparse.Namespace, local: dict) -> None:
    base = config_value(args, local, "api_base", "JMAPI_BASE", DEFAULT_API_BASE)
    project_dir = config_value(args, local, "project_dir", "JMAPI_PROJECT_DIR", DEFAULT_PROJECT_DIR)
    ensure_service(base, project_dir)
    results = search(base, args.query, getattr(args, "page", 1))
    if not results:
        print("没有找到相关结果，换个关键词试试？")
        return
    limit = getattr(args, "limit", 10)
    results = results[:limit]
    if getattr(args, "json_out", False):
        print(json.dumps(results, ensure_ascii=False))
        return
    lines = [f"找到 {len(results)} 个结果：\n"]
    for i, item in enumerate(results, 1):
        lines.append(f"{i}. [{item['id']}] {item['title']}")
    lines.append("\n你要哪一本？可以回复序号或 JM 号。")
    print("\n".join(lines))


def cmd_random(args: argparse.Namespace, local: dict) -> None:
    base = config_value(args, local, "api_base", "JMAPI_BASE", DEFAULT_API_BASE)
    project_dir = config_value(args, local, "project_dir", "JMAPI_PROJECT_DIR", DEFAULT_PROJECT_DIR)
    out_dir = Path(config_value(args, local, "out", "JMAPI_OUT_DIR", DEFAULT_OUT_DIR))
    ensure_service(base, project_dir)

    kw_str = config_value(args, local, "random_keywords", "JMAPI_RANDOM_KEYWORDS", "")
    if kw_str:
        keywords: tuple[str, ...] = tuple(k.strip() for k in kw_str.split(",") if k.strip())
    else:
        keywords = ()

    album = random_album(base, keywords=keywords)
    album_id = str(album["id"]).removeprefix("JM").removeprefix("jm")
    print(f"[jm] Random pick: [{album_id}] {album['title']}", flush=True)
    print(f"[jm] Downloading album {album_id} as PDF ...", flush=True)
    pdf_path = get_pdf(base, album_id, out_dir)

    pw = random_password()
    zip_name = pdf_path.stem + f"_{int(time.time())}.zip"
    zip_path = out_dir / zip_name
    print("[jm] Packing into encrypted ZIP ...", flush=True)
    create_encrypted_zip([pdf_path], zip_path, pw)
    pdf_path.unlink(missing_ok=True)

    print(f"zip_path={zip_path}")
    print(f"zip_password={pw}")
    print(f"album_id={album_id}")
    print(f"album_title={album['title']}")
    print(f"filename={zip_path.name}")


def cmd_zip(args: argparse.Namespace, local: dict) -> None:
    base = config_value(args, local, "api_base", "JMAPI_BASE", DEFAULT_API_BASE)
    project_dir = config_value(args, local, "project_dir", "JMAPI_PROJECT_DIR", DEFAULT_PROJECT_DIR)
    out_dir = Path(config_value(args, local, "out", "JMAPI_OUT_DIR", DEFAULT_OUT_DIR))
    ensure_service(base, project_dir)

    album_id = args.album_id.removeprefix("JM").removeprefix("jm")
    print(f"[jm] Downloading album {album_id} as PDF ...", flush=True)
    pdf_path = get_pdf(base, album_id, out_dir)

    pw = random_password()
    zip_name = pdf_path.stem + f"_{int(time.time())}.zip"
    zip_path = out_dir / zip_name
    print("[jm] Packing into encrypted ZIP ...", flush=True)
    create_encrypted_zip([pdf_path], zip_path, pw)
    pdf_path.unlink(missing_ok=True)

    print(f"zip_path={zip_path}")
    print(f"zip_password={pw}")
    print(f"album_id={album_id}")
    print(f"filename={zip_path.name}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="JMComic-Api helper")
    p.add_argument("--api-base", dest="api_base", default="")
    p.add_argument("--project-dir", dest="project_dir", default="")

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="Check config & service status")

    s = sub.add_parser("search", help="Search albums")
    s.add_argument("query")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--json", dest="json_out", action="store_true")

    r = sub.add_parser("random", help="Pick and download a random album")
    r.add_argument("--out", default="")
    r.add_argument("--keywords", dest="random_keywords", default="",
                   help="Comma-separated keyword pool (overrides config)")

    z = sub.add_parser("zip", help="Download album and pack as encrypted zip")
    z.add_argument("album_id")
    z.add_argument("--out", default="")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    local = load_local_config()

    if args.cmd == "doctor":
        cmd_doctor(args, local)
    elif args.cmd == "search":
        cmd_search(args, local)
    elif args.cmd == "random":
        cmd_random(args, local)
    elif args.cmd == "zip":
        cmd_zip(args, local)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
