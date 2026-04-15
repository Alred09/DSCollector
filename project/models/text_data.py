from sqlalchemy import Column, Integer, String, DateTime, Text, Float, ForeignKey
from project.data.db_session import Base


class TextData(Base):
    __tablename__ = 'text_data'

    id = Column(Integer, primary_key=True)
    text = Column(Text, nullable=False)
    chat_id = Column(String, index=True)
    created_at = Column(DateTime)
    author = Column(String)
    source = Column(String)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), index=True)

    def __repr__(self):
        return f"<TextData {self.id} [{self.source}] {self.sentiment}:{self.sentiment_confidence:.2f}>"