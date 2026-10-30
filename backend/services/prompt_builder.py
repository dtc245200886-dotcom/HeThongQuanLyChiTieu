"""Build a grounded prompt: the model receives facts, not raw database access."""
import json

from backend.services.question_parser import ParsedQuestion


def build_prompt(question: str, parsed: ParsedQuestion, facts: dict, history: list[dict]) -> list[dict]:
    system = (
        "Bạn là trợ lý AI của ứng dụng quản lý chi tiêu. Hãy trả lời đúng câu hỏi hiện tại "
        "bằng tiếng Việt hoặc ngôn ngữ người dùng đang sử dụng. Nếu câu hỏi là kiến thức "
        "chung hoặc không liên quan tài chính, hãy trả lời trực tiếp theo nội dung câu hỏi "
        "và không ép câu trả lời thành báo cáo tài chính. Nếu câu hỏi liên quan đến chi tiêu, "
        "ngân sách, giao dịch hoặc tiết kiệm, hãy dùng FINANCIAL_FACTS làm nguồn dữ liệu duy nhất "
        "cho các con số; không tự bịa số liệu. Với câu hỏi tài chính, nêu rõ khoảng thời gian "
        "và cảnh báo budget_alerts nếu có. Không đưa lời khuyên đầu tư hoặc cam kết tài chính. "
        "ADMIN_FACTS chỉ chứa số liệu tổng hợp hệ thống và không được suy diễn thành dữ liệu cá nhân."
    )
    context = json.dumps(facts, ensure_ascii=False)
    messages = [{"role": "system", "content": system}]
    messages.extend(history[-12:])
    messages.append({
        "role": "user",
        "content": (
            f"FINANCIAL_FACTS={context}\n"
            f"INTENT_HINT={parsed.intent}\n"
            f"USER_QUESTION={question}"
        ),
    })
    return messages
