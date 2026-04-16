from flask import Flask, session, current_app, render_template, abort, flash, redirect, request, jsonify, make_response, url_for, Blueprint
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from functools import lru_cache
from multiprocessing import Process
from functools import wraps
from sqlalchemy.exc import SQLAlchemyError
from models.Conversation import Conversation

# 1. Сначала импортируем ВСЕ модели
from models.users import User
from models.text_data import TextData
from models.TelegramModel import TelegramChat


# 2. Потом всё остальное
from data.db_session import create_session, global_init
from data.telegram_parser import TelegramBot
from forms.profile_form import ProfileForm
from forms.user import RegisterForm, LoginForm
import os
import json
from datetime import datetime

# Отключаем предупреждения о resume_download
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="xformers")
warnings.filterwarnings("ignore", category=FutureWarning, module="huggingface_hub")


app = Flask(__name__)
bot = TelegramBot("7678402317:AAHMOuLh5-6V8itO-uBoLimJ4loxybbQzJY")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
app.config['SECRET_KEY'] = 'jsut_secret_key4519'

# 3. Только теперь инициализируем БД (модели уже загружены)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "db", "blogs.db")
global_init(DB_PATH)

login_manager = LoginManager()
login_manager.init_app(app)



@login_manager.user_loader
def load_user(user_id):
    db_sess = create_session()
    ret = db_sess.query(User).get(user_id)
    db_sess.close()
    return ret


@app.route('/register', methods=['GET', 'POST'])
def reqister():
    form = RegisterForm()
    if form.validate_on_submit():
        if form.password.data != form.password_again.data:
            return render_template('register.html', title='Регистрация',
                                   form=form,
                                   message="Пароли не совпадают")
        db_sess = create_session()
        if db_sess.query(User).filter(User.email == form.email.data).first():
            return render_template('register.html', title='Регистрация',
                                   form=form,
                                   message="Такой пользователь уже есть")
        user = User(
            name=form.name.data,
            email=form.email.data,
        )
        user.set_password(form.password.data)
        db_sess.add(user)
        db_sess.commit()
        db_sess.close()
        return redirect('/login')
    return render_template('register.html', title='Регистрация', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('collect_data'))

    form = LoginForm()
    if form.validate_on_submit():
        db_sess = create_session()
        user = db_sess.query(User).filter(User.email == form.email.data).first()

        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            session.pop('selected_source', None)  # Сбрасываем предыдущий выбор
            db_sess.close()
            return redirect(url_for('collect_data'))

        db_sess.close()
        flash('Неправильный логин или пароль', 'error')

    return render_template('login.html', form=form)


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileForm()
    db_sess = create_session()

    try:
        user = db_sess.query(User).filter(User.id == current_user.id).first()
        if not user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('profile'))

        if request.method == 'POST' and form.validate_on_submit():
            updated = False  # Флаг для отслеживания изменений

            # Обновление имени
            if form.name.data and form.name.data != user.name:
                user.name = form.name.data
                updated = True
                flash('Имя успешно обновлено', 'success')

            # Обновление email
            if form.email.data and form.email.data != user.email:
                if db_sess.query(User).filter(User.email == form.email.data, User.id != current_user.id).first():
                    flash('Этот email уже используется', 'error')
                else:
                    user.email = form.email.data
                    updated = True
                    flash('Email успешно обновлён', 'success')

            # Обновление пароля
            if form.current_password.data and form.new_password.data:
                if user.check_password(form.current_password.data):
                    user.set_password(form.new_password.data)
                    updated = True
                    flash('Пароль успешно изменён', 'success')
                else:
                    flash('Текущий пароль неверен', 'error')

            if updated:
                db_sess.commit()
                flash('Профиль успешно обновлён', 'success')
            else:
                flash('Изменения не внесены', 'info')

            return redirect(url_for('profile'))

    except SQLAlchemyError as e:
        db_sess.rollback()
        flash('Ошибка базы данных. Попробуйте снова.', 'error')
        current_app.logger.error(f"Database error: {str(e)}")
    except Exception as e:
        db_sess.rollback()
        flash(f'Ошибка: {str(e)}', 'error')
        current_app.logger.error(f"Unexpected error: {str(e)}")
    finally:
        db_sess.close()

    return render_template('profile.html', user=current_user, form=form)


@app.route('/generate_verification_code', methods=['POST'])
@login_required
def generate_verification_code():
    db = create_session()
    user = db.query(User).get(current_user.id)

    if user.telegram_id and user.is_telegram_verified:
        return jsonify({"status": "error", "message": "Telegram уже привязан"})

    code = user.generate_telegram_code()
    db.commit()

    return jsonify({
        "status": "success",
        "code": code,
        "expires_at": user.telegram_code_expires.isoformat()
    })


@app.route('/verify_telegram', methods=['POST'])
@login_required
def verify_telegram():
    data = request.get_json()
    if not data or 'telegram_id' not in data or 'code' not in data:
        return jsonify({"status": "error", "message": "Неверные данные"})

    db = create_session()
    user = db.query(User).get(current_user.id)

    # Проверяем, не привязан ли этот Telegram ID к другому аккаунту
    existing_user = db.query(User).filter_by(telegram_id=data['telegram_id']).first()
    if existing_user and existing_user.id != user.id:
        return jsonify({"status": "error", "message": "Этот Telegram уже привязан к другому аккаунту"})

    if user.verify_telegram_code(data['code']):
        user.telegram_id = data['telegram_id']
        db.commit()
        return jsonify({"status": "success"})

    return jsonify({"status": "error", "message": "Неверный или просроченный код"})


@app.route('/unlink_telegram', methods=['POST'])
@login_required
def unlink_telegram():
    db_sess = create_session()
    try:
        user = db_sess.query(User).filter(User.id == current_user.id).first()
        user.telegram_id = None
        user.is_telegram_verified = False
        db_sess.commit()
        flash('Telegram успешно отвязан', 'success')
    except Exception as e:
        db_sess.rollback()
        flash('Ошибка при отвязке Telegram', 'error')
    finally:
        db_sess.close()
    return redirect(url_for('profile'))


@app.route('/check_verification', methods=['GET'])
@login_required
def check_verification():
    db = create_session()
    user = db.query(User).get(current_user.id)
    return jsonify({
        "is_verified": user.is_telegram_verified,
        "telegram_id": user.telegram_id
    })

def telegram_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_telegram_verified:
            flash('Для доступа к этой странице необходимо привязать Telegram аккаунт', 'warning')
            return redirect(url_for('telegram_connect'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/telegram_connect')
@login_required
def telegram_connect():
    if current_user.is_telegram_verified:
        return redirect(url_for('collect_data'))
    return render_template('telegram_connect.html')


@app.route("/")
def index():
    if current_user.is_authenticated:
        return render_template("collect.html")
    else:
        return render_template("base.html")


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect("/")


@app.route("/analyze", methods=["POST"])
def analyze_endpoint():
    data = request.json

    text = data["text"]
    source = data.get("source", "unknown")
    chat_id = data.get("chat_id")
    author = data.get("author")

    db_sess = create_session()

    try:
        # 🔥 1. ищем активный диалог
        conversation = (
            db_sess.query(Conversation)
            .filter_by(chat_id=chat_id, is_active=True)
            .order_by(Conversation.id.desc())
            .first()
        )

        # 🔥 2. если нет — создаём
        if not conversation:
            conversation = Conversation(
                chat_id=chat_id,
                title="Auto conversation",
                created_at=datetime.now(),
                last_message_at=datetime.now(),
                is_active=True
            )
            db_sess.add(conversation)
            db_sess.flush()  # чтобы получить id

        # 🔥 3. создаём сообщение
        new_entry = TextData(
            text=text,
            source=source,
            author=author,
            created_at=datetime.now(),
            conversation_id=conversation.id   # ✅ ВОТ ГЛАВНОЕ ИЗМЕНЕНИЕ
        )

        db_sess.add(new_entry)

        # 🔥 4. обновляем диалог
        conversation.last_message_at = datetime.now()

        db_sess.commit()

        return jsonify({
            "id": new_entry.id,
            "text": new_entry.text,
            "conversation_id": conversation.id,  # полезно для фронта
            "created_at": new_entry.created_at.isoformat()
        })

    except Exception as e:
        db_sess.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        db_sess.close()


@app.route("/collect", methods=["GET", "POST"])
@login_required
def collect_data():
    # если источник не выбран
    if 'selected_source' not in session:
        return redirect(url_for('select_source'))

    db = None

    try:
        db = create_session()

        source = session['selected_source']

        # =========================
        # TELEGRAM CHATS LIST
        # =========================
        if source == 'telegram':
            if not current_user.is_telegram_verified:
                flash('Для работы с Telegram необходимо привязать аккаунт', 'warning')
                return redirect(url_for('telegram_connect'))

            chats = db.query(TelegramChat).filter(
                TelegramChat.user_id == current_user.telegram_id
            ).order_by(TelegramChat.title).all()

        else:
            chats = None

        # =========================
        # POST: SAVE MESSAGE
        # =========================
        if request.method == "POST":
            text = request.form.get("text", "").strip()

            if not text:
                flash("Текст не может быть пустым", "error")
                return redirect(url_for("collect_data"))

            chat_id = session.get("active_chat_id")

            if not chat_id:
                flash("Не выбран чат", "error")
                return redirect(url_for("collect_data"))

            # 🔥 1. ищем активный conversation
            conversation = (
                db.query(Conversation)
                .filter_by(chat_id=chat_id, is_active=True)
                .order_by(Conversation.id.desc())
                .first()
            )

            # 🔥 2. если нет — создаём
            if not conversation:
                conversation = Conversation(
                    chat_id=chat_id,
                    title="Web conversation",
                    created_at=datetime.now(),
                    last_message_at=datetime.now(),
                    is_active=True
                )
                db.add(conversation)
                db.flush()

            # 🔥 3. сохраняем сообщение
            new_entry = TextData(
                text=text,
                source=source,
                author=str(current_user.id),
                created_at=datetime.now(),
                conversation_id=conversation.id
            )

            db.add(new_entry)

            # 🔥 4. обновляем диалог
            conversation.last_message_at = datetime.now()

            db.commit()

            flash("Данные успешно сохранены", "success")
            return redirect(url_for("collect_data"))

        # =========================
        # GET
        # =========================
        return render_template(
            "collect.html",
            chats=chats,
            source=source
        )

    except Exception as e:
        if db:
            db.rollback()

        current_app.logger.error(f"Error in collect_data: {str(e)}")
        flash(f"Ошибка: {str(e)}", "error")

        return redirect(url_for("collect_data"))

    finally:
        if db:
            db.close()


@app.route('/other_source')
@login_required
def other_source():
    if session.get('selected_source') != 'other':
        return redirect(url_for('index'))

    return render_template('other_source.html')


@app.route('/select_source', methods=['GET', 'POST'])
@login_required
def select_source():
    # Обработка выбора источника
    if request.method == 'POST' or request.args.get('source'):
        source = request.form.get('source') or request.args.get('source')

        if source not in ['telegram', 'other']:
            flash('Неверный источник данных', 'error')
        else:
            session['selected_source'] = source

            if source == 'telegram' and not current_user.is_telegram_verified:
                return redirect(url_for('telegram_connect'))

            return redirect(url_for('collect_data'))

    # Отображение формы выбора
    return render_template('select_source.html')


@app.route("/add_chat", methods=["POST"])
@login_required  # ← ДОБАВИТЬ ЭТОТ ДЕКОРАТОР
def add_chat():
    db = create_session()
    chat_id = request.form.get("chat_id", "").strip()

    if not chat_id:
        return redirect(url_for('collect_data',
                                source='telegram',
                                error="Не указан ID чата"))

    # Проверяем существование чата у ЭТОГО пользователя
    existing_chat = db.query(TelegramChat).filter_by(
        chat_id=chat_id,
        user_id=current_user.telegram_id  # ← ДОБАВИТЬ ПРОВЕРКУ ПО user_id
    ).first()

    if existing_chat:
        db.close()
        return redirect(url_for('collect_data',
                                source='telegram',
                                error="Чат уже существует"))

    try:
        # Определяем тип чата и название
        if chat_id.startswith('@'):
            chat_type = "private"
            title = f"Приватный чат {chat_id}"
        elif chat_id.lstrip('-').isdigit():
            chat_type = "group" if int(chat_id) < 0 else "private"
            title = f"Группа {chat_id}" if chat_type == "group" else f"ЛС {chat_id}"
        else:
            chat_type = "channel"
            title = f"Канал {chat_id}"

        # Создаем новый объект чата С ПРИВЯЗКОЙ К ПОЛЬЗОВАТЕЛЮ
        new_chat = TelegramChat(
            chat_id=chat_id,
            title=title,
            is_active=True,
            chat_type=chat_type,
            user_id=current_user.telegram_id,  # ← КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ
            created_at=datetime.now()
        )

        db.add(new_chat)
        db.commit()
        db.close()
        return redirect(url_for('collect_data',
                                source='telegram',
                                success=f"Чат {title} успешно добавлен"))
    except Exception as e:
        db.rollback()
        db.close()
        return redirect(url_for('collect_data',
                                source='telegram',
                                error=f"Ошибка при добавлении чата: {str(e)}"))


@app.route("/toggle_chat", methods=["POST"])
@login_required
def toggle_chat():
    db = create_session()
    chat_id = request.form.get("chat_id")

    if not chat_id:
        db.close()
        return redirect(url_for('collect_data',
                                source='telegram',
                                error="Не указан ID чата"))

    try:
        # 🔒 ВАЖНО: фильтр по владельцу
        chat = db.query(TelegramChat).filter_by(
            chat_id=chat_id,
            user_id=current_user.telegram_id
        ).first()

        if not chat:
            db.close()
            return redirect(url_for('collect_data',
                                    source='telegram',
                                    error="Чат не найден или нет доступа"))

        chat.is_active = not chat.is_active
        db.commit()

        action = "включен" if chat.is_active else "выключен"

        db.close()
        return redirect(url_for('collect_data',
                                source='telegram',
                                success=f"Чат {chat.title} {action}"))

    except Exception as e:
        db.rollback()
        db.close()
        return redirect(url_for('collect_data',
                                source='telegram',
                                error=f"Ошибка переключения: {str(e)}"))


@app.route("/delete_chat", methods=["POST"])
def delete_chat():
    db = create_session()
    chat_id = request.form.get("chat_id")

    if not chat_id:
        return redirect(url_for('collect_data',
                                source='telegram',
                                error="Не указан ID чата"))

    try:
        chat = db.query(TelegramChat).filter_by(chat_id=chat_id).first()
        if not chat:
            return redirect(url_for('collect_data',
                                    source='telegram',
                                    error="Чат не найден"))

        # Удаляем связанные сообщения
        db.query(TextData).filter_by(chat_id=chat_id).delete()

        # Удаляем сам чат
        db.delete(chat)
        db.commit()
        db.close()

        return redirect(url_for('collect_data',
                                source='telegram',
                                success=f"Чат {chat.title} удалён"))
    except Exception as e:
        db.rollback()
        return redirect(url_for('collect_data',
                                source='telegram',
                                error=f"Ошибка удаления: {str(e)}"))


@app.route("/export/<chat_id>")
def export_json(chat_id):
    db = create_session()
    selected_chats = request.args.getlist('selected_chats')

    try:

        # =========================
        # EXPORT ALL
        # =========================
        if chat_id == 'all':
            conversations = db.query(Conversation).all()

            messages = (
                db.query(TextData)
                .filter(TextData.conversation_id.in_([c.id for c in conversations]))
                .all()
            )

            filename = f"export_all_{datetime.now().strftime('%Y-%m-%d')}.json"

        # =========================
        # EXPORT MULTIPLE CHATS
        # =========================
        elif selected_chats:

            conversations = db.query(Conversation).filter(
                Conversation.chat_id.in_(selected_chats)
            ).all()

            conversation_ids = [c.id for c in conversations]

            messages = (
                db.query(TextData)
                .filter(TextData.conversation_id.in_(conversation_ids))
                .all()
            )

            filename = f"export_multiple_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"

        # =========================
        # EXPORT SINGLE CHAT
        # =========================
        else:

            conversation = (
                db.query(Conversation)
                .filter_by(chat_id=chat_id)
                .order_by(Conversation.id.desc())
                .first()
            )

            if not conversation:
                db.close()
                return "Диалог не найден", 404

            messages = (
                db.query(TextData)
                .filter_by(conversation_id=conversation.id)
                .all()
            )

            filename = f"export_{chat_id}_{datetime.now().strftime('%Y-%m-%d')}.json"

        # =========================
        # FORMAT RESULT
        # =========================
        data = [{
            'id': msg.id,
            'conversation_id': msg.conversation_id,
            'text': msg.text,
            'source': msg.source,
            'author': msg.author,
            'created_at': msg.created_at.isoformat() if msg.created_at else None
        } for msg in messages]

        response = make_response(json.dumps(data, ensure_ascii=False, indent=2))
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        response.headers['Content-type'] = 'application/json; charset=utf-8'

        return response

    except Exception as e:
        app.logger.error(f"Export error: {str(e)}")
        return "Ошибка экспорта", 500

    finally:
        db.close()


# НОВЫЙ МАРШРУТ для POST-запросов из формы с чекбоксами
@app.route('/export_selected_chats', methods=['POST'])
def export_selected_chats():
    selected_chats = request.form.getlist('selected_chats')

    if not selected_chats:
        return "Не выбран ни один чат", 400

    # Преобразуем список в GET-параметры и перенаправляем на export_json
    from urllib.parse import urlencode
    params = urlencode([('selected_chats', chat_id) for chat_id in selected_chats])
    return redirect(f"{url_for('export_json', chat_id='selected')}?{params}")


# Добавляем новый роут для управления ботом
@app.route("/bot_control", methods=["POST"])
def bot_control():
    action = request.form.get("action")

    if action == "start":
        # Логика запуска бота
        return "Бот запущен"
    elif action == "stop":
        # Логика остановки бота
        return "Бот остановлен"

    return "Неизвестное действие", 400


import threading
import os

def run_bot():
    from project.data.db_session import global_init
    import os
    import asyncio

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DB_PATH = os.path.join(BASE_DIR, "db", "blogs.db")

    global_init(DB_PATH)

    print("BOT STARTING...")

    # 🔥 ВАЖНО: создаём event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    bot.run()

if __name__ == '__main__':
    # запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()

    # запускаем Flask
    port = int(os.environ.get("PORT", 4000))
    app.run(host='0.0.0.0', port=port)
