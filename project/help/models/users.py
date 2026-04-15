from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import relationship
from project.data.db_session import Base
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import  datetime, timedelta
import random
import string


class User(Base, UserMixin):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=True)
    email = Column(String, nullable=True, unique=True)
    hashed_password = Column(String, nullable=True)
    telegram_id = Column(Integer, unique=True, nullable=True)
    is_telegram_verified = Column(Boolean, default=False)
    telegram_verify_code = Column(String, nullable=True)
    telegram_code_expires = Column(DateTime, nullable=True)

    def set_password(self, password):
        self.hashed_password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.hashed_password, password)

    def generate_telegram_code(self):
        chars = string.ascii_uppercase + string.digits
        self.telegram_verify_code = ''.join(random.choice(chars) for _ in range(6))
        self.telegram_code_expires = datetime.now() + timedelta(minutes=3)
        return self.telegram_verify_code

    def verify_telegram_code(self, code):
        if (self.telegram_verify_code == code and
            self.telegram_code_expires > datetime.now()):
            self.is_telegram_verified = True
            self.telegram_verify_code = None
            self.telegram_code_expires = None
            return True
        return False