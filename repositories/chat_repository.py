"""Persistence boundary for conversations and messages."""
from sqlalchemy.orm import Session

from models import ChatConversation, ChatMessage


class ChatRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_owned(self, conversation_id: int, user_id: int) -> ChatConversation | None:
        return self.db.query(ChatConversation).filter(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user_id,
        ).first()

    def messages(self, conversation: ChatConversation) -> list[ChatMessage]:
        return self.db.query(ChatMessage).filter(
            ChatMessage.conversation_id == conversation.id
        ).order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc()).all()

    def create(self, user_id: int) -> ChatConversation:
        conversation = ChatConversation(user_id=user_id, title="Cuộc trò chuyện mới")
        self.db.add(conversation)
        self.db.flush()
        return conversation

    def add_message(self, conversation: ChatConversation, role: str, content: str) -> ChatMessage:
        message = ChatMessage(conversation_id=conversation.id, role=role, content=content)
        self.db.add(message)
        self.db.flush()
        return message
