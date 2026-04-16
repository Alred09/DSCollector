from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from datetime import datetime, timedelta
from .db_session import create_session
from models.TelegramModel import TelegramChat
import logging
import random
import string
from typing import Dict, Optional
from models.users import User
from models.text_data import TextData
from models.Conversation import Conversation


class TelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.active_verifications: Dict[int, dict] = {}  # {user_id: {code: str, expires_at: datetime}}
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO
        )
        self.logger = logging.getLogger(__name__)

    def clean_expired_codes(self):
        """Очищает просроченные коды верификации"""
        now = datetime.now()
        expired_users = [
            user_id for user_id, data in self.active_verifications.items()
            if data["expires_at"] < now
        ]
        for user_id in expired_users:
            del self.active_verifications[user_id]
            self.logger.debug(f"Cleared expired code for user {user_id}")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        user = update.effective_user

        # ===== ЛИЧНЫЕ =====
        if chat.type == "private":
            await update.message.reply_text(
                "🔐 Привязка Telegram к сайту:\n"
                "1. На сайте нажмите 'Привязать Telegram'\n"
                "2. Получите код\n"
                "3. Отправьте его командой:\n"
                "/verify КОД\n\n"

                "🔑 Команды:\n"
                "/verify <код>\n"
                "/code\n"
            )
            return

        # ===== ГРУППЫ =====
        db = create_session()
        try:
            chat_in_db = db.query(TelegramChat).filter_by(
                chat_id=str(chat.id)
            ).first()

            # 👉 ЕСЛИ ЧАТ УЖЕ ЕСТЬ
            if chat_in_db:
                await update.message.reply_text(
                    "📊 Информация о чате:\n\n"
                    f"🆔 ID: {chat.id}\n"
                    f"📛 Название: {chat.title}\n"
                    f"⚙ Статус: {'Активен' if chat_in_db.is_active else 'Неактивен'}\n\n"

                    "📜 Команды:\n"
                    "/chat_id — инфо о чате\n"
                    "/last10 — последние сообщения\n"
                    "/del_last — удалить последнее сообщение\n"
                    "/start_conversation — начать диалог\n"
                    "/end_conversation — завершить диалог\n"
                )
                return

            # 👉 ЕСЛИ ЧАТА НЕТ — РЕГИСТРАЦИЯ
            await self._register_new_chat(chat, user, update)

        finally:
            db.close()

    async def verify(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик верификации кода"""
        if update.message.chat.type != "private":
            return

        self.clean_expired_codes()
        user_id = update.message.from_user.id
        args = context.args

        if not args or len(args[0]) != 6:
            await update.message.reply_text("❌ Код должен состоять из 6 символов. Пример: /verify A1B2C3")
            return

        code = args[0].upper()
        db = create_session()

        try:
            # Ищем пользователя с таким кодом
            user = db.query(User).filter(
                User.telegram_verify_code == code,
                User.telegram_code_expires > datetime.now()
            ).first()

            if user:
                if user.telegram_id and user.telegram_id != user_id:
                    await update.message.reply_text(
                        "❌ Этот код уже используется другим аккаунтом Telegram"
                    )
                    return

                user.telegram_id = user_id
                user.is_telegram_verified = True
                user.telegram_verify_code = None
                user.telegram_code_expires = None
                db.commit()

                await update.message.reply_text(
                    "✅ Ваш Telegram успешно привязан к аккаунту!\n\n"
                    f"Привязанный аккаунт: {user.email or user.name}"
                )
            else:
                await update.message.reply_text("❌ Неверный или просроченный код")

        except Exception as e:
            db.rollback()
            self.logger.error(f"Ошибка при верификации: {e}")
            await update.message.reply_text("⚠ Произошла ошибка при обработке запроса")

        finally:
            db.close()

    async def get_verification_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Генерирует и возвращает код верификации (только для ЛС)"""
        if update.message.chat.type != "private":
            return

        self.clean_expired_codes()  # Очищаем просроченные коды

        user_id = update.message.from_user.id

        # Если у пользователя уже есть активный код
        if user_id in self.active_verifications:
            code_data = self.active_verifications[user_id]
            await update.message.reply_text(
                f"У вас уже есть активный код: {code_data['code']}\n"
                f"⏳ Действует до: {code_data['expires_at'].strftime('%H:%M:%S')}\n\n"
                f"Используйте его на сайте или дождитесь истечения срока."
            )
            return

        code = self.generate_verification_code()
        expires_at = datetime.now() + timedelta(minutes=3)

        self.active_verifications[user_id] = {
            "code": code,
            "expires_at": expires_at
        }

        self.logger.info(f"Generated verification code {code} for user {user_id}")

        await update.message.reply_text(
            f"🔑 Ваш код верификации: {code}\n"
            f"⏳ Действует до: {expires_at.strftime('%H:%M:%S')}\n\n"
            f"Введите его на сайте для привязки аккаунта."
        )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message

        # ❌ игнорируем ботов
        if message.from_user.is_bot:
            return

        chat_id = str(update.effective_chat.id)
        db = create_session()

        try:
            # 1. проверяем чат + включенность
            chat = db.query(TelegramChat).filter_by(chat_id=chat_id).first()

            if not chat or not chat.is_active or not getattr(chat, "bot_enabled", True):
                return

            # 2. ищем АКТИВНЫЙ диалог (ONLY READ, NO CREATE)
            conversation = (
                db.query(Conversation)
                .filter_by(chat_id=chat_id, is_active=True)
                .order_by(Conversation.id.desc())
                .first()
            )

            # ❌ нет диалога → игнор
            if conversation is None:
                return

            # 3. пишем сообщение в диалог
            db.add(TextData(
                text=message.text,
                source="telegram",
                chat_id=chat_id,
                conversation_id=conversation.id,
                author=str(message.from_user.id),
                created_at=datetime.now()
            ))

            # 4. обновляем метаданные диалога
            conversation.last_message_at = datetime.now()

            db.commit()

        except Exception as e:
            db.rollback()
            self.logger.error(f"Ошибка сохранения сообщения: {e}")

        finally:
            db.close()

    async def get_chat_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда для получения ID чата"""
        chat = update.effective_chat
        await update.message.reply_text(
            f"ID этого чата: {chat.id}\n"
            f"Тип чата: {'группа' if chat.type in ['group', 'supergroup'] else 'личный'}\n"
            f"Название: {getattr(chat, 'title', 'нет')}"
        )

    async def _register_new_chat(self, chat, user, update):
        """Регистрация нового чата в БД"""
        db = create_session()

        try:
            if chat.type == "private":
                title_parts = []
                if user.first_name:
                    title_parts.append(user.first_name)
                if user.last_name:
                    title_parts.append(user.last_name)
                title = ' '.join(title_parts) if title_parts else f"Пользователь {chat.id}"

                if hasattr(user, 'username') and user.username:
                    title += f" (@{user.username})"
            else:
                title = chat.title if hasattr(chat, 'title') and chat.title else f'Чат {chat.id}'

            new_chat = TelegramChat(
                chat_id=str(chat.id),
                title=title,
                user_id=user.id,
                is_active=False,
                chat_type=chat.type,
                created_at=datetime.now()
            )

            db.add(new_chat)
            db.commit()

            response = (
                f"🎉 Чат успешно зарегистрирован!\n"
                f"ID: {chat.id}\n"
                f"Тип: {'Личные сообщения' if chat.type == 'private' else 'Группа/Канал'}\n"
                f"Название: {title}\n\n"
                f"Для активации парсинга перейдите в панель управления."
            )

        except Exception as e:
            db.rollback()
            response = f"❌ Ошибка регистрации чата: {str(e)}"
            self.logger.error(f"Chat registration error: {str(e)}", exc_info=True)

        await update.message.reply_text(response)

    async def on_chat_join(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик добавления бота в чат"""
        chat = update.effective_chat
        user = update.effective_user
        db = create_session()

        if not db.query(TelegramChat).filter_by(chat_id=str(chat.id)).first():
            title = chat.title if chat.type in ['group', 'supergroup', 'channel'] else user.full_name

            new_chat = TelegramChat(
                chat_id=str(chat.id),
                title=title,
                user_id=str(user.id),
                is_active=False,
                chat_type=chat.type,
                created_at=datetime.now()
            )

            db.add(new_chat)
            db.commit()

            response_msg = (
                f"Чат {'группы' if chat.type != 'private' else 'ЛС'} "
                f"добавлен: {title}\n"
                f"Активируйте парсинг в панели управления."
            )

            await update.message.reply_text(response_msg)

    async def delete_last_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        db = create_session()

        try:
            conversation = (
                db.query(Conversation)
                .filter_by(chat_id=chat_id, is_active=True)
                .first()
            )

            if not conversation:
                await update.message.reply_text("❌ Активного диалога нет")
                return

            last_msg = (
                db.query(TextData)
                .filter_by(conversation_id=conversation.id)
                .order_by(TextData.id.desc())
                .first()
            )

            if not last_msg:
                await update.message.reply_text("❌ Сообщений в диалоге нет")
                return

            db.delete(last_msg)
            db.commit()

            # 🔥 обновляем состояние диалога
            new_last = (
                db.query(TextData)
                .filter_by(conversation_id=conversation.id)
                .order_by(TextData.id.desc())
                .first()
            )

            conversation.last_message_at = new_last.created_at if new_last else None
            db.commit()

            await update.message.reply_text(
                f"🗑 Удалено сообщение из диалога {conversation.id}"
            )

        except Exception as e:
            db.rollback()
            self.logger.error(f"Ошибка удаления: {e}")
            await update.message.reply_text("⚠ Ошибка удаления")

        finally:
            db.close()

    async def get_last_10_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        db = create_session()

        try:
            conversation = (
                db.query(Conversation)
                .filter_by(chat_id=chat_id, is_active=True)
                .first()
            )

            if not conversation:
                await update.message.reply_text("📭 Активного диалога нет")
                return

            messages = (
                db.query(TextData)
                .filter_by(conversation_id=conversation.id)
                .order_by(TextData.id.asc())
                .limit(10)
                .all()
            )

            if not messages:
                await update.message.reply_text("📭 Сообщений нет")
                return

            text = f"📜 Последние 10 сообщений (диалог {conversation.id}):\n\n"

            for m in messages:
                time = m.created_at.strftime("%H:%M:%S") if m.created_at else "??"
                text += f"[{time}] {m.author}: {m.text}\n"

            await update.message.reply_text(text)

        except Exception as e:
            self.logger.error(f"Ошибка получения сообщений: {e}")
            await update.message.reply_text("⚠ Ошибка")

        finally:
            db.close()

    async def start_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        db = create_session()

        try:
            # 🔥 проверяем есть ли активный диалог
            active_conv = (
                db.query(Conversation)
                .filter_by(chat_id=chat_id, is_active=True)
                .first()
            )

            if active_conv:
                await update.message.reply_text(
                    "⚠ Уже есть активный диалог!\n\n"
                    f"ID: {active_conv.id}\n\n"
                    "❗ Сначала завершите текущий диалог командой:\n"
                    "/end_conversation"
                )
                return

            # 🟢 создаём новый диалог
            new_conv = Conversation(
                chat_id=chat_id,
                title="New conversation",
                created_at=datetime.now(),
                last_message_at=datetime.now(),
                is_active=True
            )

            db.add(new_conv)
            db.commit()

            await update.message.reply_text(
                f"🟢 Новый диалог начат\n"
                f"ID: {new_conv.id}"
            )

        except Exception as e:
            db.rollback()
            self.logger.error(f"Start conversation error: {e}")
            await update.message.reply_text("⚠ Ошибка создания диалога")

        finally:
            db.close()

    async def end_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        db = create_session()

        try:
            conv = (
                db.query(Conversation)
                .filter_by(chat_id=chat_id, is_active=True)
                .order_by(Conversation.id.desc())
                .first()
            )

            if not conv:
                await update.message.reply_text("❌ Активного диалога нет")
                return

            conv.is_active = False
            db.commit()

            await update.message.reply_text(
                f"🔴 Диалог завершён\n"
                f"ID: {conv.id}"
            )

        except Exception as e:
            db.rollback()
            self.logger.error(f"End conversation error: {e}")
            await update.message.reply_text("⚠ Ошибка завершения диалога")

        finally:
            db.close()

    def run(self):
        """Запуск бота"""
        app = Application.builder().token(self.token).build()

        # Добавляем обработчики команд
        handlers = [
            CommandHandler("start", self.start),
            CommandHandler("chat_id", self.get_chat_id),
            CommandHandler("verify", self.verify),
            CommandHandler("start_conversation", self.start_conversation),
            CommandHandler("end_conversation", self.end_conversation),
            CommandHandler("del_last", self.delete_last_message),
            CommandHandler("last10", self.get_last_10_messages),

            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message),
            MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, self.on_chat_join)
        ]

        for handler in handlers:
            app.add_handler(handler)

        self.logger.info("Бот запущен и готов к работе!")
        app.run_polling()

