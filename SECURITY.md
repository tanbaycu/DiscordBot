# Security Policy

- Never disable TLS certificate validation (`ssl.CERT_NONE`) when making outbound API requests.
- Gemini API keys are transmitted strictly via the `x-goog-api-key` HTTP header, never inside query URLs.
- Keep `DISCORD_TOKEN`, `GEMINI_API_KEY*`, and `GITHUB_TOKEN` exclusively inside `.env` or secret managers.
- Report security issues privately via GitHub Security Advisories on `tanbaycu/DiscordBot`.
