#!/usr/bin/env python3
"""Log into X with a dedicated monitoring account and check the
"Following" timeline for new posts from accounts the user follows.

Credentials come from the X_USERNAME / X_PASSWORD environment
variables (GitHub Actions secrets) - never logged, never written to
any file. Unlike the ticket-site checkers, tweet text is unstructured,
so this doesn't try to extract date/venue - it just surfaces new posts
(author, text, link) for the user to read and judge for themselves.

X's login flow is one of the most bot-hostile of anything this project
touches. This script fails soft: if login or scraping doesn't work,
it prints diagnostics and exits 0 rather than breaking the rest of the
GitHub Actions job.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
X_STATE_PATH = ROOT / "x_state.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

MAX_NEW_POSTS_PER_RUN = 40
SCROLL_ROUNDS = 8


def load_json(path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


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


def log_in(page, username, password):
    page.goto("https://x.com/i/flow/login", timeout=30000)
    page.wait_for_timeout(2000)

    username_input = page.locator('input[autocomplete="username"]').first
    username_input.wait_for(timeout=15000)
    username_input.fill(username)
    page.get_by_role("button", name=re.compile("次へ|Next")).first.click()
    page.wait_for_timeout(1500)

    # X sometimes re-asks for the username/phone as an "unusual activity"
    # check before ever showing the password field.
    if page.locator('input[autocomplete="username"]').count() > 0 and \
       page.locator('input[name="password"]').count() == 0:
        retry_input = page.locator('input[autocomplete="username"], input[data-testid="ocfEnterTextTextInput"]').first
        retry_input.fill(username)
        page.get_by_role("button", name=re.compile("次へ|Next")).first.click()
        page.wait_for_timeout(1500)

    password_input = page.locator('input[name="password"]').first
    password_input.wait_for(timeout=15000)
    password_input.fill(password)
    page.get_by_role("button", name=re.compile("ログイン|Log in")).first.click()
    page.wait_for_timeout(4000)

    try:
        page.wait_for_url(re.compile(r"x\.com/home"), timeout=20000)
        return True
    except Exception:
        return False


def scrape_following_timeline(page):
    page.goto("https://x.com/home", timeout=30000)
    page.wait_for_timeout(3000)

    following_tab = page.get_by_role("tab", name=re.compile("フォロー中|Following"))
    try:
        following_tab.first.click(timeout=10000)
        page.wait_for_timeout(2500)
    except Exception:
        print("[warn] could not click the Following tab; reading whatever timeline is showing")

    seen_ids = set()
    posts = []
    for _ in range(SCROLL_ROUNDS):
        articles = page.locator('article[data-testid="tweet"]')
        count = articles.count()
        for i in range(count):
            article = articles.nth(i)
            try:
                link = article.locator('a[href*="/status/"]').first
                href = link.get_attribute("href")
                if not href:
                    continue
                m = re.search(r"/([^/]+)/status/(\d+)", href)
                if not m:
                    continue
                handle, tweet_id = m.group(1), m.group(2)
                if tweet_id in seen_ids:
                    continue
                seen_ids.add(tweet_id)
                text_el = article.locator('div[data-testid="tweetText"]').first
                text = text_el.inner_text() if text_el.count() > 0 else ""
                posts.append({
                    "id": tweet_id,
                    "handle": handle,
                    "text": text,
                    "url": f"https://x.com/{handle}/status/{tweet_id}",
                })
            except Exception:
                continue
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(1500)

    return posts


def main():
    username = os.environ.get("X_USERNAME")
    password = os.environ.get("X_PASSWORD")
    if not username or not password:
        print("X_USERNAME / X_PASSWORD not set; skipping X check.")
        return

    from playwright.sync_api import sync_playwright

    x_state = load_json(X_STATE_PATH, {"seen_ids": []})
    seen_ids = set(x_state.get("seen_ids", []))

    posts = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        try:
            page = browser.new_page(user_agent=USER_AGENT, locale="ja-JP")
            if not log_in(page, username, password):
                print(f"[skip] X login did not reach the home timeline. "
                      f"Current URL: {page.url!r}, title: {page.title()!r}")
                snippet = page.locator("body").inner_text()[:500]
                print(f"[debug] body snippet: {snippet!r}")
                return
            posts = scrape_following_timeline(page)
        except Exception as e:
            print(f"[skip] X check failed: {type(e).__name__}: {e}")
            return
        finally:
            browser.close()

    new_posts = [p for p in posts if p["id"] not in seen_ids]
    print(f"[X] checked {len(posts)} posts in following timeline, {len(new_posts)} new")

    if new_posts:
        to_report = new_posts[:MAX_NEW_POSTS_PER_RUN]
        lines = []
        for post in to_report:
            text = post["text"].strip() or "(本文なし・画像/動画のみ等)"
            lines.append(f"- **@{post['handle']}**\n  {text}\n  {post['url']}")
        title = f"Xの新着投稿 {len(to_report)}件"
        body = "\n\n".join(lines)
        create_issue(title, body)

        for post in new_posts:
            seen_ids.add(post["id"])
        x_state["seen_ids"] = list(seen_ids)[-5000:]  # cap growth
        with X_STATE_PATH.open("w", encoding="utf-8") as f:
            json.dump(x_state, f, ensure_ascii=False, indent=2)
            f.write("\n")

    print(f"done: {len(new_posts)} new X posts")


if __name__ == "__main__":
    main()
