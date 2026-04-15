import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Session
from sqlalchemy import text

Base = orm.declarative_base() #абстрактную декларативную базу, в которую позднее будем наследовать все наши модели

__factory = None #для получения сессий подключения к нашей базе данных


def global_init(db_file):
    global __factory

    if __factory:
        return

    if not db_file or not db_file.strip():
        raise Exception("Необходимо указать файл базы данных.")

    conn_str = f'sqlite:///{db_file.strip()}?check_same_thread=False'
    #print(f"Подключение к базе данных по адресу {conn_str}")

    engine = sa.create_engine(conn_str)  # Включим echo для отладки
    __factory = orm.sessionmaker(bind=engine)

    # Явный импорт моделей
    from project.models.__all_models import User, TelegramChat, TextData

    Base.metadata.create_all(engine)


def create_session() -> Session:
    global __factory
    return __factory()

