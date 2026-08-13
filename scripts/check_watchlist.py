#!/usr/bin/env python3
"""Fetch each watchlist URL, diff against the stored hash, and file a GitHub
issue when a page's content has changed since the last check."""

import hashlib
import json
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCHLIST_PATH = ROOT / "watchlist.json"
STATE_PATH = ROOT / "state.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 oshisuke-watcher/1.0"
)


def load_json(path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_issue(title, body):
    result = subprocess.run(
        ["gh", "issue", "create", "--title", title, "--body", body],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"gh issue create failed: {result.stderr}", file=sys.stderr)
        return False
    print(result.stdout.strip())
    return True


def main():
    watchlist = load_json(WATCHLIST_PATH, [])
    state = load_json(STATE_PATH, {})

    if not watchlist:
        print("watchlist.json is empty, nothing to check.")
        return

    checked = 0
    changed = 0
    failed = 0

    for entry in watchlist:
        url = entry.get("url")
        group = entry.get("group", "(不明)")
        note = entry.get("note", "")
        if not url:
            continue

        checked += 1
        try:
            content = fetch(url)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"[skip] {group} ({url}): fetch failed: {e}")
            failed += 1
            continue

        digest = hashlib.sha256(content).hexdigest()
        prev = state.get(url)
        checked_at = now_iso()

        if prev is None:
            state[url] = {"hash": digest, "lastChecked": checked_at, "lastChanged": None}
            print(f"[baseline] {group} ({url})")
            continue

        if prev.get("hash") != digest:
            print(f"[changed] {group} ({url})")
            changed += 1
            state[url] = {"hash": digest, "lastChecked": checked_at, "lastChanged": checked_at}
            title = f"新着更新の可能性: {group}"
            body = f"{url}\n\n{note}\n\nchecked at {checked_at}"
            create_issue(title, body)
        else:
            prev["lastChecked"] = checked_at
            print(f"[unchanged] {group} ({url})")

    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"checked={checked} changed={changed} failed={failed}")


if __name__ == "__main__":
    main()
