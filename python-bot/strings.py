from enum import StrEnum


class Strings(StrEnum):
    ADMIN_PANEL = "Админ-панель"
    BUTTON_START = "Приступить к заявке"
    BUTTON_AGREE = "Я ознакомлен"
    ONLY_PRIVATE_ALERT = "Кнопка доступна только в личных сообщениях."
    INVALID_NICKNAME = "Неверный ник. Используйте 3-16 символов: латиница, цифры и _."
    APPLICATION_NOT_FOUND = "Заявка не найдена."
    APPLICATION_ALREADY_PROCESSED = "Заявка уже обработана."
    WHITELIST_ADD_FAILED = "Не удалось добавить в whitelist."
    ACTION_ACCEPTED = "Принято ✅"
    ACTION_REJECTED = "Отклонено ❌"
    ACTION_BANNED = "Забанено ⛔"
    EMPTY_COMMAND = "Пустая команда. Отмена."
    NOTHING_FOUND = "Ничего не найдено."
    NO_PENDING_APPLICATIONS = "Ожидающих заявок нет."
    ADMIN_ONLY_BUTTON = "Эта кнопка доступна только в админ-чате."
    NO_ACCESS = "У вас нет доступа."
    SERVER_PANEL_TITLE = "<b>Панель сервера</b>"
