# Minecraft Applications Bot

Базовая архитектура:

```text
Telegram bot на Python
        -> HTTP с Bearer token
Paper/Purpur plugin на Java
        -> Bukkit/Paper API
        -> whitelist
```

## Python bot

1. Скопируй конфиг:

```powershell
Copy-Item python-bot\config.example.yml python-bot\config.yml
```

2. Заполни `bot_token`, `admin_chat_id` и `bridge.token`.

3. Установи зависимости:

```powershell
cd python-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python bot.py
```

## Paper plugin

1. Собери плагин:

```powershell
cd paper-plugin
mvn package
```

2. Положи jar из `paper-plugin\target` в папку `plugins` сервера.

3. После первого запуска настрой:

```text
plugins/ApplicationBridge/config.yml
```

Токен в плагине и в `python-bot/config.yml` должен совпадать.

## Что уже работает

- бот задает вопросы из YAML-конфига;
- собирает ответы пользователя;
- отправляет заявку в админ-группу;
- под заявкой есть кнопки `Принять`, `Отклонить`, `Бан`;
- при принятии бот вызывает Java-плагин;
- Java-плагин добавляет ник в whitelist через Paper API.
