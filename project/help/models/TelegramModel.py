from sqlalchemy import Column, String, Boolean, Integer, DateTime
from project.data.db_session import Base


class TelegramChat(Base):
    __tablename__ = 'telegram_chats'

    id = Column(Integer, primary_key=True)
    chat_id = Column(String, unique=True, nullable=False)
    title = Column(String)
    user_id = Column(String) #кем добавлен чат и кому он доступен
    is_active = Column(Boolean, default=False)
    chat_type = Column(String)  # Добавляем новое поле
    created_at = Column(DateTime)

    def __repr__(self):
        return f"TelegramChat(id={self.id}, title='{self.title}')"
