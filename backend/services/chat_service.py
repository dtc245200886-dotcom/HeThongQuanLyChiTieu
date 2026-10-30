"""Question -> facts -> prompt -> AI provider -> validation -> persistence."""
from datetime import datetime
import logging
import os
from sqlalchemy.orm import Session

from backend.repositories.chat_repository import ChatRepository
from backend.services.financial_analyzer import analyze_finances, analyze_system
from backend.services.openai_service import OpenAIService
from backend.services.prompt_builder import build_prompt
from backend.services.question_parser import parse_question
from backend.services.response_validator import validate_response
from backend.services.gemini_service import ask_gemini, ask_gemini_with_image

MAX_MESSAGES = int(os.getenv("MAX_CHAT_MESSAGES", "100"))
MAX_TOKENS = int(os.getenv("MAX_CHAT_TOKENS", "50000"))
FALLBACK_NOTICE = "AI nâng cao hiện tạm thời không khả dụng. Hệ thống đang sử dụng dữ liệu tài chính nội bộ để hỗ trợ bạn."
logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _title(question: str) -> str:
    clean = " ".join(question.split()).strip(" .!?;:")
    return clean[:57] + "..." if len(clean) > 60 else clean


def _fallback_financial_response(question: str, facts: dict, is_admin: bool) -> str:
    """Answer common finance questions from database facts when Gemini fails."""
    if is_admin or facts.get("private_data_access") is False:
        return (
            f"{FALLBACK_NOTICE}\n\n"
            f"Số liệu hệ thống: {facts.get('total_users', 0)} người dùng, "
            f"{facts.get('total_transactions', 0)} giao dịch, "
            f"{facts.get('ai_requests', 0)} lượt sử dụng AI."
        )
    normalized = question.lower()
    period = f"{facts.get('start_date')} đến {facts.get('end_date')}"
    answer = [FALLBACK_NOTICE, f"Khoảng thời gian: {period}"]
    if any(term in normalized for term in ("mục tiêu", "tiết kiệm", "du lịch")):
        goals = facts.get("saving_goals", [])
        if goals:
            answer.append("Mục tiêu tiết kiệm:")
            answer.extend(
                f"• {goal['name']}: {goal['current_amount']:,.0f}đ / {goal['target_amount']:,.0f}đ ({goal['progress_percent']}%)"
                + (f"; vượt {goal['over_amount']:,.0f}đ" if goal['over_amount'] else "")
                for goal in goals
            )
        else:
            answer.append("Bạn chưa có mục tiêu tiết kiệm nào.")
    elif any(term in normalized for term in ("nhiều nhất", "danh mục")):
        top = facts.get("top_categories", [])
        answer.append("Danh mục chi nhiều nhất: " + (f"{top[0]['name']} ({top[0]['amount']:,.0f}đ)." if top else "Chưa có dữ liệu."))
    elif any(term in normalized for term in ("ngân sách", "vượt")):
        budgets = facts.get("budgets", [])
        answer.append("Ngân sách: " + ("; ".join(f"{item['category']} còn {item['remaining']:,.0f}đ ({item['percent']}%)" for item in budgets) if budgets else "Bạn chưa thiết lập ngân sách."))
    elif any(term in normalized for term in ("thu chi", "báo cáo", "tổng")):
        answer.append(f"• Tổng thu: {facts.get('income', 0):,.0f}đ\n• Tổng chi: {facts.get('expense', 0):,.0f}đ\n• Số dư: {facts.get('balance', 0):,.0f}đ\n• Tỷ lệ tiết kiệm: {facts.get('saving_rate', 0)}%")
    else:
        answer.append(f"• Tổng thu: {facts.get('income', 0):,.0f}đ\n• Tổng chi: {facts.get('expense', 0):,.0f}đ\n• Số dư: {facts.get('balance', 0):,.0f}đ")
    return "\n\n".join(answer)


def answer_chat(db: Session, user_id: int, conversation_id: int, question: str, is_admin: bool = False, image_bytes: bytes | None = None, image_mime_type: str | None = None) -> dict:
    content = question.strip()
    if not content and not image_bytes:
        raise ValueError("Tin nhắn không được để trống")
    provider = os.getenv("AI_PROVIDER", "mock").strip().lower()
    if provider not in ("mock", "gemini", "openai"):
        raise RuntimeError("AI_PROVIDER must be one of: mock, gemini, openai.")
    if image_bytes and provider != "gemini":
        raise ValueError("Phân tích ảnh hiện chỉ hỗ trợ AI_PROVIDER=gemini.")
    prompt_content = content or "Hãy phân tích nội dung trong ảnh này."

    repository = ChatRepository(db)
    conversation = repository.create(user_id) if conversation_id == 0 else repository.get_owned(conversation_id, user_id)
    if conversation is None:
        raise LookupError("Không tìm thấy cuộc trò chuyện")

    previous = repository.messages(conversation)
    if len(previous) + 2 > MAX_MESSAGES:
        raise OverflowError("Cuộc trò chuyện đã quá dài, vui lòng tạo cuộc trò chuyện mới.")
    history_text = "".join(message.content for message in previous)
    if _estimate_tokens(history_text) + _estimate_tokens(prompt_content) > MAX_TOKENS:
        raise OverflowError("Cuộc trò chuyện đã quá dài, vui lòng tạo cuộc trò chuyện mới.")

    parsed = parse_question(prompt_content)
    facts = analyze_system(db, parsed) if is_admin else analyze_finances(db, user_id, parsed)
    history = [{"role": message.role, "content": message.content} for message in previous[-12:]]
    messages = build_prompt(prompt_content, parsed, facts, history)
    prompt = "\n\n".join(f"{item['role']}: {item['content']}" for item in messages)
    active_provider = provider
    if provider == "mock":
        response = _fallback_financial_response(prompt_content, facts, is_admin)
        source = "System" if is_admin else "Fallback"
    else:
        source = "AI"
        try:
            if provider == "gemini":
                response = (
                    ask_gemini_with_image(prompt, image_bytes, image_mime_type)
                    if image_bytes
                    else ask_gemini(prompt)
                )
            else:
                response = OpenAIService().complete(messages)
        except Exception as exc:
            logger.warning(
                "%s failed; using financial fallback for user_id=%s (error_type=%s)",
                provider,
                user_id,
                type(exc).__name__,
            )
            response = _fallback_financial_response(prompt_content, facts, is_admin)
            source = "System" if is_admin else "Fallback"
            active_provider = "local-fallback"
    response = validate_response(response, facts)
    stored_content = content if content else "[Ảnh đính kèm]"
    if image_bytes and content:
        stored_content = "[Ảnh đính kèm]\n" + content
    if _estimate_tokens(history_text + stored_content + response) > MAX_TOKENS:
        raise OverflowError("Cuộc trò chuyện đã quá dài, vui lòng tạo cuộc trò chuyện mới.")

    user_message = repository.add_message(conversation, "user", stored_content)
    assistant_message = repository.add_message(conversation, "assistant", response)
    if conversation.title == "Cuộc trò chuyện mới":
        conversation.title = _title(content) if content else "Phân tích ảnh"
    conversation.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)
    return {
        "conversation_id": conversation.id,
        "title": conversation.title,
        "user_message": user_message,
        "assistant_message": assistant_message,
        "facts": facts,
        "source": source,
        "provider": active_provider,
    }
