#!/usr/bin/env python3
"""JMComic-Api helper — targets FfmpegZZZ/JMComic-Api."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_API_BASE = "http://127.0.0.1:8699"
# Assumes JMComic-Api lives next to koishi-skills under the same parent dir
DEFAULT_PROJECT_DIR = str(Path(__file__).resolve().parents[3] / "JMComic-Api")
DEFAULT_OUT_DIR = str(Path(__file__).resolve().parents[1] / "downloads")
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.local.json"
COMPRESS_THRESHOLD_MB = 100
JMCOMIC_API_REPO = "https://github.com/FfmpegZZZ/JMComic-Api.git"


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
# HTTP helpers
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


def _get_binary(url: str, dest: Path, timeout: int = 900) -> Path:
    tmp = dest.with_suffix(".tmp")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            with open(tmp, "wb") as f:
                shutil.copyfileobj(resp, f)
        tmp.rename(dest)
        return dest
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Service management
# ---------------------------------------------------------------------------

def is_service_running(base: str) -> bool:
    # FfmpegZZZ has no /health — probe with a lightweight download/image call.
    # code=200 means the service is up (album may not exist, that's fine).
    try:
        url = api_url(base, "/download/image?jm_id=1")
        with urllib.request.urlopen(url, timeout=3) as r:
            data = json.loads(r.read().decode())
            return isinstance(data, dict) and data.get("code") == 200
    except Exception:
        return False


def _venv_ready(project_dir: str) -> bool:
    uvicorn = Path(project_dir) / ".venv" / "bin" / "uvicorn"
    return uvicorn.exists()


def start_service(project_dir: str, base: str) -> None:
    pd = Path(project_dir)

    git = shutil.which("git")
    if not pd.exists():
        if git is None:
            raise RuntimeError("git is not installed — cannot auto-deploy JMComic-Api")
        print(f"[jm] Cloning FfmpegZZZ/JMComic-Api into {project_dir} ...", flush=True)
        pd.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([git, "clone", JMCOMIC_API_REPO, str(pd)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is not installed — see https://github.com/astral-sh/uv")

    if not _venv_ready(project_dir):
        print("[jm] First-time setup: installing dependencies ...", flush=True)
        subprocess.run([uv, "sync", "--no-dev"], cwd=project_dir, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    port_match = re.search(r":(\d+)$", base)
    port = port_match.group(1) if port_match else "8699"

    python = pd / ".venv" / "bin" / "python3"
    subprocess.Popen(
        [str(python), "-m", "jmcomic_api"],
        cwd=project_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    print("[jm] Waiting for service ...", flush=True)
    for _ in range(30):
        time.sleep(1)
        if is_service_running(base):
            print("[jm] Service is up.", flush=True)
            return
    raise RuntimeError("Service did not start within 30 s.")


def ensure_service(base: str, project_dir: str) -> None:
    if is_service_running(base):
        return
    print("[jm] Service not running, starting ...", flush=True)
    start_service(project_dir, base)


# ---------------------------------------------------------------------------
# Ghostscript compression
# ---------------------------------------------------------------------------

def _find_gs() -> str | None:
    return shutil.which("gs")


def compress_pdf(pdf_path: Path, threshold_mb: int = COMPRESS_THRESHOLD_MB) -> Path:
    size_mb = pdf_path.stat().st_size / (1024 * 1024)
    if size_mb <= threshold_mb:
        return pdf_path
    gs = _find_gs()
    if not gs:
        print(f"[jm] {size_mb:.1f} MB but Ghostscript not found, skipping compression.", flush=True)
        return pdf_path
    print(f"[jm] Compressing {size_mb:.1f} MB with Ghostscript ...", flush=True)
    out = pdf_path.with_suffix(".compressed.pdf")
    result = subprocess.run(
        [gs, "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite",
         "-dPDFSETTINGS=/ebook", "-dCompatibilityLevel=1.4",
         f"-sOutputFile={out}", str(pdf_path)],
        capture_output=True,
    )
    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        print("[jm] Compression failed, using original.", flush=True)
        return pdf_path
    new_mb = out.stat().st_size / (1024 * 1024)
    print(f"[jm] Compressed: {size_mb:.1f} MB → {new_mb:.1f} MB", flush=True)
    pdf_path.unlink()
    out.rename(pdf_path)
    return pdf_path


# ---------------------------------------------------------------------------
# FfmpegZZZ API calls
# ---------------------------------------------------------------------------

def trigger_download(base: str, album_id: str, timeout: int = 900) -> None:
    """Trigger server-side image download. Blocks until images are ready."""
    url = api_url(base, f"/download/image?jm_id={album_id}")
    print(f"[jm] Triggering download for {album_id} ...", flush=True)
    r = _get(url, timeout=timeout)
    if r.get("code") != 200:
        raise RuntimeError(f"download/image failed: {r}")


def get_pdf(base: str, album_id: str, out_dir: Path, timeout: int = 900) -> Path:
    """Fetch encrypted PDF (password = album_id)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{album_id}.pdf"
    url = api_url(
        base,
        f"/get/file?jm_id={album_id}&file_type=pdf"
        f"&file_pwd={album_id}&return_method=from-data",
    )
    print(f"[jm] Downloading PDF for {album_id} ...", flush=True)
    return _get_binary(url, dest, timeout=timeout)


def search(base: str, query: str, page: int = 1) -> list[dict]:
    url = api_url(base, f"/get/raw/search?search_query={urllib.request.quote(query)}&page={page}")
    r = _get(url)
    # Response shape: {"code":200, "data": {"content": [{"id":..., "name":...}, ...]}}
    if r.get("code") != 200:
        raise RuntimeError(f"search failed: {r}")
    items = r.get("data", {}).get("content", [])
    return [{"id": str(item["id"]), "title": item.get("name", "")} for item in items]


def random_album(base: str, *, keywords: tuple[str, ...] = (), rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    if keywords:
        results = search(base, rng.choice(keywords))
    else:
        # Fallback: use search with a popular keyword
        results = search(base, "全彩")
    if not results:
        raise RuntimeError("No albums returned for random pick")
    return rng.choice(results)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_doctor(args: argparse.Namespace, local: dict) -> None:
    base = config_value(args, local, "api_base", "JMAPI_BASE", DEFAULT_API_BASE)
    project_dir = config_value(args, local, "project_dir", "JMAPI_PROJECT_DIR", DEFAULT_PROJECT_DIR)
    gs = _find_gs()
    pd = Path(project_dir)
    lines = [
        f"API base:      {base}",
        f"Service:       {'running ✓' if is_service_running(base) else 'not running ✗'}",
        f"git:           {'found ✓' if shutil.which('git') else 'not found ✗'}",
        f"uv:            {'found ✓' if shutil.which('uv') else 'not found ✗'}",
        f"Project dir:   {project_dir} ({'exists ✓' if pd.exists() else 'not found (will auto-clone)'})",
        f"Venv ready:    {'yes ✓' if _venv_ready(project_dir) else 'no (first run will install)'}",
        f"Ghostscript:   {gs + ' ✓' if gs else 'not found (compression disabled)'}",
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
    lines.append(f"\n你要哪一本？回复 1-{len(results)} 的序号或直接回复 JM 号。")
    print("\n".join(lines))


def _download_and_output(base: str, album_id: str, out_dir: Path) -> None:
    clean = album_id.removeprefix("JM").removeprefix("jm")
    trigger_download(base, clean)
    pdf_path = get_pdf(base, clean, out_dir)
    pdf_path = compress_pdf(pdf_path)
    print(f"pdf_path={pdf_path}")
    print(f"pdf_password={clean}")
    print(f"album_id={clean}")
    print(f"filename={pdf_path.name}")


def cmd_get(args: argparse.Namespace, local: dict) -> None:
    base = config_value(args, local, "api_base", "JMAPI_BASE", DEFAULT_API_BASE)
    project_dir = config_value(args, local, "project_dir", "JMAPI_PROJECT_DIR", DEFAULT_PROJECT_DIR)
    out_dir = Path(config_value(args, local, "out", "JMAPI_OUT_DIR", DEFAULT_OUT_DIR))
    ensure_service(base, project_dir)
    _download_and_output(base, args.album_id, out_dir)


def cmd_random(args: argparse.Namespace, local: dict) -> None:
    base = config_value(args, local, "api_base", "JMAPI_BASE", DEFAULT_API_BASE)
    project_dir = config_value(args, local, "project_dir", "JMAPI_PROJECT_DIR", DEFAULT_PROJECT_DIR)
    out_dir = Path(config_value(args, local, "out", "JMAPI_OUT_DIR", DEFAULT_OUT_DIR))
    ensure_service(base, project_dir)
    kw_str = config_value(args, local, "random_keywords", "JMAPI_RANDOM_KEYWORDS", "")
    keywords = tuple(k.strip() for k in kw_str.split(",") if k.strip()) if kw_str else ()
    album = random_album(base, keywords=keywords)
    print(f"[jm] Random pick: [{album['id']}] {album['title']}", flush=True)
    _download_and_output(base, album["id"], out_dir)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="JMComic-Api helper (FfmpegZZZ)")
    p.add_argument("--api-base", dest="api_base", default="")
    p.add_argument("--project-dir", dest="project_dir", default="")

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="Check config & service status")

    s = sub.add_parser("search", help="Search albums")
    s.add_argument("query")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--json", dest="json_out", action="store_true")

    g = sub.add_parser("get", help="Download album as encrypted PDF")
    g.add_argument("album_id")
    g.add_argument("--out", default="")

    r = sub.add_parser("random", help="Pick and download a random album")
    r.add_argument("--out", default="")
    r.add_argument("--keywords", dest="random_keywords", default="")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    local = load_local_config()
    dispatch = {"doctor": cmd_doctor, "search": cmd_search, "get": cmd_get, "random": cmd_random}
    fn = dispatch.get(args.cmd)
    if fn:
        fn(args, local)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
