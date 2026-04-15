from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import Length, Email, Optional, EqualTo

class ProfileForm(FlaskForm):
    name = StringField('Имя', validators=[Optional(), Length(min=2, max=50)])
    email = StringField('Email', validators=[Optional(), Email()])
    current_password = PasswordField('Текущий пароль', validators=[Optional()])
    new_password = PasswordField('Новый пароль', validators=[
        Optional(),
        Length(min=6, message='Пароль должен содержать минимум 6 символов'),
        EqualTo('confirm_password', message='Пароли должны совпадать')
    ])
    confirm_password = PasswordField('Подтвердите новый пароль', validators=[Optional()])
    submit = SubmitField('Сохранить изменения')