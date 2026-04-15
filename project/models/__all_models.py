# Явно импортируем все модели
from .users import User
from .TelegramModel import TelegramChat
from .text_data import TextData

__all__ = ['User', 'TelegramChat', 'TextData']