# Docker запуск бота

Сборка из корня проекта:

```powershell
docker build -t vanilla-login-bot .
```

Запуск:

```powershell
docker run -d `
  --name vanilla-login-bot `
  --restart unless-stopped `
  -v ${PWD}\python-bot\config.yml:/app/config.yml:ro `
  -v vanilla-login-bot-data:/data `
  vanilla-login-bot
```

Для Docker лучше указать в `python-bot/config.yml` путь базы:

```yml
DATABASE:
  PATH: "/data/applications.db"
```

Если Minecraft bridge запущен на хосте, `127.0.0.1` внутри контейнера будет указывать на сам контейнер. На Windows/Mac обычно можно поставить:

```yml
BRIDGE:
  BASE_URL: "http://host.docker.internal:8088"
```

Если бот и bridge будут в одной Docker-сети, укажи имя сервиса bridge вместо `host.docker.internal`.

