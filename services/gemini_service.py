"""Gemini Flash service with retry handling for temporary overloads."""
import logging
import os
import time

from dotenv import load_dotenv
from google import genai

load_dotenv()

logger = logging.getLogger(__name__)


class GeminiServiceError(RuntimeError):
    """Raised when Gemini cannot generate a response."""

    def __init__(self, message: str, *, category: str = "unknown", status_code=None, original_type: str = ""):
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.original_type = original_type


def _error_details(exc: Exception) -> tuple[str, str, int | None, str]:
    message = str(exc) or repr(exc)
    error_type = type(exc).__name__
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    try:
        status_code = int(status_code) if status_code is not None and int(status_code) in range(100, 600) else None
    except (TypeError, ValueError):
        status_code = None
    normalized = message.upper()
    if status_code in (401, 403) or any(term in normalized for term in ("API KEY", "API_KEY", "INVALID_ARGUMENT", "PERMISSION_DENIED", "UNAUTHENTICATED")):
        category = "invalid_api_key_or_permission"
    elif status_code == 429 or any(term in normalized for term in ("QUOTA", "RATE LIMIT", "RESOURCE_EXHAUSTED", "TOO MANY REQUESTS")):
        category = "quota_or_rate_limit"
    elif status_code == 503 or any(term in normalized for term in ("UNAVAILABLE", "HIGH DEMAND", "OVERLOADED", "SERVICE UNAVAILABLE")):
        category = "service_unavailable"
    else:
        category = "unknown"
    return category, error_type, status_code, message


def _log_gemini_error(exc: Exception, operation: str, attempt: int) -> tuple[bool, str]:
    category, error_type, status_code, message = _error_details(exc)
    logger.warning(
        "Gemini API error | operation=%s | category=%s | status_code=%s | attempt=%s | error_type=%s",
        operation, category, status_code, attempt, error_type,
    )
    return category == "service_unavailable", category


def _create_client() -> tuple[genai.Client, str]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        error = "Chưa cấu hình GEMINI_API_KEY trong file .env"
        logger.error(error)
        raise GeminiServiceError(error)

    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    logger.info(
        "Initializing Gemini client | sdk=google-genai | model=%s | api_key_configured=true",
        model,
    )
    return genai.Client(api_key=api_key), model


def ask_gemini(prompt: str) -> str:
    """Send a prompt to Gemini Flash and return ``response.text``."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Prompt không được để trống")

    client, model = _create_client()
    retry_delays = (2, 4, 8)

    for attempt in range(len(retry_delays) + 1):
        try:
            logger.info("Calling Gemini generate_content | operation=text | model=%s | attempt=%s", model, attempt + 1)
            response = client.models.generate_content(
                model=model,
                contents=prompt,
            )
            text = response.text
            if not text:
                raise GeminiServiceError("Gemini trả về response.text rỗng")
            logger.info("Gemini request succeeded | operation=text | model=%s", model)
            return text
        except GeminiServiceError:
            raise
        except Exception as exc:
            is_overloaded, category = _log_gemini_error(exc, "text", attempt + 1)
            if not is_overloaded or attempt == len(retry_delays):
                if is_overloaded:
                    raise GeminiServiceError(
                        "Gemini hiện không khả dụng sau khi đã thử lại.",
                        category="service_unavailable",
                        status_code=503,
                    ) from exc
                error_category, error_type, status_code, error_message = _error_details(exc)
                raise GeminiServiceError(
                    f"Gemini error [{error_category}] [{error_type}] status={status_code}: {error_message}",
                    category=error_category, status_code=status_code, original_type=error_type,
                ) from exc

            delay = retry_delays[attempt]
            logger.warning("Gemini overloaded; retrying in %s seconds", delay)
            time.sleep(delay)


def check_ai_connection() -> dict:
    """Check configured Gemini connectivity without exposing credentials."""
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    try:
        answer = ask_gemini("Trả lời đúng một từ: OK")
        if answer:
            return {"status": "online", "model": model, "message": "AI connected successfully"}
        return {"status": "offline", "error": "Gemini trả về phản hồi rỗng"}
    except Exception as exc:
        category, error_type, status_code, message = _error_details(exc)
        logger.warning(
            "AI connection check failed | category=%s | status=%s | error_type=%s",
            category,
            status_code,
            error_type,
        )
        return {"status": "offline", "model": model, "error": f"{category}: {error_type} ({status_code})"}


def ask_gemini_with_image(prompt: str, image_bytes: bytes, mime_type: str) -> str:
    """Send text plus one uploaded image to Gemini Vision."""
    if not image_bytes:
        raise ValueError("Ảnh tải lên không có dữ liệu")
    client, model = _create_client()
    retry_delays = (2, 4, 8)
    contents = [prompt, genai.types.Part.from_bytes(data=image_bytes, mime_type=mime_type)]
    for attempt in range(len(retry_delays) + 1):
        try:
            logger.info("Calling Gemini generate_content | operation=vision | model=%s | attempt=%s", model, attempt + 1)
            response = client.models.generate_content(model=model, contents=contents)
            text = response.text
            if not text:
                raise GeminiServiceError("Gemini trả về response.text rỗng")
            logger.info("Gemini request succeeded | operation=vision | model=%s", model)
            return text
        except GeminiServiceError:
            raise
        except Exception as exc:
            is_overloaded, category = _log_gemini_error(exc, "vision", attempt + 1)
            if not is_overloaded or attempt == len(retry_delays):
                if is_overloaded:
                    raise GeminiServiceError(
                        "Gemini Vision hiện không khả dụng sau khi đã thử lại.",
                        category="service_unavailable",
                        status_code=503,
                    ) from exc
                error_category, error_type, status_code, error_message = _error_details(exc)
                raise GeminiServiceError(
                    f"Gemini Vision error [{error_category}] [{error_type}] status={status_code}: {error_message}",
                    category=error_category, status_code=status_code, original_type=error_type,
                ) from exc
            time.sleep(retry_delays[attempt])


def _is_overload_error(exc: Exception, message: str) -> bool:
    """Recognize Gemini 503/UNAVAILABLE/high-demand responses."""
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    normalized = message.upper()
    return (
        status_code == 503
        or "503" in normalized
        or "UNAVAILABLE" in normalized
        or "HIGH DEMAND" in normalized
        or "OVERLOADED" in normalized
    )