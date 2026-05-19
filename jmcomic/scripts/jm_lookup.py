#!/usr/bin/env python3
"""JMComic-Api helper — auto-deploy, search, download encrypted PDF."""

from __future__ import annotations

import argparse
import json
import os
import platform
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
DEFAULT_PROJECT_DIR = str(Path(__file__).resolve().parents[3] / "JMComic-Api")
DEFAULT_OUT_DIR = str(Path(__file__).resolve().parents[1] / "downloads")
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.local.json"
COMPRESS_THRESHOLD_MB = 100


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


def _venv_ready(project_dir: str) -> bool:
    """True if the project venv exists and has uvicorn installed."""
    pd = Path(project_dir)
    # uv creates .venv by default
    uvicorn = pd / ".venv" / ("Scripts" if platform.system() == "Windows" else "bin") / (
        "uvicorn.exe" if platform.system() == "Windows" else "uvicorn"
    )
    return uvicorn.exists()


def start_service(project_dir: str, base: str) -> None:
    pd = Path(project_dir)
    if not pd.exists():
        raise RuntimeError(f"JMComic-Api project not found at {project_dir}")

    uv = _find_uv()
    if uv is None:
        raise RuntimeError("uv is not installed — see https://github.com/astral-sh/uv")

    # Only install if venv isn't ready yet (first-time setup only)
    if not _venv_ready(project_dir):
        print("[jm] First-time setup: installing dependencies ...", flush=True)
        subprocess.run(
            [uv, "sync", "--no-dev"],
            cwd=project_dir,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        print("[jm] Venv ready, skipping install.", flush=True)

    port_match = re.search(r":(\d+)$", base)
    port = port_match.group(1) if port_match else "8699"

    # Launch uvicorn directly from the venv — avoids uv run overhead
    venv_bin = pd / ".venv" / ("Scripts" if platform.system() == "Windows" else "bin")
    uvicorn_exe = venv_bin / ("uvicorn.exe" if platform.system() == "Windows" else "uvicorn")

    kwargs: dict = dict(cwd=project_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if platform.system() == "Windows":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True

    subprocess.Popen(
        [str(uvicorn_exe), "jmcomic_api.app:app", "--host", "0.0.0.0", "--port", port],
        **kwargs,
    )

    print("[jm] Waiting for service ...", flush=True)
    for _ in range(30):
        time.sleep(1)
        if is_service_running(base):
            print("[jm] Service is up.", flush=True)
            return
    raise RuntimeError("Service did not start within 30 s — check JMComic-Api logs.")


def ensure_service(base: str, project_dir: str) -> None:
    if is_service_running(base):
        return
    print(f"[jm] Service not running, starting ...", flush=True)
    start_service(project_dir, base)


# ---------------------------------------------------------------------------
# Ghostscript compression
# ---------------------------------------------------------------------------

def _find_gs() -> str | None:
    return shutil.which("gs")


def compress_pdf(pdf_path: Path, threshold_mb: int = COMPRESS_THRESHOLD_MB) -> Path:
    """Compress with Ghostscript if file exceeds threshold. Returns path (may be same file)."""
    size_mb = pdf_path.stat().st_size / (1024 * 1024)
    if size_mb <= threshold_mb:
        return pdf_path

    gs = _find_gs()
    if not gs:
        print(f"[jm] File is {size_mb:.1f} MB but Ghostscript not found, skipping compression.", flush=True)
        return pdf_path

    print(f"[jm] Compressing {size_mb:.1f} MB PDF with Ghostscript ...", flush=True)
    out = pdf_path.with_suffix(".compressed.pdf")
    result = subprocess.run(
        [
            gs, "-q", "-dNOPAUSE", "-dBATCH",
            "-sDEVICE=pdfwrite",
            "-dPDFSETTINGS=/ebook",   # ~150 DPI, good quality/size balance
            "-dCompatibilityLevel=1.4",
            f"-sOutputFile={out}",
            str(pdf_path),
        ],
        capture_output=True,
    )
    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        print("[jm] Ghostscript compression failed, using original.", flush=True)
        out.unlink(missing_ok=True)
        return pdf_path

    new_mb = out.stat().st_size / (1024 * 1024)
    print(f"[jm] Compressed: {size_mb:.1f} MB → {new_mb:.1f} MB", flush=True)
    pdf_path.unlink()
    out.rename(pdf_path)
    return pdf_path


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def search(base: str, query: str, page: int = 1) -> list[dict]:
    url = api_url(base, f"/search?query={urllib.request.quote(query)}&page={page}")
    r = _get(url)
    if not r.get("success"):
        raise RuntimeError(r.get("message", "search failed"))
    return r["data"]["results"]


def categories(base: str, order_by: str = "day_rank", page: int = 1) -> list[dict]:
    url = api_url(base, f"/categories?order_by={order_by}&page={page}")
    r = _get(url)
    if not r.get("success"):
        raise RuntimeError(r.get("message", "categories failed"))
    return r["data"]["results"]


def random_album(base: str, *, keywords: tuple[str, ...] = (), rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    results = search(base, rng.choice(keywords)) if keywords else categories(base, order_by="day_rank")
    if not results:
        raise RuntimeError("No albums returned for random pick")
    return rng.choice(results)


def get_pdf(base: str, album_id: str, out_dir: Path, timeout: int = 900) -> Path:
    """Download API-encrypted PDF (password = album_id)."""
    clean = album_id.removeprefix("JM").removeprefix("jm")
    # passwd=true → API encrypts with album_id as password
    url = api_url(base, f"/get_pdf/{clean}?pdf=true&passwd=true&Titletype=2")
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f"_tmp_{clean}_{int(time.time())}.pdf"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
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
    pd = Path(project_dir)
    gs = _find_gs()
    lines = [
        f"API base:      {base}",
        f"Service:       {'running ✓' if is_service_running(base) else 'not running ✗'}",
        f"uv:            {'found ✓' if _find_uv() else 'not found ✗'}",
        f"Project dir:   {project_dir} ({'exists ✓' if pd.exists() else 'not found ✗'})",
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
    print(f"[jm] Downloading [{clean}] ...", flush=True)
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
    keywords: tuple[str, ...] = tuple(k.strip() for k in kw_str.split(",") if k.strip()) if kw_str else ()

    album = random_album(base, keywords=keywords)
    album_id = str(album["id"]).removeprefix("JM").removeprefix("jm")
    print(f"[jm] Random pick: [{album_id}] {album['title']}", flush=True)
    _download_and_output(base, album_id, out_dir)


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

    dispatch = {
        "doctor": cmd_doctor,
        "search": cmd_search,
        "get": cmd_get,
        "random": cmd_random,
    }
    fn = dispatch.get(args.cmd)
    if fn:
        fn(args, local)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
