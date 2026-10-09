# Telegram-бот для сервера Minecraft

Бот для закрытого сервера Minecraft. Он принимает заявки на вайтлист, собирает жалобы игроков, даёт администраторам панель управления сервером и связывает чат игры с форумом в Telegram.

[Русский](#русский) · [English](#english)

---

## Русский

### Что умеет бот

**Для игроков** (в личных сообщениях с ботом):

- **Заявка на сервер.** Игрок пишет `/start`, вводит ник Minecraft, подтверждает, что прочитал правила, и отвечает на вопросы анкеты. Когда заявку примут, бот сам добавит ник в вайтлист и сообщит игроку.
- **Жалоба на игрока.** Кнопка «Жалоба» появляется у тех, кто уже подавал заявку. Игрок указывает ник нарушителя, описывает ситуацию и прикладывает фото, видео или файл. Если у администратора есть вопрос, игрок получит его от бота и сможет ответить.

**Для администраторов** (в админ-чате):

- Новые заявки приходят с кнопками «Принять», «Отклонить» и «Бан». При отклонении бот спросит причину и передаст её игроку.
- Жалобы приходят с кнопками «В работу», «Вопрос» и «Решено».
- Команда `/admins` открывает панель: список заявок, поиск, статистика, кто сейчас онлайн, карточка игрока, кик, команды консоли и рассылка всем, кто писал боту.

**Мост между игрой и Telegram-форумом:**

- Сообщения из чата игры попадают в тему форума, а сообщения из этой темы — в игру.
- Вход и выход игроков, смерти и достижения публикуются в той же теме чата.
- Запуск и остановка сервера публикуются в отдельной теме статуса.
- В форуме работают команды `/list` (кто онлайн) и `/tps` (нагрузка сервера).
- Вид всех сообщений настраивается в конфиге.

### Как это устроено

Проект состоит из двух частей:

| Часть | Папка | Что делает |
| --- | --- | --- |
| Telegram-бот на Python | `python-bot` | Анкеты, жалобы, админ-панель, база заявок, мост чата |
| Плагин для Paper | `paper-plugin` | Добавляет игроков в вайтлист, отдаёт онлайн, выполняет команды, пересылает события игры |

Бот и плагин общаются по локальному HTTP с секретным токеном. В игру бот не заходит. По умолчанию плагин принимает запросы только с той же машины (`127.0.0.1`), поэтому из интернета до него не достучаться.

```text
Игрок в Telegram ──► бот ──► HTTP + токен ──► плагин ──► сервер Minecraft
Форум в Telegram ◄──────── чат и события игры ◄────────┘
```

### Что понадобится

- Сервер на Linux. Подойдёт тот же VPS, где работает Minecraft.
- Сервер Minecraft на **Paper или Purpur 26.2** с **Java 25**.
- **Python 3.14** для бота.
- Аккаунт Telegram, чтобы создать бота.
- Две группы в Telegram:
  - **админ-чат** — туда приходят заявки и жалобы;
  - **форум** (группа с включёнными темами) — для моста чата. Если мост не нужен, форум можно не создавать.

---

### Установка по шагам

#### Шаг 1. Создайте бота в Telegram

1. Откройте [@BotFather](https://t.me/BotFather) и отправьте `/newbot`.
2. Придумайте имя и username бота. BotFather пришлёт **токен** — длинную строку вида `123456789:AA...`. Это пароль от бота, никому его не показывайте.
3. Отправьте BotFather `/setprivacy`, выберите бота и нажмите **Disable**. Без этого бот не увидит обычные сообщения в группах, и мост чата работать не будет.
4. Добавьте бота в админ-чат и в форум и **сделайте его администратором** в обоих.

#### Шаг 2. Установите плагин на сервер Minecraft

1. Возьмите готовый файл `vanilla-plus-plus-bridge-0.1.0.jar` или соберите его сами (см. [Сборка плагина](#сборка-плагина)).
2. Положите jar в папку `plugins` сервера.
3. Запустите сервер, дождитесь полной загрузки и остановите его. Плагин создаст файл `plugins/VanillaPlusPlus/config.yml`.
4. Придумайте секретный токен для связи бота с плагином. Проще всего сгенерировать его командой:

   ```bash
   openssl rand -hex 32
   ```

5. Откройте `plugins/VanillaPlusPlus/config.yml` и вставьте токен:

   ```yaml
   host: "127.0.0.1"
   port: 8088
   token: "сюда-вставьте-сгенерированный-токен"
   ```

6. Запустите сервер.

> Это **не** токен Telegram. Это отдельный пароль, который знают только бот и плагин.

#### Шаг 3. Установите бота

Скопируйте папку проекта на сервер, например в `/opt/vpp-bot`, и выполните:

```bash
cd /opt/vpp-bot/python-bot
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yml config.yml
```

#### Шаг 4. Заполните `python-bot/config.yml`

Откройте файл любым редактором, например `nano config.yml`. Главные поля:

| Поле | Что вписать |
| --- | --- |
| `BOT_TOKEN` | Токен от BotFather |
| `BOT_USERNAME` | Username бота, например `@my_server_bot` |
| `ADMIN_CHAT_ID` | ID админ-чата (как узнать — ниже) |
| `FORUM_CHAT_ID` | ID форума для моста чата |
| `ADMINS` | Telegram ID администраторов, по одному в строке |
| `BRIDGE.TOKEN` | Тот же токен, что в конфиге плагина |
| `QUESTIONS` | Вопросы анкеты |
| `MESSAGES` | Тексты, которые бот пишет игрокам |

**Как узнать ID чата.** Запустите бота (шаг 5), отправьте в нужной группе команду `/topic`, и бот ответит строкой `Chat ID`. ID групп начинаются с `-100`.

**Как узнать свой Telegram ID.** Напишите боту [@userinfobot](https://t.me/userinfobot).

> Если список `ADMINS` пустой, администратором считается **любой** пользователь. Обязательно впишите свои ID.

Значения в кавычках оставляйте в кавычках. Если в токене есть символы `#`, `&`, `*` или `!`, кавычки обязательны.

#### Шаг 5. Запустите бота

```bash
cd /opt/vpp-bot/python-bot
source .venv/bin/activate
python bot.py
```

Напишите боту `/start` в личные сообщения. Если пришло приветствие, бот работает. Остановить его можно сочетанием `Ctrl+C`.

#### Шаг 6. Настройте темы форума

1. В настройках форума включите **Темы**.
2. Создайте две темы, например «Статус» и «Чат Minecraft».
3. Отправьте `/topic` в каждой теме. Бот ответит номером темы (`Topic ID`).
4. Впишите номера в `config.yml`:

   ```yaml
   CHAT_BRIDGE:
     ENABLED: true
     STATUS_TOPIC_ID: "22"   # запуск и остановка сервера
     CHAT_TOPIC_ID: "7"      # чат, входы, выходы, смерти, достижения
   ```

5. Перезапустите бота.

Номер темы — это короткое число вроде `7` или `22`. Не путайте его с ID чата, который начинается с `-100`.

#### Шаг 7. Запуск в фоне (systemd)

Чтобы бот работал постоянно и сам поднимался после перезагрузки сервера, создайте службу:

```bash
sudo nano /etc/systemd/system/vpp-bot.service
```

```ini
[Unit]
Description=Telegram bot for the Minecraft server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=bot
WorkingDirectory=/opt/vpp-bot/python-bot
ExecStart=/opt/vpp-bot/python-bot/.venv/bin/python bot.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Замените `bot` на пользователя Linux, от имени которого будет работать бот, и включите службу:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vpp-bot
```

Полезные команды:

```bash
sudo systemctl status vpp-bot    # работает ли бот
sudo systemctl restart vpp-bot   # перезапуск после правки конфига
journalctl -u vpp-bot -f         # живой лог
```

Запуск в Docker описан в [DOCKER.md](DOCKER.md).

---

### Как пользоваться

#### Игроку

1. Найти бота в Telegram и нажать **Start** (или отправить `/start`).
2. Ввести ник Minecraft **точно как в лаунчере**.
3. Прочитать правила и нажать «Я ознакомлен».
4. Ответить на вопросы и дождаться решения: бот пришлёт сообщение сам.

#### Администратору

- Решения по заявкам принимаются кнопками прямо под заявкой в админ-чате.
- `/admins` открывает панель управления.
- Нажать «Принять» может только один администратор. Если двое нажмут одновременно, сработает первое нажатие.
- Если ника нет среди аккаунтов Minecraft, заявка остаётся на рассмотрении, и бот напишет об этом.
- «Бан» запрещает человеку подавать заявки. Из вайтлиста он при этом не удаляется.

#### Команды

| Где | Команда | Что делает |
| --- | --- | --- |
| Личка с ботом | `/start` | Открывает меню игрока: заявка или жалоба |
| Админ-чат | `/admins` | Админ-панель |
| Любой чат | `/topic` | Показывает ID чата и номер темы |
| Форум | `/list` | Кто сейчас на сервере |
| Форум | `/tps` | TPS и MSPT сервера |
| В игре | `/tgbridge toggle` | Скрыть или показать сообщения из Telegram для себя |
| В игре | `/tgbridge reload` | Перечитать конфиг плагина (нужны права оператора) |
| В игре | `/tgbridge send <формат> <чат> <текст>` | Отправить сообщение в Telegram из игры или консоли |

---

### Настройка

Все настройки бота лежат в `python-bot/config.yml`. После правки перезапустите бота.

#### Анкета и тексты

- `QUESTIONS` — список вопросов анкеты. Их можно добавлять, убирать и менять местами.
- `MESSAGES` — что бот пишет игроку: приветствие, правила, принятие, отказ и так далее.
- В текстах можно использовать HTML: `<b>жирный</b>`, `<i>курсив</i>`, `<a href="https://...">ссылка</a>`.

#### Какие события отправлять

Раздел `CHAT_BRIDGE.EVENTS`, где `true` — отправлять, `false` — нет:

```yaml
  EVENTS:
    START: true                  # запуск сервера
    STOP: true                   # остановка сервера
    JOIN: true                   # вход (или "first_join_only" — только первый вход)
    LEAVE: true                  # выход
    DEATH: true                  # смерти
    ADVANCEMENT: true            # достижения целиком
    ADVANCEMENT_TASK: true       # обычные достижения
    ADVANCEMENT_GOAL: true       # цели
    ADVANCEMENT_CHALLENGE: true  # испытания
    ADVANCEMENT_DESCRIPTION: true  # описание под достижением
```

#### Вид сообщений в Telegram

Раздел `CHAT_BRIDGE.FORMAT`. В фигурных скобках — подстановки, их бот заменит на данные:

```yaml
  FORMAT:
    JOIN: "🥳 {name} зашёл на сервер"
    CHAT: "💬 <b>{name}</b>: {text}"
    DEATH: "☠️ {text}"
```

| Подстановка | Что означает |
| --- | --- |
| `{name}` | Ник игрока |
| `{text}` | Текст сообщения или фраза о смерти |
| `{title}`, `{description}` | Название и описание достижения |
| `{count}`, `{players}` | Число игроков онлайн и их ники (для `/list`) |
| `{tps}`, `{mspt}` | Нагрузка сервера (для `/tps`) |

Пустая строка `""` отключает сообщение. Если удалить строку целиком, вернётся вид по умолчанию.

#### Вид сообщений из Telegram в игре

Раздел `CHAT_BRIDGE.MINECRAFT_FORMAT`. Цвета задаются в формате [MiniMessage](https://docs.advntr.dev/minimessage/format):

```yaml
  MINECRAFT_FORMAT:
    MESSAGE: "<reply><aqua>[TG] <sender>:</aqua> <white><text></white>"
    REPLY: "<gray>[Ответ: <reply>]</gray> "
    EDIT_PREFIX: "✎ "
```

- `<sender>` — имя в Telegram, `<text>` — сообщение, `<reply>` — цитата, если человек ответил на чьё-то сообщение.
- `REPLY: false` полностью отключает цитаты в игре.
- Цвета: `<red>`, `<gold>`, `<#ff8800>`, `<bold>`, `<gradient:#5e4fa2:#f79459>текст</gradient>`.

#### Прочее

| Поле | Что делает |
| --- | --- |
| `REPLY_TO_MESSAGES` | Бот отвечает реплаем на сообщение, на которое реагирует |
| `CHAT_BRIDGE.MERGE_WINDOW` | Склеивает сообщения игрока, отправленные подряд за N секунд (`0` — выключено) |
| `CHAT_BRIDGE.LEAVE_JOIN_MERGE_WINDOW` | Если игрок перезашёл за N секунд, сообщения о выходе и входе не появятся |
| `CHAT_BRIDGE.REQUIRE_PREFIX_MINECRAFT` | В Telegram попадают только сообщения из игры с этим префиксом, например `!` |
| `CHAT_BRIDGE.REQUIRE_PREFIX_TELEGRAM` | То же для сообщений из Telegram в игру |
| `CHAT_BRIDGE.SILENT_EVENTS` | События, которые приходят без звука, например `[JOIN, LEAVE]` |
| `DATABASE.BACKUP_KEEP_LAST` | Сколько резервных копий базы хранить |

---

### Обновление

1. Остановите бота: `sudo systemctl stop vpp-bot`.
2. Замените файлы проекта новыми. `config.yml` и `applications.db` не трогайте: там ваши настройки и заявки.
3. Обновите зависимости: `.venv/bin/pip install -r requirements.txt`.
4. Если вышел новый jar плагина, замените его в `plugins` и перезапустите сервер Minecraft.
5. Запустите бота: `sudo systemctl start vpp-bot`.

Перед каждым запуском бот сам делает копию базы в папку `backups`.

---

### Частые проблемы

**Бот не отвечает в группе.** Отключите privacy mode у BotFather (`/setprivacy` → Disable), удалите бота из группы и добавьте снова, затем выдайте ему права администратора.

**В логе `message thread not found`.** В `STATUS_TOPIC_ID` или `CHAT_TOPIC_ID` указан неверный номер темы. Отправьте `/topic` внутри нужной темы и перепишите номер.

**«Сервер недоступен» или `Cannot connect to host 127.0.0.1:8088`.** Сервер Minecraft выключен, плагин не загрузился или в `BRIDGE.BASE_URL` указан не тот порт. Проверьте лог сервера.

**`401 Unauthorized`.** Токены не совпадают. Значение `BRIDGE.TOKEN` у бота должно быть таким же, как `token` в `plugins/VanillaPlusPlus/config.yml`.

**Paper не загружает плагин.** Версия плагина должна совпадать с версией сервера. Текущая сборка рассчитана на Paper 26.2.

**Игрока не добавляет в вайтлист.** Ник введён с ошибкой или такого аккаунта Minecraft нет. Заявка останется на рассмотрении. Попросите игрока подать её заново с правильным ником.

**После правки конфига ничего не изменилось.** Бот читает конфиг только при запуске. Перезапустите его. Для конфига плагина достаточно `/tgbridge reload` в игре.

---

### Безопасность

- Никому не показывайте `BOT_TOKEN` и `BRIDGE.TOKEN`. Если токен утёк, выпустите новый: у BotFather командой `/revoke`, для моста — новой строкой `openssl rand -hex 32`.
- Оставьте `host: "127.0.0.1"` в конфиге плагина, если бот и сервер на одной машине.
- Если они на разных машинах, не открывайте порт 8088 в интернет. Используйте VPN или закрытую сеть, подробнее в [BRIDGE.md](BRIDGE.md).
- Кнопка «Консоль» позволяет выполнить любую команду сервера. Ограничить список команд можно в `console.allowed-commands` конфига плагина.

---

### Сборка плагина

Нужны Java 25 и Maven.

```bash
cd paper-plugin
mvn package
```

Готовый файл появится по пути `paper-plugin/target/vanilla-plus-plus-bridge-0.1.0.jar`.

---

## English

### What it does

A bot for a private Minecraft server. It handles whitelist applications, collects player reports, gives admins a server control panel, and links the in-game chat with a Telegram forum.

- **Players** send `/start` to the bot, enter their Minecraft name, accept the rules, and answer the form. Once accepted, they are whitelisted automatically and get a message. Players who have applied can also file a report with a photo, video, or file attached.
- **Admins** get new applications in the admin chat with Accept, Reject, and Ban buttons. `/admins` opens a panel with the application list, search, statistics, online players, player info, kick, console commands, and a broadcast.
- **Chat bridge**: in-game chat, joins, leaves, deaths, and advancements go to the chat topic. Server start and stop go to the status topic. Messages from the chat topic appear in the game. `/list` and `/tps` work in the forum.

### Requirements

- A Linux host
- Paper or Purpur **26.2** on **Java 25**
- **Python 3.14**
- An admin chat and, for the bridge, a Telegram group with topics enabled

### Setup

1. **Create the bot.** In [@BotFather](https://t.me/BotFather) send `/newbot` and save the token. Send `/setprivacy` → **Disable** so the bot can read group messages. Add the bot to the admin chat and the forum as an administrator.
2. **Install the plugin.** Put `vanilla-plus-plus-bridge-0.1.0.jar` into `plugins/`, start and stop the server once, then set a secret in `plugins/VanillaPlusPlus/config.yml`:

   ```yaml
   host: "127.0.0.1"
   port: 8088
   token: "output-of-openssl-rand-hex-32"
   ```

3. **Install the bot.**

   ```bash
   cd /opt/vpp-bot/python-bot
   python3.14 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cp config.example.yml config.yml
   ```

4. **Fill in `config.yml`**: `BOT_TOKEN`, `BOT_USERNAME`, `ADMIN_CHAT_ID`, `FORUM_CHAT_ID`, `ADMINS` (your Telegram IDs; an empty list makes everyone an admin), and `BRIDGE.TOKEN` (the same secret as the plugin).
5. **Run**: `python bot.py`. Send `/topic` in any chat to see its chat ID, and in each forum topic to see its topic ID.
6. **Set the topics** in `CHAT_BRIDGE.STATUS_TOPIC_ID` and `CHAT_BRIDGE.CHAT_TOPIC_ID`, then restart the bot.
7. **Run as a service** with the systemd unit from the Russian section above (`sudo systemctl enable --now vpp-bot`). Docker is covered in [DOCKER.md](DOCKER.md).

### Commands

| Where | Command | Action |
| --- | --- | --- |
| Private chat | `/start` | Player menu: apply or report |
| Admin chat | `/admins` | Admin panel |
| Any chat | `/topic` | Show the chat ID and topic ID |
| Forum | `/list`, `/tps` | Online players, server TPS |
| In game | `/tgbridge toggle` | Hide or show Telegram messages for yourself |
| In game | `/tgbridge reload` | Reload the plugin config (op) |
| In game | `/tgbridge send <format> <chat> <text>` | Send a message to Telegram |

### Customization

Everything lives in `python-bot/config.yml`. Restart the bot after editing.

- `QUESTIONS` and `MESSAGES`: the form and the texts players see. HTML is allowed.
- `CHAT_BRIDGE.EVENTS`: turn each event type on or off.
- `CHAT_BRIDGE.FORMAT`: how messages look in Telegram. Placeholders: `{name}`, `{text}`, `{title}`, `{description}`, `{count}`, `{players}`, `{tps}`, `{mspt}`. An empty string disables the message.
- `CHAT_BRIDGE.MINECRAFT_FORMAT`: how Telegram messages look in game, in [MiniMessage](https://docs.advntr.dev/minimessage/format) with `<sender>`, `<text>`, `<reply>`. `REPLY: false` hides quotes.
- `REPLY_TO_MESSAGES`: the bot answers as a reply to the user's message.

### Troubleshooting

- **The bot ignores group messages**: disable privacy mode, re-add the bot, make it an admin.
- **`message thread not found`**: the topic ID is wrong. Run `/topic` inside the topic.
- **`Cannot connect to host 127.0.0.1:8088`**: the server is down, the plugin failed to load, or the port is wrong.
- **`401 Unauthorized`**: `BRIDGE.TOKEN` and the plugin `token` differ.
- **Paper refuses the plugin**: this build targets Paper 26.2.

### Security

Keep `BOT_TOKEN` and `BRIDGE.TOKEN` secret. Leave the plugin on `127.0.0.1` when the bot runs on the same host, and never expose port 8088 to the internet. The console button can run any server command; restrict it with `console.allowed-commands` in the plugin config. See [BRIDGE.md](BRIDGE.md).

### Building the plugin

Java 25 and Maven are required:

```bash
cd paper-plugin
mvn package
```

The jar is written to `paper-plugin/target/vanilla-plus-plus-bridge-0.1.0.jar`.
