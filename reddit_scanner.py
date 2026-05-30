#!/usr/bin/env python3
"""
Reddit Keyword Scanner → Telegram Notifier
Uses the official Reddit Data API via PRAW (OAuth2 / Password Flow).

Usage:
    python reddit_scanner.py                    # one-shot scan
    python reddit_scanner.py --watch            # continuous, re-scans on interval
    python reddit_scanner.py --config my.yaml   # custom config path
    python reddit_scanner.py --dry-run          # print matches, don't send to Telegram

Setup:
    pip install praw pyyaml requests

    Fill in config.yaml:
      reddit.client_id / client_secret  ← from https://www.reddit.com/prefs/apps
      reddit.username / password        ← your Reddit account
      telegram.bot_token                ← from @BotFather
      telegram.chat_id                  ← from @userinfobot
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import praw
import requests
import yaml

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("reddit_scanner")

# Suppress PRAW's verbose info logs
logging.getLogger("prawcore").setLevel(logging.WARNING)


# ── Config ─────────────────────────────────────────────────────────────────────

def load_config(path: str) -> dict:
    if not os.path.exists(path):
        sys.exit(f"❌  Config file not found: {path}")

    with open(path) as f:
        cfg = yaml.safe_load(f)

    # --- Reddit credentials ---
    r = cfg.get("reddit", {})
    missing = [k for k in ("client_id", "client_secret", "username", "password", "user_agent")
               if not r.get(k) or "YOUR_" in str(r.get(k, ""))]
    if missing:
        sys.exit(f"❌  Fill in reddit.{missing[0]} (and others) in {path}")

    # --- Telegram credentials ---
    tg = cfg.get("telegram", {})
    if not tg.get("bot_token") or "YOUR_" in tg.get("bot_token", ""):
        sys.exit(f"❌  Set telegram.bot_token in {path}")
    if not tg.get("chat_id") or "YOUR_" in str(tg.get("chat_id", "")):
        sys.exit(f"❌  Set telegram.chat_id in {path}")

    # --- Required lists ---
    if not cfg.get("subreddits"):
        sys.exit("❌  Add at least one subreddit to config.")
    if not cfg.get("keywords"):
        sys.exit("❌  Add at least one keyword to config.")

    # --- Defaults ---
    s = cfg.setdefault("scan", {})
    s.setdefault("posts_per_subreddit", 25)
    s.setdefault("scan_interval_minutes", 30)
    s.setdefault("search_in_body", True)

    f = cfg.setdefault("filters", {})
    f.setdefault("min_score", 0)
    f.setdefault("exclude_flairs", [])

    cfg.setdefault("state_file", ".reddit_scanner_state.json")
    return cfg


# ── State (deduplication) ──────────────────────────────────────────────────────

def load_state(path: str) -> set:
    """Return set of already-seen post IDs."""
    if os.path.exists(path):
        with open(path) as f:
            return set(json.load(f).get("seen_ids", []))
    return set()


def save_state(path: str, seen_ids: set) -> None:
    trimmed = list(seen_ids)[-10_000:]   # cap at 10k to avoid unbounded growth
    with open(path, "w") as f:
        json.dump({"seen_ids": trimmed, "updated": datetime.now().isoformat()}, f)


# ── Reddit (PRAW) ──────────────────────────────────────────────────────────────

def build_reddit(cfg: dict) -> praw.Reddit:
    r = cfg["reddit"]
    return praw.Reddit(
        client_id=r["client_id"],
        client_secret=r["client_secret"],
        username=r["username"],
        password=r["password"],
        user_agent=r["user_agent"],
    )


def fetch_posts(reddit: praw.Reddit, subreddit: str, limit: int) -> list:
    """Fetch recent posts from a subreddit. Returns list of praw Submission objects."""
    try:
        return list(reddit.subreddit(subreddit).new(limit=limit))
    except Exception as e:
        log.warning(f"r/{subreddit} fetch error: {e}")
        return []


# ── Keyword matching ───────────────────────────────────────────────────────────

def find_matching_keywords(submission, keywords: list[str], search_body: bool) -> list[str]:
    title = submission.title.lower()
    body = (submission.selftext or "").lower() if search_body else ""
    haystack = f"{title} {body}"
    return [kw for kw in keywords if kw.lower() in haystack]


def passes_filters(submission, filters: dict) -> bool:
    if submission.score < filters["min_score"]:
        return False
    flair = (submission.link_flair_text or "").strip()
    if flair and flair in filters["exclude_flairs"]:
        return False
    return True


# ── Telegram ───────────────────────────────────────────────────────────────────

TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"


def format_message(submission, subreddit: str, matched: list[str]) -> str:
    dt = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
    time_str = dt.strftime("%b %d, %H:%M UTC")
    kw_tags = " ".join(f"#{kw.replace(' ', '_').replace('-', '_')}" for kw in matched)
    permalink = f"https://www.reddit.com{submission.permalink}"
    flair = (submission.link_flair_text or "").strip()

    lines = [
        f"🔍 <b>r/{subreddit}</b>  ·  {time_str}",
        "",
        f"📌 <b>{submission.title}</b>",
    ]
    if flair:
        lines.append(f"🏷 {flair}")
    lines += [
        "",
        f"👤 u/{submission.author}  ·  ⬆️ {submission.score}  ·  💬 {submission.num_comments}",
        "",
        f"🔑 {kw_tags}",
        "",
        f"🔗 <a href=\"{permalink}\">View on Reddit</a>",
    ]
    if not submission.is_self and submission.url != permalink:
        lines.append(f"🌐 <a href=\"{submission.url}\">External link</a>")

    return "\n".join(lines)


def send_telegram(bot_token: str, chat_id: str, text: str, dry_run: bool = False) -> bool:
    if dry_run:
        print("\n" + "─" * 60)
        print(text)
        print("─" * 60)
        return True

    url = TELEGRAM_URL.format(token=bot_token)
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": False},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except requests.exceptions.HTTPError as e:
        desc = resp.json().get("description", "") if resp.content else ""
        log.error(f"Telegram send failed: {e} — {desc}")
        return False
    except Exception as e:
        log.error(f"Telegram send error: {e}")
        return False


# ── Core scan ──────────────────────────────────────────────────────────────────

def run_scan(cfg: dict, reddit: praw.Reddit, dry_run: bool = False) -> int:
    bot_token = cfg["telegram"]["bot_token"]
    chat_id = cfg["telegram"]["chat_id"]
    keywords = cfg["keywords"]
    filters = cfg["filters"]
    scan = cfg["scan"]
    state_file = cfg["state_file"]

    seen_ids = load_state(state_file)
    new_matches = 0

    log.info(f"Scanning {len(cfg['subreddits'])} subreddit(s) for "
             f"{len(keywords)} keyword(s) …")

    for subreddit in cfg["subreddits"]:
        log.info(f"  r/{subreddit}")
        posts = fetch_posts(reddit, subreddit, limit=scan["posts_per_subreddit"])

        for submission in posts:
            post_id = submission.id

            if post_id in seen_ids:
                continue
            seen_ids.add(post_id)   # always mark seen, keyword match or not

            if not passes_filters(submission, filters):
                continue

            matched = find_matching_keywords(
                submission, keywords, search_body=scan["search_in_body"]
            )
            if not matched:
                continue

            title_preview = submission.title[:70] + ("…" if len(submission.title) > 70 else "")
            log.info(f"    ✅ [{post_id}] {title_preview}  →  {matched}")

            msg = format_message(submission, subreddit, matched)
            if send_telegram(bot_token, chat_id, msg, dry_run=dry_run):
                new_matches += 1

            if not dry_run:
                time.sleep(0.5)   # gentle Telegram rate limit buffer

    save_state(state_file, seen_ids)
    log.info(f"Done. {new_matches} new match(es) sent.")
    return new_matches


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Scan Reddit for keywords and notify via Telegram (uses Reddit Data API / OAuth2)."
    )
    parser.add_argument("--config", default="config.yaml",
                        help="YAML config file (default: config.yaml)")
    parser.add_argument("--watch", action="store_true",
                        help="Continuous mode: re-scan on interval set in config")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print matches to stdout instead of sending to Telegram")
    args = parser.parse_args()

    cfg = load_config(args.config)
    reddit = build_reddit(cfg)

    # Verify credentials on startup
    try:
        me = reddit.user.me()
        log.info(f"✅ Authenticated as u/{me.name}")
    except Exception as e:
        sys.exit(f"❌  Reddit authentication failed: {e}\n"
                 f"    Check client_id, client_secret, username and password in {args.config}")

    if args.dry_run:
        log.info("🔍 DRY RUN — messages will be printed, not sent to Telegram.")

    if args.watch:
        interval = cfg["scan"]["scan_interval_minutes"]
        log.info(f"👁  Watch mode — rescanning every {interval} min. Ctrl+C to stop.")
        while True:
            run_scan(cfg, reddit, dry_run=args.dry_run)
            log.info(f"💤  Sleeping {interval} min …")
            time.sleep(interval * 60)
    else:
        run_scan(cfg, reddit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
