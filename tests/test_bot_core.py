import ast
from pathlib import Path

from ai_client import AsyncGeminiClient, GeminiKeyRotator, get_gemini_endpoint
from memory_store import MemoryStore


def test_gemini_rotator_and_header_auth():
    rotator = GeminiKeyRotator(["key_one", "key_two"])
    assert rotator.get_current_key() == "key_one"
    assert rotator.switch_to_next_key() == "key_two"

    rotator.mark_rate_limited("key_one", cooldown_seconds=30.0)
    assert rotator.is_rate_limited("key_one") is True

    client = AsyncGeminiClient(rotator=rotator, model="gemini-flash-latest")
    headers = client.build_request_headers("key_one")
    assert headers["x-goog-api-key"] == "key_one"
    endpoint = get_gemini_endpoint("gemini-flash-latest")
    assert "key_one" not in endpoint
    assert "gemini-flash-latest" in endpoint


def test_memory_store_isolates_discord_users(tmp_path):
    store = MemoryStore(db_path=str(tmp_path / "discord_mem.db"), short_limit=4)
    try:
        store.update("u1", "Mình thích nhạc lofi", "Okê bạn, để mình bật lofi!")
        store.update("u2", "Tớ thích chơi game", "Chơi game vui vẻ nhé!")

        ctx_u1 = store.get_context("u1")
        ctx_u2 = store.get_context("u2")
        assert "lofi" in ctx_u1
        assert "game" not in ctx_u1
        assert "game" in ctx_u2

        assert store.clear_short("u1") is True
        store.clear_all("u1")
        assert store.get_context("u1") == ""
        assert "game" in store.get_context("u2")
    finally:
        store.close()


def test_bot_and_music_modules_clean_tls_and_syntax():
    root = Path(__file__).resolve().parent.parent
    for fname in ("bot.py", "music_system.py", "ai_client.py", "memory_store.py"):
        src = (root / fname).read_text(encoding="utf-8")
        ast.parse(src)
        assert "CERT_NONE" not in src
        assert "nocheckcertificate" not in src

    import bot as discord_bot
    import music_system

    assert hasattr(discord_bot, "ai_client")
    assert hasattr(music_system.Music, "music_stats")
