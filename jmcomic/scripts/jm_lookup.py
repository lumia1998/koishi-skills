#!/usr/bin/env python3
"""JMComic-Api helper for the FastAPI rewrite.

The helper keeps bot-side logic small: it can deploy the API on the host with
uv when the local service is missing, then talks to the FastAPI endpoints.
"""

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
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_API_BASE = "http://127.0.0.1:8699"
# Assumes JMComic-Api lives next to koishi-skills under the same parent dir.
DEFAULT_PROJECT_DIR = str(Path(__file__).resolve().parents[3] / "JMComic-Api")
DEFAULT_OUT_DIR = str(Path(__file__).resolve().parents[1] / "downloads")
DEFAULT_API_REPO = "https://github.com/FfmpegZZZ/JMComic-Api"
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_START_TIMEOUT = 60

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.local.json"
COMPRESS_THRESHOLD_MB = 100
FASTAPI_ENTRY = Path("src") / "jmcomic_api" / "__main__.py"


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


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def auto_deploy_enabled(args: argparse.Namespace, local: dict) -> bool:
    if getattr(args, "no_auto_deploy", False):
        return False
    if "JMAPI_AUTO_DEPLOY" in os.environ:
        return _as_bool(os.environ.get("JMAPI_AUTO_DEPLOY"), default=True)
    if "auto_deploy" in local:
        return _as_bool(local.get("auto_deploy"), default=True)
    return True


def clean_album_id(raw: str) -> str:
    album_id = raw.strip()
    if not album_id:
        raise RuntimeError("album id is empty")
    prefixed = re.search(
        r"(?:jmid|jm\s*id|jm号|jm|禁漫)\s*[:：#-]?\s*(\d+)",
        album_id,
        flags=re.IGNORECASE,
    )
    if prefixed:
        return prefixed.group(1)
    digits = re.search(r"\d+", album_id)
    if digits:
        return digits.group(0)
    return album_id


def expand_path(value: Any) -> str:
    return str(Path(str(value)).expanduser())


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
        message = payload.get("message") or payload.get("detail") or body
    except Exception:
        message = body
    return RuntimeError(f"HTTP {e.code}: {message}")


def _get_json(url: str, timeout: int = 15) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise _http_error(e) from e


def _filename_from_response(resp: Any, fallback: str) -> str:
    header = resp.headers.get("Content-Disposition", "")
    filename = ""
    m = re.search(r"filename\*=utf-8''([^;]+)", header, flags=re.IGNORECASE)
    if m:
        filename = urllib.parse.unquote(m.group(1))
    else:
        m = re.search(r'filename="?([^";]+)"?', header, flags=re.IGNORECASE)
        if m:
            filename = m.group(1)

    filename = Path(filename or fallback).name
    filename = re.sub(r"[\x00-\x1f\x7f]", "", filename).strip()
    return filename or fallback


def _download_binary(url: str, out_dir: Path, fallback_filename: str, timeout: int = 900) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            filename = _filename_from_response(resp, fallback_filename)
            dest = out_dir / filename
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            with open(tmp, "wb") as f:
                shutil.copyfileobj(resp, f)
            tmp.replace(dest)
            return dest
    except urllib.error.HTTPError as e:
        raise _http_error(e) from e
    except Exception:
        tmp_path = out_dir / (fallback_filename + ".tmp")
        tmp_path.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Service management (host local, no Docker)
# ---------------------------------------------------------------------------

def is_service_running(base: str) -> bool:
    try:
        data = _get_json(api_url(base, "/health/live"), timeout=3)
        return isinstance(data, dict) and data.get("status") == "ok"
    except Exception:
        return False


def _readiness_status(base: str) -> str:
    try:
        data = _get_json(api_url(base, "/health/ready"), timeout=3)
        if isinstance(data, dict):
            return str(data.get("status", "unknown"))
    except Exception:
        pass
    return "unknown"


def _venv_python(project_dir: str) -> Path:
    pd = Path(project_dir)
    if os.name == "nt":
        return pd / ".venv" / "Scripts" / "python.exe"
    return pd / ".venv" / "bin" / "python"


def _venv_ready(project_dir: str) -> bool:
    python = _venv_python(project_dir)
    return python.exists() and (Path(project_dir) / ".venv" / "pyvenv.cfg").exists()


def _runtime_ready(project_dir: str) -> bool:
    python = _venv_python(project_dir)
    if not python.exists():
        return False
    result = subprocess.run(
        [str(python), "-c", "import jmcomic_api"],
        cwd=project_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _run_checked(cmd: list[str], *, cwd: str | Path | None = None, label: str) -> None:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout or "").strip()[-1600:]
    raise RuntimeError(f"{label} failed" + (f": {detail}" if detail else ""))


def _ensure_project(project_dir: str, api_repo: str, api_ref: str = "") -> None:
    pd = Path(project_dir)
    if pd.exists():
        if not _is_fastapi_project(pd):
            raise RuntimeError(
                f"project dir is not the FastAPI JMComic-Api rewrite: {project_dir}"
            )
        return

    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is not installed; cannot auto-clone JMComic-Api")

    print(f"[jm] Cloning JMComic-Api into {project_dir} ...", flush=True)
    pd.parent.mkdir(parents=True, exist_ok=True)
    _run_checked([git, "clone", api_repo, str(pd)], label="git clone")
    if api_ref:
        _run_checked([git, "checkout", api_ref], cwd=pd, label="git checkout")
    if not _is_fastapi_project(pd):
        raise RuntimeError(
            "cloned repository is not the FastAPI JMComic-Api rewrite; "
            "set JMAPI_REPO/JMAPI_REF to the updated API repo"
        )


def _is_fastapi_project(project_dir: Path) -> bool:
    pyproject = project_dir / "pyproject.toml"
    entry = project_dir / FASTAPI_ENTRY
    if not pyproject.exists() or not entry.exists():
        return False
    try:
        text = pyproject.read_text(encoding="utf-8")
    except Exception:
        return False
    return 'name = "jmcomic-api"' in text and "jmcomic_api.__main__:main" in text


def _ensure_runtime(project_dir: str) -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is not installed; install uv first: https://docs.astral.sh/uv/")
    if _runtime_ready(project_dir):
        return
    print("[jm] First-time host setup: uv sync --no-dev ...", flush=True)
    _run_checked([uv, "sync", "--no-dev"], cwd=project_dir, label="uv sync")


def _port_from_base(base: str) -> int:
    parsed = urllib.parse.urlparse(base)
    return parsed.port or 8699


def start_service(
    project_dir: str,
    base: str,
    *,
    api_repo: str,
    api_ref: str = "",
    bind_host: str = DEFAULT_BIND_HOST,
    start_timeout: int = DEFAULT_START_TIMEOUT,
) -> None:
    _ensure_project(project_dir, api_repo, api_ref)
    _ensure_runtime(project_dir)

    pd = Path(project_dir)
    python = _venv_python(project_dir)
    port = str(_port_from_base(base))
    env = os.environ.copy()
    env["JMAPI_HOST"] = bind_host
    env["JMAPI_PORT"] = port

    log_path = pd / "jmcomic-api.log"
    print(f"[jm] Starting JMComic-Api on {bind_host}:{port} ...", flush=True)

    creationflags = 0
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        popen_kwargs["start_new_session"] = True

    with open(log_path, "ab") as log:
        subprocess.Popen(
            [str(python), "-m", "jmcomic_api"],
            cwd=project_dir,
            stdout=log,
            stderr=log,
            env=env,
            creationflags=creationflags,
            **popen_kwargs,
        )

    print("[jm] Waiting for service ...", flush=True)
    deadline = time.monotonic() + start_timeout
    while time.monotonic() < deadline:
        time.sleep(1)
        if is_service_running(base):
            print("[jm] Service is up.", flush=True)
            return
    raise RuntimeError(f"service did not start within {start_timeout}s; see {log_path}")


def ensure_service(base: str, project_dir: str, args: argparse.Namespace, local: dict) -> None:
    if is_service_running(base):
        return
    if not auto_deploy_enabled(args, local):
        raise RuntimeError(f"JMComic-Api is not running: {base}")

    api_repo = config_value(args, local, "api_repo", "JMAPI_REPO", DEFAULT_API_REPO)
    api_ref = config_value(args, local, "api_ref", "JMAPI_REF", "")
    bind_host = config_value(args, local, "bind_host", "JMAPI_BIND_HOST", DEFAULT_BIND_HOST)
    start_timeout = int(config_value(args, local, "start_timeout", "JMAPI_START_TIMEOUT", DEFAULT_START_TIMEOUT))
    print("[jm] Service not running, deploying on host ...", flush=True)
    start_service(
        project_dir,
        base,
        api_repo=api_repo,
        api_ref=api_ref,
        bind_host=bind_host,
        start_timeout=start_timeout,
    )


# ---------------------------------------------------------------------------
# Ghostscript compression
# ---------------------------------------------------------------------------

def _find_gs() -> str | None:
    return shutil.which("gs") or shutil.which("gswin64c") or shutil.which("gswin32c")


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
        [
            gs,
            "-q",
            "-dNOPAUSE",
            "-dBATCH",
            "-sDEVICE=pdfwrite",
            "-dPDFSETTINGS=/ebook",
            "-dCompatibilityLevel=1.4",
            f"-sOutputFile={out}",
            str(pdf_path),
        ],
        capture_output=True,
    )
    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        print("[jm] Compression failed, using original.", flush=True)
        return pdf_path
    new_mb = out.stat().st_size / (1024 * 1024)
    print(f"[jm] Compressed: {size_mb:.1f} MB -> {new_mb:.1f} MB", flush=True)
    pdf_path.unlink()
    out.rename(pdf_path)
    return pdf_path


# ---------------------------------------------------------------------------
# FastAPI calls
# ---------------------------------------------------------------------------

def get_pdf(base: str, album_id: str, out_dir: Path, timeout: int = 900) -> Path:
    """Fetch encrypted PDF from the FastAPI service (password = album_id)."""
    clean = clean_album_id(album_id)
    path = "/get_pdf/" + urllib.parse.quote(clean, safe="")
    url = api_url(path=path, base=base, query={"pdf": "true", "passwd": "true", "Titletype": 2})
    print(f"[jm] Downloading PDF for {clean} ...", flush=True)
    return _download_binary(url, out_dir, f"{clean}.pdf", timeout=timeout)


def search(base: str, query: str, page: int = 1) -> list[dict[str, str]]:
    url = api_url(base, "/search", {"query": query, "page": page})
    r = _get_json(url)
    if not r.get("success"):
        raise RuntimeError(f"search failed: {r}")
    items = r.get("data", {}).get("results", [])
    return [{"id": str(item["id"]), "title": item.get("title", "")} for item in items]


def random_album(
    base: str, *, keywords: tuple[str, ...] = (), rng: random.Random | None = None
) -> dict[str, str]:
    rng = rng or random.Random()
    keyword = rng.choice(keywords) if keywords else "全彩"
    results = search(base, keyword)
    if not results:
        raise RuntimeError("No albums returned for random pick")
    return rng.choice(results)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _common_config(args: argparse.Namespace, local: dict) -> tuple[str, str]:
    base = config_value(args, local, "api_base", "JMAPI_BASE", DEFAULT_API_BASE)
    project_dir = config_value(args, local, "project_dir", "JMAPI_PROJECT_DIR", DEFAULT_PROJECT_DIR)
    return str(base), expand_path(project_dir)


def cmd_doctor(args: argparse.Namespace, local: dict) -> None:
    base, project_dir = _common_config(args, local)
    api_repo = config_value(args, local, "api_repo", "JMAPI_REPO", DEFAULT_API_REPO)
    api_ref = config_value(args, local, "api_ref", "JMAPI_REF", "")
    bind_host = config_value(args, local, "bind_host", "JMAPI_BIND_HOST", DEFAULT_BIND_HOST)
    gs = _find_gs()
    pd = Path(project_dir)
    service = is_service_running(base)
    lines = [
        f"API base:      {base}",
        f"Service:       {'running' if service else 'not running'}",
        f"Readiness:     {_readiness_status(base) if service else 'unknown'}",
        f"Auto deploy:   {'enabled' if auto_deploy_enabled(args, local) else 'disabled'}",
        f"Bind host:     {bind_host}",
        f"API repo:      {api_repo}{(' @ ' + api_ref) if api_ref else ''}",
        f"git:           {'found' if shutil.which('git') else 'not found'}",
        f"uv:            {'found' if shutil.which('uv') else 'not found'}",
        f"Project dir:   {project_dir} ({'exists' if pd.exists() else 'not found (will auto-clone)'})",
        f"Venv ready:    {'yes' if _venv_ready(project_dir) else 'no (first run will install)'}",
        f"Runtime ready: {'yes' if _runtime_ready(project_dir) else 'no (uv sync needed)'}",
        f"Ghostscript:   {gs if gs else 'not found (compression disabled)'}",
    ]
    print("\n".join(lines))


def cmd_search(args: argparse.Namespace, local: dict) -> None:
    base, project_dir = _common_config(args, local)
    ensure_service(base, project_dir, args, local)
    results = search(base, args.query, getattr(args, "page", 1))
    if not results:
        print("没有找到相关结果，换个关键词试试？")
        return
    limit = getattr(args, "limit", 10)
    results = results[:limit]
    if getattr(args, "json_out", False):
        print(json.dumps(results, ensure_ascii=False))
        return
    lines = [f"找到 {len(results)} 个和「{args.query}」相关的结果：\n"]
    for i, item in enumerate(results, 1):
        lines.append(f"{i}. [{item['id']}] {item['title']}")
    lines.append(f"\n你要哪一本？回复 1-{len(results)} 的序号或直接回复 JM 号。")
    print("\n".join(lines))


def _download_and_output(base: str, album_id: str, out_dir: Path) -> None:
    clean = clean_album_id(album_id)
    pdf_path = get_pdf(base, clean, out_dir)
    pdf_path = compress_pdf(pdf_path)
    print(f"pdf_path={pdf_path}")
    print(f"pdf_password={clean}")
    print(f"album_id={clean}")
    print(f"filename={pdf_path.name}")


def cmd_get(args: argparse.Namespace, local: dict) -> None:
    base, project_dir = _common_config(args, local)
    out_dir = Path(expand_path(config_value(args, local, "out", "JMAPI_OUT_DIR", DEFAULT_OUT_DIR)))
    ensure_service(base, project_dir, args, local)
    _download_and_output(base, args.album_id, out_dir)


def cmd_random(args: argparse.Namespace, local: dict) -> None:
    base, project_dir = _common_config(args, local)
    out_dir = Path(expand_path(config_value(args, local, "out", "JMAPI_OUT_DIR", DEFAULT_OUT_DIR)))
    ensure_service(base, project_dir, args, local)
    kw_str = config_value(args, local, "random_keywords", "JMAPI_RANDOM_KEYWORDS", "")
    keywords = tuple(k.strip() for k in kw_str.split(",") if k.strip()) if kw_str else ()
    album = random_album(base, keywords=keywords)
    print(f"[jm] Random pick: [{album['id']}] {album['title']}", flush=True)
    _download_and_output(base, album["id"], out_dir)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="JMComic FastAPI helper")
    p.add_argument("--api-base", dest="api_base", default="")
    p.add_argument("--project-dir", dest="project_dir", default="")
    p.add_argument("--api-repo", dest="api_repo", default="")
    p.add_argument("--api-ref", dest="api_ref", default="")
    p.add_argument("--bind-host", dest="bind_host", default="")
    p.add_argument("--start-timeout", dest="start_timeout", default="")
    p.add_argument("--no-auto-deploy", action="store_true")

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
    try:
        main()
    except KeyboardInterrupt:
        print("error=interrupted", file=sys.stderr)
        sys.exit(130)
    except RuntimeError as e:
        print(f"error={e}", file=sys.stderr)
        sys.exit(1)
