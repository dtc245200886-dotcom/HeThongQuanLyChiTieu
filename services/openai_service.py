"""Small OpenAI-compatible client using the existing httpx dependency."""
import os
import httpx


class OpenAIServiceError(RuntimeError):
    pass


class OpenAIService:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("AI_API_KEY", "")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.endpoint = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions")

    def complete(self, messages: list[dict]) -> str:
        if not self.api_key:
            raise OpenAIServiceError("Chưa cấu hình OPENAI_API_KEY")
        try:
            response = httpx.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "messages": messages, "temperature": 0.2},
                timeout=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30")),
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise OpenAIServiceError("OpenAI trả về nội dung rỗng")
            return content.strip()
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise OpenAIServiceError(f"OpenAI request failed: {exc}") from exc
