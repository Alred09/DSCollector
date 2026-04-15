from sqlalchemy import Column, Integer, String, DateTime, Text, Float
from project.data.db_session import Base


class TextData(Base):
    __tablename__ = 'text_data'

    id = Column(Integer, primary_key=True)
    text = Column(Text, nullable=False)
    chat_id = Column(String, index=True)
    sentiment = Column(String)  # 'positive', 'neutral', 'negative'
    sentiment_confidence = Column(Float)  # 0.0 - 1.0
    created_at = Column(DateTime)
    author = Column(String)
    source = Column(String)

    def __repr__(self):
        return f"<TextData {self.id} [{self.source}] {self.sentiment}:{self.sentiment_confidence:.2f}>"