from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from data.db_session import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    is_active = Column(Boolean, default=True)
    chat_id = Column(
        String,
        ForeignKey("telegram_chats.chat_id"),
        index=True,
        nullable=False
    )
    title = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)
    last_message_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Conversation {self.id} chat={self.chat_id}>"
