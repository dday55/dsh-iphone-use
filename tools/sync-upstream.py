#!/usr/bin/env python3
"""Refresh ``vendor/iphone-use`` from the upstream iPhone Use repository.

This bundle carries a snapshot of the upstream runtime (MCP server, skills,
widget page) so that a git install needs nothing else. Update it
deliberately:

    python3 tools/sync-upstream.py --ref v0.3.16          # from GitHub
    python3 tools/sync-upstream.py --source ../iPhone-use --ref HEAD   # local clone
    python3 tools/sync-upstream.py --check                # verify the snapshot

The snapshot is authoritative for the paths listed in ``SNAPSHOT``: files that
disappear upstream are deleted here too. ``vendor/UPSTREAM.json`` records the
commit and version the snapshot came from, and this script warns when the
bundle's own version no longer matches.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "iphone-use"
UPSTREAM_REPO = "zhongerxin/iPhone-use"
UPSTREAM_URL = f"https://github.com/{UPSTREAM_REPO}.git"
CODELOAD = f"https://codeload.github.com/{UPSTREAM_REPO}/tar.gz/"

# Everything the Harness bundle needs, and nothing else: the Codex manifests,
# UI sources, tests, and the WorkBuddy/Doubao adapters stay upstream.
SNAPSHOT_FILES = (
    "plugin.json",
    "assets/phone-screen.html",
    "assets/icon.svg",
    "scripts/smoke_mcp.py",
)
SNAPSHOT_DIRS = ("server", "skills")


def _extract_all(tar: tarfile.TarFile, target: Path) -> None:
    if hasattr(tarfile, "data_filter"):
        tar.extractall(target, filter="data")
    else:
        tar.extractall(target)


def local_source(source: Path, ref: str) -> Path:
    if not (source / ".git").exists():
        raise SystemExit(f"not a git checkout: {source}")
    target = Path(tempfile.mkdtemp(prefix="iphone-use-sync-"))
    archive = subprocess.run(
        ["git", "-C", str(source), "archive", "--format=tar", ref],
        check=True, capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        _extract_all(tar, target)
    return target


def remote_source(ref: str) -> Path:
    target = Path(tempfile.mkdtemp(prefix="iphone-use-sync-"))
    data = urllib.request.urlopen(CODELOAD + ref, timeout=60).read()
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        _extract_all(tar, target)
    inner = next(path for path in target.iterdir() if path.is_dir())
    return inner


def collect(source: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for name in SNAPSHOT_FILES:
        path = source / name
        if path.is_file():
            files[name] = path.read_bytes()
    for dirname in SNAPSHOT_DIRS:
        for path in sorted((source / dirname).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".jsonl"):
                files[path.relative_to(source).as_posix()] = path.read_bytes()
    return files


def current() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    if VENDOR.exists():
        for path in sorted(VENDOR.rglob("*")):
            if path.is_file():
                files[path.relative_to(VENDOR).as_posix()] = path.read_bytes()
    return files


def version_of(files: dict[str, bytes]) -> str:
    manifest = json.loads(files["plugin.json"])
    return manifest["version"]


def write(files: dict[str, bytes], ref: str, commit: str) -> None:
    VENDOR.mkdir(parents=True, exist_ok=True)
    wanted = set(files)
    for path in sorted(VENDOR.rglob("*"), reverse=True):
        if path.is_file() and path.relative_to(VENDOR).as_posix() not in wanted:
            path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    for name, data in files.items():
        target = VENDOR / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (VENDOR / "UPSTREAM.json").write_text(json.dumps({
        "repo": UPSTREAM_URL,
        "ref": ref,
        "commit": commit,
        "version": version_of(files),
        "syncedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, indent=2) + "\n")


def git_commit(source: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "-C", str(source), "rev-parse", ref], check=True, capture_output=True, text=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", help="local upstream checkout (default: download from GitHub)")
    parser.add_argument("--ref", default="HEAD", help="tag, branch, or commit to snapshot")
    parser.add_argument("--check", action="store_true", help="compare the snapshot with the upstream ref and exit")
    args = parser.parse_args()

    if args.check:
        recorded = json.loads((VENDOR / "UPSTREAM.json").read_text())
        print(f"snapshot: {recorded['ref']} @ {recorded['commit'][:12]} (version {recorded['version']})")
        local = current()
        local.pop("UPSTREAM.json", None)
        expected = collect(VENDOR)
        expected.pop("UPSTREAM.json", None)
        changed = sorted(set(local) ^ set(expected))
        if changed:
            print("snapshot is missing or carries extra files:", *changed, sep="\n  ")
            return 1
        print("snapshot is internally consistent")
        return 0

    if args.source:
        source = Path(args.source).expanduser().resolve()
        tree = local_source(source, args.ref)
        commit = git_commit(source, args.ref)
    else:
        tree = remote_source(args.ref)
        commit = args.ref

    files = collect(tree)
    if "server/iphone_use.py" not in files or "plugin.json" not in files:
        raise SystemExit("upstream snapshot is incomplete: server/iphone_use.py or plugin.json missing")
    previous = json.loads((VENDOR / "UPSTREAM.json").read_text()) if (VENDOR / "UPSTREAM.json").is_file() else {}
    write(files, args.ref, commit)

    # The bundle owns its own semver; the vendored runtime's version lives in
    # UPSTREAM.json, so an upstream bump does not have to reuse its number.
    bundle = json.loads((ROOT / "package.json").read_text())
    upstream_version = version_of(files)
    print(f"vendored {len(files)} files from {args.ref} ({commit[:12]}), upstream version {upstream_version}")
    if previous.get("version") != upstream_version:
        print(f"note: upstream moved {previous.get('version')} -> {upstream_version}; bump the bundle version (currently {bundle['version']})")
    print("next: git diff --stat, then commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
