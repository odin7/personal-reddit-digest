# Reddit Keyword Scanner → Telegram Notifier

A lightweight Python script that monitors Reddit subreddits for keywords and sends matching posts to your Telegram chat. Uses the official **Reddit Data API** (via PRAW + OAuth2) and requires no third-party data services.

---

## Features

- Monitors multiple subreddits simultaneously
- Matches keywords in post titles and optionally post bodies
- Sends richly formatted Telegram notifications with post metadata
- Deduplicates across runs — never notifies you about the same post twice
- Supports one-shot scans or continuous watch mode
- Dry-run mode for testing without sending messages
- Simple YAML config — no code changes needed to adjust subreddits or keywords

---

## Requirements

- Python 3.10+
- A Reddit account with an approved API app
- A Telegram bot

Install dependencies:

```bash
pip install praw pyyaml requests
```

---

## Reddit Setup

### 1. Register your app

Go to [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) and click **Create App** (requires Reddit's Responsible Builder Policy approval — see note below).

Fill in the form:

| Field | Value |
|---|---|
| Name | `reddit_scanner` (or anything you like) |
| App type | **script** |
| Redirect URI | `http://localhost:8080` |

After creation you'll see:
- **Client ID** — the short string directly under your app name
- **Client Secret** — labeled "secret"

### 2. Responsible Builder Policy

As of November 2025, Reddit requires manual approval before you can create a new API app. When you click "Create App" you'll be directed to their [Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy). Submit the request form describing your personal/non-commercial use. Approval may take several days.

---

## Telegram Setup

### 1. Create a bot

1. Message **@BotFather** on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** it gives you (looks like `123456789:ABCdef...`)

### 2. Get your chat ID

1. Message **@userinfobot** on Telegram
2. It replies with your **chat ID** (a number like `123456789`)

---

## Configuration

Edit `config.yaml` before running:

```yaml
reddit:
  client_id: "YOUR_CLIENT_ID_HERE"
  client_secret: "YOUR_CLIENT_SECRET_HERE"
  username: "YOUR_REDDIT_USERNAME"
  password: "YOUR_REDDIT_PASSWORD"
  user_agent: "script:reddit_scanner:1.0 (by u/YOUR_REDDIT_USERNAME)"

telegram:
  bot_token: "YOUR_BOT_TOKEN_HERE"
  chat_id: "YOUR_CHAT_ID_HERE"
```

### Subreddits and keywords

```yaml
subreddits:
  - MachineLearning
  - LocalLLaMA
  - selfhosted

keywords:
  - claude
  - ollama
  - docker
```

A post matches if **any** keyword appears in the title (or body, if `search_in_body: true`). Matching is case-insensitive.

### All config options

| Key | Default | Description |
|---|---|---|
| `scan.posts_per_subreddit` | `25` | Recent posts to fetch per subreddit each scan |
| `scan.scan_interval_minutes` | `30` | Re-scan interval in `--watch` mode |
| `scan.search_in_body` | `true` | Also match keywords in post body/selftext |
| `filters.min_score` | `0` | Skip posts below this upvote score |
| `filters.exclude_flairs` | `[]` | Skip posts with these flair labels |
| `state_file` | `.reddit_scanner_state.json` | Tracks seen post IDs to prevent duplicates |

---

## Usage

```bash
# One-shot scan
python reddit_scanner.py

# Continuous mode — rescans on the interval set in config
python reddit_scanner.py --watch

# Dry run — prints matches to stdout, nothing sent to Telegram
python reddit_scanner.py --dry-run

# Use a custom config file
python reddit_scanner.py --config /path/to/my_config.yaml
```

On startup the script verifies your Reddit credentials and logs the authenticated username before scanning begins.

---

## Example Telegram notification

```
🔍 r/LocalLLaMA  ·  May 29, 14:32 UTC

📌 Running Mistral locally with Docker on a NAS
🏷 Discussion

👤 u/someuser  ·  ⬆️ 142  ·  💬 38

🔑 #docker #mistral #self_hosted

🔗 View on Reddit
🌐 External link
```

---

## Running continuously (on a server or NAS)

For 24/7 monitoring, run the script in watch mode on your server or NAS. A simple systemd service or `screen`/`tmux` session works well.

**With screen:**
```bash
screen -S reddit-scanner
python reddit_scanner.py --watch
# Detach with Ctrl+A, D
```

**With a cron job (alternative to --watch):**
```cron
*/30 * * * * cd /path/to/scanner && python reddit_scanner.py
```

The state file (`.reddit_scanner_state.json`) ensures no duplicates even when running via cron.

---

## File structure

```
.
├── reddit_scanner.py              # Main script
├── config.yaml                    # Your configuration
├── README.md                      # This file
└── .reddit_scanner_state.json     # Auto-created; tracks seen post IDs
```

---

## Rate limits

The free Reddit API tier allows 100 authenticated requests per minute. With the default config (25 posts × ~5 subreddits) each scan uses well under that. PRAW handles rate limit backoff automatically.

---

## License

MIT — personal use, modify freely.
