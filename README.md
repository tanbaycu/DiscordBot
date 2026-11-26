# DiscordBot v2.0

[![CI](https://github.com/tanbaycu/DiscordBot/actions/workflows/ci.yml/badge.svg)](https://github.com/tanbaycu/DiscordBot/actions/workflows/ci.yml)
[![CodeQL](https://github.com/tanbaycu/DiscordBot/actions/workflows/codeql.yml/badge.svg)](https://github.com/tanbaycu/DiscordBot/actions/workflows/codeql.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Modular Discord AI & Music Bot powered by Google Gemini (`gemini-flash-latest`), per-user SQLite memory, yt-dlp audio streaming, and server moderation tools.**

---

## Highlights (v2.0)

- **Hardened AI Client (`ai_client.py`)**: Enforces TLS certificate verification, transmits Gemini keys via `x-goog-api-key` headers (never in query URLs), and supports automatic key rotation on HTTP 429.
- **Persistent SQLite Memory (`memory_store.py`)**: Thread-safe, per-user short-term and long-term conversation context stored under `data/bot_memory.db`.
- **Music Cog (`music_system.py`)**: Voice playback via `yt-dlp` + FFmpeg with queue, loop, volume, search cache, auto-disconnect, and fixed `/musicstats`.
- **Server Moderation & Utilities (`bot.py`)**: `/ping`, `/helpme`, `/kick`, `/ban`, `/warning`, `/fact`, `/quote`, `/randomimage`.

---

## Quickstart

```bash
git clone https://github.com/tanbaycu/DiscordBot.git
cd DiscordBot
pip install -r requirements.txt
cp .env.example .env
# Set DISCORD_TOKEN and GEMINI_API_KEY in .env
python bot.py
```

### Docker

```bash
docker build -t discordbot:2.0 .
docker run --env-file .env -v $(pwd)/data:/app/data discordbot:2.0
```

---

## Testing

```bash
pip install -r requirements-dev.txt
ruff check .
pytest -v
```

Licensed under the [MIT License](LICENSE). See [SECURITY.md](SECURITY.md) for security notes.
