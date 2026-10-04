# ApplicationBridge

`ApplicationBridge` - это маленький Paper/Purpur-плагин, который принимает локальный HTTP-запрос от Telegram-бота и добавляет игрока в whitelist через Paper API.

## Как это работает

```text
Админ нажимает "Принять" в Telegram
        ↓
Python-бот отправляет POST /whitelist/add
        ↓
ApplicationBridge проверяет секретный TOKEN
        ↓
Paper добавляет ник в whitelist
```

## Файлы плагина

- `paper-plugin/pom.xml` - Maven-проект для сборки jar.
- `paper-plugin/src/main/resources/plugin.yml` - описание Paper-плагина.
- `paper-plugin/src/main/resources/config.yml` - конфиг плагина.
- `paper-plugin/src/main/java/dev/example/vanillaplus/VanillaPlusPlusPlugin.java` - логика bridge.

Плагин рассчитан на Paper 26.3 (`api-version: "26.3"`) и Java 25. Whitelist пишется через Paper API, не через RCON и не через протокол 777.

## Сборка

Нужны Java и Maven.

Проверка:

```powershell
java -version
mvn -version
```

Сборка:

```powershell
cd paper-plugin
mvn package
```

Готовый jar появится в:

```text
paper-plugin\target\vanilla-plus-plus-bridge-0.1.0.jar
```

## Установка на сервер

1. Скопируй jar в папку `plugins` Paper/Purpur-сервера.
2. Запусти сервер.
3. Останови сервер.
4. Открой файл:

```text
plugins\VanillaPlusPlus\config.yml
```

5. Настрой:

```yml
host: "127.0.0.1"
port: 8088
token: "some-long-random-secret"
```

6. Такой же token поставь в `python-bot/config.yml`:

```yml
BRIDGE:
  BASE_URL: "http://127.0.0.1:8088"
  TOKEN: "some-long-random-secret"
  TIMEOUT_SECONDS: 5
```

7. Запусти сервер и Python-бота.

## Важно

`host: "127.0.0.1"` означает, что bridge доступен только с той же машины. Это самый безопасный вариант, если Minecraft-сервер и бот запущены на одном VPS.

Не используй Telegram bot token как `BRIDGE.TOKEN`. Это разные секреты.

Если бот и Minecraft-сервер находятся на разных машинах, лучше не открывать bridge в интернет напрямую. Нужен firewall, VPN или отдельная защищенная сеть.

