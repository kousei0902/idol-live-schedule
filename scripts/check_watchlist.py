#!/usr/bin/env python3
"""Fetch each watchlist URL and look for new live events.

For sites we have a structured parser for (tiget.net, livepocket.jp,
eplus.jp), this extracts actual event data (title, date, venue) and files
a GitHub issue per newly-seen event. For any other site, it falls back to
a simple content-hash diff (detects "something changed", nothing more).
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit, parse_qsl, urlencode

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
WATCHLIST_PATH = ROOT / "watchlist.json"
STATE_PATH = ROOT / "state.json"
EVENTS_PATH = ROOT / "events.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

JP_DATE_RE = re.compile(r"(\d{4})[年/](\d{1,2})[月/](\d{1,2})")
JST = timezone(timedelta(hours=9))


def load_json(path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def fetch(url):
    req = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def add_query_param(url, key, value):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query[key] = str(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


# Hosts whose listing is behind a JS bot-challenge and need a real browser.
BROWSER_HOSTS = {"livepocket.jp"}

# How to build the URL for page N (N >= 2) of a site's listing. Sites not
# listed here only ever fetch a single page, regardless of max_pages.
def _liveidol_page_url(url, page):
    # liveidol.blog's /live/ page shows a rolling 3-week (21-day) window
    # starting from "today" by default, but a `schedule_start=YYYY-MM-DD`
    # query param (confirmed via its own date-picker's change handler,
    # which does window.location.assign with that param) fetches a fresh
    # server-rendered 21-day window from any start date. Event counts
    # taper off the further out you go (confirmed: 704 -> 208 -> 81 -> 45
    # -> 26 -> 19 across 6 successive 21-day windows), so page N asks for
    # the window starting 21*(N-1) days from today.
    start_date = datetime.now(JST).date() + timedelta(days=21 * (page - 1))
    return add_query_param(url, "schedule_start", start_date.isoformat())


PAGE_URL_BUILDERS = {
    "tiget.net": lambda url, page: add_query_param(url, "page", page),
    "livepocket.jp": lambda url, page: add_query_param(url, "page", page),
    "eplus.jp": lambda url, page: url.rstrip("/") + f"/p{page}",
    "liveidol.blog": _liveidol_page_url,
}

DEFAULT_MAX_PAGES = 4
# Pause between page requests on the same site, to be polite and avoid
# tripping congestion/rate-limit pages (eplus.jp has shown a "混雑のお知らせ"
# 503 under rapid repeated requests).
PAGE_DELAY_SECONDS = 1.5


def fetch_pages(base_url, max_pages, page_url_fn, use_browser):
    """Fetch up to max_pages pages of a listing, returning a list of
    (page_url, html_bytes). Stops early on a fetch error."""
    if use_browser:
        from playwright.sync_api import sync_playwright

        pages = []
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            try:
                browser_page = browser.new_page(user_agent=USER_AGENT, locale="ja-JP")
                for i in range(1, max_pages + 1):
                    page_url = page_url_fn(base_url, i) if (page_url_fn and i > 1) else base_url
                    try:
                        browser_page.goto(page_url, timeout=30000)
                        try:
                            browser_page.wait_for_load_state("networkidle", timeout=15000)
                        except Exception:
                            pass
                        # AWS WAF's JS challenge resolves and swaps in real
                        # content a few seconds after load; give it room.
                        browser_page.wait_for_timeout(5000 if i == 1 else 2500)
                        pages.append((page_url, browser_page.content().encode("utf-8")))
                    except Exception as e:
                        print(f"  [page {i}] browser fetch failed: {type(e).__name__}: {e}")
                        break
                    if i < max_pages:
                        browser_page.wait_for_timeout(int(PAGE_DELAY_SECONDS * 1000))
            finally:
                browser.close()
        return pages

    pages = []
    for i in range(1, max_pages + 1):
        page_url = page_url_fn(base_url, i) if (page_url_fn and i > 1) else base_url
        try:
            pages.append((page_url, fetch(page_url)))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read(300).decode("utf-8", "replace")
            except Exception:
                pass
            print(f"  [page {i}] HTTP {e.code} {e.reason} :: {body}")
            break
        except Exception as e:
            print(f"  [page {i}] fetch failed: {type(e).__name__}: {e}")
            break
        if i < max_pages:
            time.sleep(PAGE_DELAY_SECONDS)
    return pages


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


def parse_ticketdive(html, base_url):
    """TicketDive is a Next.js SPA with no genre filter and no listing
    API beyond what's embedded in the homepage's server-rendered
    __NEXT_DATA__ blob (confirmed via network-request capture: no
    search/browse endpoint, no infinite-scroll loading). Combines every
    section of that blob that carries individual events - "entryNow"
    (new arrivals, has date/venue) and "carousel" (featured picks,
    title only) - for the maximum this site exposes. Mixed genres
    (band, comedy, sports, ...) since there's no idol-only feed."""
    text = html.decode("utf-8", "replace")
    marker = "__NEXT_DATA__"
    idx = text.find(marker)
    if idx == -1:
        return []
    start = text.find(">", idx) + 1
    end = text.find("</script>", start)
    try:
        data = json.loads(text[start:end])
        payload = data["props"]["pageProps"]["__superjsonProps"]["json"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []

    events = []
    seen_urls = set()
    for section in ("entryNow", "carousel", "forYouArtistEvents"):
        for item in payload.get(section) or []:
            slug = item.get("url")
            if not slug:
                continue
            event_url = urljoin(base_url, f"/event/{slug}")
            if event_url in seen_urls:
                continue
            seen_urls.add(event_url)
            title = item.get("title", "")
            date = None
            raw_date = item.get("displayStageDate") or item.get("startEventDate")
            if raw_date:
                try:
                    dt_utc = datetime.strptime(raw_date, "%Y-%m-%dT%H:%M:%S.%fZ")
                    date = (dt_utc + timedelta(hours=9)).strftime("%Y-%m-%d")
                except ValueError:
                    pass
            events.append({
                "event_url": event_url,
                "title": title,
                "group": title,
                "date": date,
                "venue": item.get("venueName", "") or "",
            })
    return events


def parse_liveidol(html, base_url):
    """liveidol.blog is a third-party aggregator: its /live/ schedule
    page embeds a single JS array (`const scheduleData = [...]`) with
    every event it has collected from 20+ ticket/venue sites (tiget,
    livepocket, eplus, ticketdive, t.pia, buzz-ticket, ...), including
    many more ticketdive.com entries than that site's own page exposes
    directly. No pagination and no JS execution needed - it's a plain
    JS variable in the server-rendered HTML, extracted by balancing
    brackets rather than a <script type="application/json"> tag since
    it isn't one. event_url points at the ORIGINAL ticket site, which
    is convenient: it dedupes for free against events already found by
    the site-specific parsers above (both key on event_url)."""
    text = html.decode("utf-8", "replace")
    marker = "const scheduleData = "
    idx = text.find(marker)
    if idx == -1:
        return []
    start = idx + len(marker)
    depth = 0
    end = None
    for i in range(start, len(text)):
        c = text[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        return []
    try:
        data = json.loads(text[start:end])
    except json.JSONDecodeError:
        return []

    events = []
    seen_urls = set()
    for item in data:
        event_url = item.get("event_url")
        if not event_url:
            continue
        event_url = urljoin(base_url, event_url)
        if event_url in seen_urls:
            continue
        seen_urls.add(event_url)
        title = item.get("event_name", "") or ""
        venue = item.get("venue_name", "") or ""
        events.append({
            "event_url": event_url,
            "title": title,
            "group": title,
            "date": item.get("event_date") or None,
            "venue": venue,
        })
    return events


PARSERS = {
    "tiget.net": parse_tiget,
    "livepocket.jp": parse_livepocket,
    "eplus.jp": parse_eplus,
    "ticketdive.com": parse_ticketdive,
    "liveidol.blog": parse_liveidol,
}


def create_issue(title, body):
    # Body can be large (a big batch of newly-discovered events); passing it
    # as a CLI argument risks OSError: Argument list too long, so write it
    # to a temp file and use --body-file instead.
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(body)
        body_path = f.name
    try:
        result = subprocess.run(
            ["gh", "issue", "create", "--title", title, "--body-file", body_path],
            capture_output=True,
            text=True,
        )
    finally:
        os.unlink(body_path)
    if result.returncode != 0:
        print(f"gh issue create failed: {result.stderr}", file=sys.stderr)
        return False
    print(result.stdout.strip())
    return True


def check_structured(entry, parser, events_known, use_browser=False, max_pages=1, page_url_fn=None):
    url = entry["url"]
    group_label = entry.get("group", "(不明)")

    fetched_pages = fetch_pages(url, max_pages, page_url_fn, use_browser)
    if not fetched_pages:
        print(f"[skip] {group_label} ({url}): no pages fetched")
        return [], False

    all_events = []
    seen_this_run = set()
    for page_url, html in fetched_pages:
        events = parser(html, page_url)
        if not events:
            soup = BeautifulSoup(html, "html.parser")
            page_title = soup.title.get_text(strip=True) if soup.title else "(no <title>)"
            print(f"  [debug] {group_label}: 0 events parsed at {page_url}; page title = {page_title!r}, body length = {len(html)}")
            break  # either the end of pagination, or a block page — stop either way
        for ev in events:
            if ev["event_url"] not in seen_this_run:
                seen_this_run.add(ev["event_url"])
                all_events.append(ev)

    new_events = []
    changed = False
    for ev in all_events:
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
    print(f"[{group_label}] checked {len(all_events)} listings across {len(fetched_pages)} page(s), {len(new_events)} new")
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
            page_url_fn = PAGE_URL_BUILDERS.get(host)
            max_pages = entry.get("max_pages", DEFAULT_MAX_PAGES) if page_url_fn else 1
            new_events, changed = check_structured(
                entry, parser, events_known,
                use_browser=(host in BROWSER_HOSTS),
                max_pages=max_pages,
                page_url_fn=page_url_fn,
            )
            all_new_events.extend(new_events)
            events_changed = events_changed or changed
        else:
            alert = check_hash_fallback(entry, state)
            state_changed = True
            if alert:
                hash_alerts.append(alert)

    # Persist first, notify second — a crash while creating issues (e.g. a
    # huge one-off batch) must never cost us the newly-collected data.
    if events_changed:
        with EVENTS_PATH.open("w", encoding="utf-8") as f:
            json.dump(events_known, f, ensure_ascii=False, indent=2)
            f.write("\n")

    if state_changed:
        with STATE_PATH.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.write("\n")

    # GitHub issue bodies cap out around 65,536 characters; keep each issue
    # comfortably under that by splitting large batches into chunks.
    MAX_EVENTS_PER_ISSUE = 150
    if all_new_events:
        chunks = [
            all_new_events[i:i + MAX_EVENTS_PER_ISSUE]
            for i in range(0, len(all_new_events), MAX_EVENTS_PER_ISSUE)
        ]
        for idx, chunk in enumerate(chunks, start=1):
            title = f"新着ライブ情報 {len(all_new_events)}件"
            if len(chunks) > 1:
                title += f" ({idx}/{len(chunks)})"
            lines = []
            for ev in chunk:
                date = ev["date"] or "日付不明"
                venue = ev["venue"] or "会場不明"
                lines.append(f"- **{ev['group']}** / {date} / {venue}\n  {ev['title']}\n  {ev['event_url']}")
            body = "\n\n".join(lines)
            create_issue(title, body)

    for alert in hash_alerts:
        title = f"新着更新の可能性: {alert['group']}"
        body = f"{alert['url']}\n\n{alert['note']}\n\nchecked at {alert['checked_at']}"
        create_issue(title, body)

    print(f"done: {len(all_new_events)} new events, {len(hash_alerts)} hash-diff alerts")


if __name__ == "__main__":
    main()
