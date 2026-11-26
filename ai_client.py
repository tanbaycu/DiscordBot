import asyncio
import os
import time
from typing import Any, Dict, List, Optional

import aiohttp

DEFAULT_GEMINI_MODEL = "gemini-flash-latest"


def get_gemini_endpoint(model: Optional[str] = None) -> str:
    chosen = (model or os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()
    return f"https://generativelanguage.googleapis.com/v1beta/models/{chosen}:generateContent"


class GeminiKeyRotator:
    """Quản lý và xoay vòng nhiều Gemini API key khi gặp rate-limit (HTTP 429)."""

    def __init__(self, api_keys: Optional[List[str]] = None):
        if api_keys is None:
            candidates = [
                os.getenv("GEMINI_API_KEY"),
                os.getenv("GEMINI_API_KEY_1"),
                os.getenv("GEMINI_API_KEY_2"),
                os.getenv("GEMINI_API_KEY_3"),
            ]
            api_keys = [k.strip() for k in candidates if k and k.strip()]

        self.api_keys: List[str] = list(dict.fromkeys(api_keys))
        self.current_index = 0
        self.cooldowns: Dict[str, float] = {}

    @classmethod
    def from_env(cls) -> "GeminiKeyRotator":
        return cls(api_keys=None)

    def has_keys(self) -> bool:
        return len(self.api_keys) > 0

    def get_current_key(self) -> str:
        if not self.api_keys:
            raise ValueError("No Gemini API keys configured.")
        return self.api_keys[self.current_index]

    def switch_to_next_key(self) -> str:
        if not self.api_keys:
            raise ValueError("No Gemini API keys configured.")
        self.current_index = (self.current_index + 1) % len(self.api_keys)
        return self.api_keys[self.current_index]

    def mark_rate_limited(self, key: str, cooldown_seconds: float = 60.0) -> None:
        self.cooldowns[key] = time.time() + cooldown_seconds

    def is_rate_limited(self, key: str) -> bool:
        return time.time() < self.cooldowns.get(key, 0.0)


class AsyncGeminiClient:
    """Client gọi Gemini REST API bất đồng bộ qua header `x-goog-api-key` với xác thực TLS chuẩn."""

    def __init__(
        self,
        rotator: Optional[GeminiKeyRotator] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 30.0,
    ):
        self.rotator = rotator or GeminiKeyRotator.from_env()
        self.model = model or os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
        self.timeout_seconds = float(timeout_seconds)

    def build_request_headers(self, api_key: str) -> Dict[str, str]:
        # Truyền API key qua header thay vì query string để tránh lộ key trong access log/URL.
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }

    async def generate(
        self,
        prompt: str,
        system_instruction: str = "",
        max_tokens: int = 2048,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> str:
        if not self.rotator.has_keys():
            raise ValueError("Missing GEMINI_API_KEY configuration.")

        endpoint = get_gemini_endpoint(self.model)
        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.85,
                "topK": 50,
                "topP": 0.95,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        owns_session = session is None
        client_session = session or aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout_seconds)
        )

        try:
            attempts = max(2, len(self.rotator.api_keys) * 2)
            for attempt in range(attempts):
                key = self.rotator.get_current_key()
                if self.rotator.is_rate_limited(key) and len(self.rotator.api_keys) > 1:
                    self.rotator.switch_to_next_key()
                    continue

                headers = self.build_request_headers(key)
                try:
                    # Mặc định bật xác thực chứng chỉ TLS đầy đủ của hệ thống.
                    async with client_session.post(endpoint, headers=headers, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return (
                                data.get("candidates", [{}])[0]
                                .get("content", {})
                                .get("parts", [{}])[0]
                                .get("text", "")
                                .strip()
                            )
                        if resp.status == 429:
                            self.rotator.mark_rate_limited(key, 60.0)
                        elif resp.status == 503:
                            await asyncio.sleep(min(4.0, 1.0 * (attempt + 1)))
                except Exception:
                    if attempt == attempts - 1:
                        raise

                self.rotator.switch_to_next_key()

            return "xin lỗi, mình đang quá tải api một chút, bạn thử lại sau nhé"
        finally:
            if owns_session:
                await client_session.close()
