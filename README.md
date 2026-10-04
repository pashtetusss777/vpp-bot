# Заявки на вайтлист

Telegram-бот для закрытого сервера Minecraft. Игрок заполняет короткую анкету, администратор читает ответы и одной кнопкой открывает сервер: ник появляется в whitelist.

[Русский](#русский) · [English](#english)

## Русский

Игрок пишет боту в личке. Администраторы сидят в отдельном чате и решают, кого пускать. С самим сервером бот не говорит по игровому протоколу: он отправляет локальный HTTP-запрос Paper-плагину, а плагин добавляет игрока через Paper API.

На Linux-сервере бот и Minecraft обычно живут на одной машине. Плагин слушает `127.0.0.1`, так что мост не торчит в интернет. Если бот и сервер на разных хостах, закройте канал VPN или отдельной сетью — см. [BRIDGE.md](BRIDGE.md).

### Состав

| Часть | Каталог | Роль |
| --- | --- | --- |
| Telegram-бот | `python-bot` | Анкета, база заявок, панель администратора |
| Paper-плагин | `paper-plugin` | Мост к whitelist, статусу сервера и консоли |

```text
Игрок в Telegram
    -> Python-бот (анкета, SQLite)
        -> HTTP с Bearer-токеном
            -> Paper-плагин
                -> Paper API
```

### Что умеет бот

По `/start` игрок вводит ник Minecraft, подтверждает, что прочитал правила, и отвечает на вопросы из `python-bot/config.yml`. Готовая заявка уходит в админ-чат. О решении бот пишет игроку сам.

Под заявкой три кнопки: «Принять», «Отклонить», «Бан». «Принять» вызывает `POST /whitelist/add`. Плагин находит UUID аккаунта Mojang и ставит whitelist именно на него. Если такого аккаунта нет, заявка остаётся на рассмотрении, а не помечается принятой впустую.

В том же чате есть список заявок, поиск, статистика, онлайн, карточка игрока, кик, консольная команда и рассылка тем, кто уже писал боту.

### Что нужно на сервере

- Linux
- Python 3.14
- Java 25 и Maven, чтобы собрать плагин
- Paper или Purpur 26.3

Плагин объявляет `api-version: "26.3"` и собран против `paper-api` `26.3.build.151-beta`. Игровому серверу нужна Java 25.

### Запуск бота

Скопируйте пример конфига и заполните токен бота, `ADMIN_CHAT_ID`, список `ADMINS` и `BRIDGE.TOKEN`. Вопросы анкеты и тексты сообщений тоже живут в этом файле.

```bash
cp python-bot/config.example.yml python-bot/config.yml
cd python-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

`BRIDGE.TOKEN` должен совпадать с токеном в конфиге плагина. Это отдельный секрет, не токен Telegram.

На сервере бота удобно держать службой systemd. Юнит ниже рассчитан на каталог `/opt/vpp-bot` и пользователя `bot` — подставьте свои пути.

```ini
[Unit]
Description=Minecraft whitelist application bot
After=network-online.target

[Service]
Type=simple
User=bot
WorkingDirectory=/opt/vpp-bot/python-bot
ExecStart=/opt/vpp-bot/python-bot/.venv/bin/python bot.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Тот же бот можно поднять контейнером. Готовый сценарий для Linux — в [DOCKER.md](DOCKER.md).

### Плагин

```bash
cd paper-plugin
mvn package
```

Скопируйте jar из `paper-plugin/target` в `plugins/` сервера, один раз запустите сервер и остановите его. Paper создаст конфиг плагина. В `plugins/VanillaPlusPlus/config.yml` выставьте `host`, `port` и `token` так же, как блок `BRIDGE` у бота, затем запустите сервер снова.

Сборка, токен и сеть моста — в [BRIDGE.md](BRIDGE.md).

## English

A Telegram bot for a closed Minecraft server. A player fills in a short application, an admin reads the answers, and one button opens the gate: the name is added to the whitelist.

Players talk to the bot in a private chat. Admins work in a separate chat and decide who gets in. The bot does not speak the Minecraft protocol. It sends a local HTTP request to a Paper plugin, and the plugin whitelists the player through the Paper API.

On a Linux host the bot and the game server usually share one machine. The plugin listens on `127.0.0.1`, so the bridge stays off the public internet. If they run on different hosts, keep the channel on a VPN or a private network. See [BRIDGE.md](BRIDGE.md).

### Parts

| Part | Directory | Role |
| --- | --- | --- |
| Telegram bot | `python-bot` | Application form, application database, admin panel |
| Paper plugin | `paper-plugin` | Bridge to the whitelist, server status, and the console |

```text
Player in Telegram
    -> Python bot (form, SQLite)
        -> HTTP with a Bearer token
            -> Paper plugin
                -> Paper API
```

### What the bot does

`/start` asks for a Minecraft name, a confirmation that the rules were read, and the questions from `python-bot/config.yml`. The finished application lands in the admin chat. The bot tells the player the decision itself.

Each application has three buttons: Accept, Reject, and Ban. Accept calls `POST /whitelist/add`. The plugin resolves the Mojang account UUID and whitelists that UUID. If there is no such account, the application stays pending instead of being marked approved.

The same chat also has the application list, search, statistics, the online list, a player card, kick, a console command, and a broadcast to people who have already messaged the bot.

### Server requirements

- Linux
- Python 3.14
- Java 25 and Maven, to build the plugin
- Paper or Purpur 26.3

The plugin sets `api-version: "26.3"` and is built against `paper-api` `26.3.build.151-beta`. The game server needs Java 25.

### Run the bot

Copy the example config and fill in the bot token, `ADMIN_CHAT_ID`, the `ADMINS` list, and `BRIDGE.TOKEN`. The form questions and message texts live in the same file.

```bash
cp python-bot/config.example.yml python-bot/config.yml
cd python-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

`BRIDGE.TOKEN` must match the token in the plugin config. It is a separate secret from the Telegram bot token.

On a server, run the bot as a systemd service. The unit below assumes `/opt/vpp-bot` and a user named `bot`. Change both to match the host.

```ini
[Unit]
Description=Minecraft whitelist application bot
After=network-online.target

[Service]
Type=simple
User=bot
WorkingDirectory=/opt/vpp-bot/python-bot
ExecStart=/opt/vpp-bot/python-bot/.venv/bin/python bot.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

The same bot can run in a container. The Linux setup is in [DOCKER.md](DOCKER.md).

### Plugin

```bash
cd paper-plugin
mvn package
```

Copy the jar from `paper-plugin/target` into the server `plugins/` directory, start the server once, and stop it. Paper will create the plugin config. In `plugins/VanillaPlusPlus/config.yml`, set `host`, `port`, and `token` to the same values as the bot's `BRIDGE` block, then start the server again.

Build, token, and bridge networking are covered in [BRIDGE.md](BRIDGE.md).
