#!/usr/bin/env python3
"""Fetch each watchlist URL and look for new live events.

For sites we have a structured parser for (tiget.net, livepocket.jp,
eplus.jp), this extracts actual event data (title, date, venue) and files
a GitHub issue per newly-seen event. For any other site, it falls back to
a simple content-hash diff (detects "something changed", nothing more).
"""

import hashlib
import json
import re
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
WATCHLIST_PATH = ROOT / "watchlist.json"
STATE_PATH = ROOT / "state.json"
EVENTS_PATH = ROOT / "events.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 oshisuke-watcher/1.0"
)

JP_DATE_RE = re.compile(r"(\d{4})[年/](\d{1,2})[月/](\d{1,2})")


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


def parse_jp_date(text):
    m = JP_DATE_RE.search(text or "")
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    try:
        return f"{y:04d}-{mo:02d}-{d:02d}"
    except ValueError:
        return None


def strip_label(el):
    """Remove the first <span> child (a field label like '会場') and
    return the remaining text of el."""
    if el is None:
        return ""
    el = BeautifulSoup(str(el), "html.parser")
    span = el.find("span")
    if span:
        span.extract()
    return el.get_text(strip=True)


# ---- site-specific parsers ----------------------------------------------

def parse_tiget(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    events = []
    seen_urls = set()
    for detail in soup.select(".event-detail"):
        title_a = detail.select_one(".event-title a")
        if not title_a or not title_a.get("href"):
            continue
        event_url = urljoin(base_url, title_a["href"])
        if event_url in seen_urls:
            continue
        seen_urls.add(event_url)
        title = title_a.get_text(strip=True)
        play_date = detail.select_one(".play-date")
        date = parse_jp_date(play_date.get_text(strip=True) if play_date else "")
        performer = detail.select_one(".performer")
        group = ""
        if performer:
            group = performer.get_text(strip=True).replace("出演：", "").replace("出演:", "").strip()
        venue_el = detail.select_one(".event-area")
        venue = venue_el.get_text(strip=True) if venue_el else ""
        venue = re.sub(r"^場所[：:]\s*", "", venue)
        events.append({
            "event_url": event_url,
            "title": title,
            "group": group or title,
            "date": date,
            "venue": venue,
        })
    return events


def parse_livepocket(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    events = []
    seen_urls = set()
    for card in soup.select("a.event-card"):
        href = card.get("href")
        if not href:
            continue
        event_url = urljoin(base_url, href)
        if event_url in seen_urls:
            continue
        seen_urls.add(event_url)
        title_el = card.select_one(".event-card__title")
        title = title_el.get_text(strip=True) if title_el else ""
        date_p = card.select_one(".event-card__text--date")
        date = parse_jp_date(strip_label(date_p))
        venue = ""
        for p in card.select(".event-card__text"):
            if p.select_one(".event-card__place"):
                venue = strip_label(p)
                break
        group = ""
        for p in card.select(".event-card__text"):
            if p.select_one(".event-card__cast"):
                group = strip_label(p)
                break
        events.append({
            "event_url": event_url,
            "title": title,
            "group": group or title,
            "date": date,
            "venue": venue,
        })
    return events


def parse_eplus(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    events = []
    seen_urls = set()
    for item in soup.select("a.ticket-item"):
        href = item.get("href")
        if not href:
            continue
        event_url = urljoin(base_url, href)
        if event_url in seen_urls:
            continue
        seen_urls.add(event_url)
        title_el = item.select_one(".ticket-item__title")
        title = ""
        if title_el:
            title_copy = BeautifulSoup(str(title_el), "html.parser")
            for span in title_copy.find_all("span"):
                span.extract()
            title = title_copy.get_text(strip=True)
        yyyy_el = item.select_one(".ticket-item__yyyy")
        mmdd_el = item.select_one(".ticket-item__mmdd")
        date_text = (yyyy_el.get_text(strip=True) if yyyy_el else "") + \
                    (mmdd_el.get_text(strip=True) if mmdd_el else "")
        date = parse_jp_date(date_text)
        venue_el = item.select_one(".ticket-item__venue")
        venue = venue_el.get_text(strip=True) if venue_el else ""
        events.append({
            "event_url": event_url,
            "title": title,
            "group": title,
            "date": date,
            "venue": venue,
        })
    return events


PARSERS = {
    "tiget.net": parse_tiget,
    "livepocket.jp": parse_livepocket,
    "eplus.jp": parse_eplus,
}


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


def check_structured(entry, parser, events_known):
    url = entry["url"]
    group_label = entry.get("group", "(不明)")
    try:
        html = fetch(url)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read(500).decode("utf-8", "replace")
        except Exception:
            pass
        print(f"[skip] {group_label} ({url}): HTTP {e.code} {e.reason} :: {body}")
        return [], False
    except Exception as e:
        print(f"[skip] {group_label} ({url}): fetch failed: {type(e).__name__}: {e}")
        return [], False

    events = parser(html, url)
    if not events:
        soup = BeautifulSoup(html, "html.parser")
        page_title = soup.title.get_text(strip=True) if soup.title else "(no <title>)"
        print(f"  [debug] {group_label}: 0 events parsed; page title = {page_title!r}, body length = {len(html)}")
    new_events = []
    changed = False
    for ev in events:
        key = ev["event_url"]
        if key not in events_known:
            events_known[key] = {
                "title": ev["title"],
                "group": ev["group"],
                "date": ev["date"],
                "venue": ev["venue"],
                "source": group_label,
                "firstSeen": now_iso(),
            }
            new_events.append(ev)
            changed = True
    print(f"[{group_label}] checked {len(events)} listings, {len(new_events)} new")
    return new_events, changed


def check_hash_fallback(entry, state):
    url = entry["url"]
    group_label = entry.get("group", "(不明)")
    note = entry.get("note", "")
    try:
        content = fetch(url)
    except Exception as e:
        print(f"[skip] {group_label} ({url}): fetch failed: {type(e).__name__}: {e}")
        return None

    digest = hashlib.sha256(content).hexdigest()
    prev = state.get(url)
    checked_at = now_iso()

    if prev is None:
        state[url] = {"hash": digest, "lastChecked": checked_at, "lastChanged": None}
        print(f"[baseline] {group_label} ({url})")
        return None

    if prev.get("hash") != digest:
        state[url] = {"hash": digest, "lastChecked": checked_at, "lastChanged": checked_at}
        print(f"[changed] {group_label} ({url})")
        return {"group": group_label, "url": url, "note": note, "checked_at": checked_at}

    prev["lastChecked"] = checked_at
    print(f"[unchanged] {group_label} ({url})")
    return None


def main():
    watchlist = load_json(WATCHLIST_PATH, [])
    state = load_json(STATE_PATH, {})
    events_known = load_json(EVENTS_PATH, {})

    if not watchlist:
        print("watchlist.json is empty, nothing to check.")
        return

    all_new_events = []
    hash_alerts = []
    state_changed = False
    events_changed = False

    for entry in watchlist:
        url = entry.get("url")
        if not url:
            continue
        host = urlparse(url).netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        parser = PARSERS.get(host)

        if parser:
            new_events, changed = check_structured(entry, parser, events_known)
            all_new_events.extend(new_events)
            events_changed = events_changed or changed
        else:
            alert = check_hash_fallback(entry, state)
            state_changed = True
            if alert:
                hash_alerts.append(alert)

    if all_new_events:
        title = f"新着ライブ情報 {len(all_new_events)}件"
        lines = []
        for ev in all_new_events:
            date = ev["date"] or "日付不明"
            venue = ev["venue"] or "会場不明"
            lines.append(f"- **{ev['group']}** / {date} / {venue}\n  {ev['title']}\n  {ev['event_url']}")
        body = "\n\n".join(lines)
        create_issue(title, body)

    for alert in hash_alerts:
        title = f"新着更新の可能性: {alert['group']}"
        body = f"{alert['url']}\n\n{alert['note']}\n\nchecked at {alert['checked_at']}"
        create_issue(title, body)

    if events_changed:
        with EVENTS_PATH.open("w", encoding="utf-8") as f:
            json.dump(events_known, f, ensure_ascii=False, indent=2)
            f.write("\n")

    if state_changed:
        with STATE_PATH.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.write("\n")

    print(f"done: {len(all_new_events)} new events, {len(hash_alerts)} hash-diff alerts")


if __name__ == "__main__":
    main()
