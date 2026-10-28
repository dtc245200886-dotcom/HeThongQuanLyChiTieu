"""Gemini API adapter with a deterministic fallback supplied by callers."""
import logging
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class AIServiceError(RuntimeError):
    pass


class GeminiService:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
        self.endpoint = os.getenv(
            "GEMINI_API_URL",
            "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        ).format(model=self.model)
        logger.info(
            "Initializing legacy Gemini REST client | model=%s | api_key_configured=%s",
            self.model,
            bool(self.api_key),
        )

    def generate(self, prompt: str) -> str:
        if not self.api_key:
            raise AIServiceError("Chưa cấu hình GEMINI_API_KEY")
        try:
            logger.info("Calling Gemini REST generateContent | model=%s", self.model)
            response = httpx.post(
                self.endpoint,
                headers={"x-goog-api-key": self.api_key},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=float(os.getenv("GEMINI_TIMEOUT_SECONDS", "30")),
            )
            response.raise_for_status()
            parts = response.json()["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts).strip()
            if not text:
                raise AIServiceError("Gemini trả về nội dung rỗng")
            return text
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise AIServiceError(f"Gemini request failed: {exc}") from exc


def generate_with_gemini(prompt: str, fallback: str) -> tuple[str, str]:
    try:
        return GeminiService().generate(prompt), "gemini"
    except AIServiceError:
        logger.exception("Gemini request failed; returning caller-supplied fallback")
        return fallback, "local-fallback"
