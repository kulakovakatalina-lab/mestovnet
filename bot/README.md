# Телеграм-бот «Местов.Нет»

Присылает подписчикам подборки живой музыки Крыма с [mestov.net](https://mestov.net).
Пользователь выбирает жанры, города и частоту (каждый день / раз в неделю / по запросу) —
бот по расписанию шлёт подборку ссылок на события.

Данные берутся напрямую с сайта (`events.json` + `settings.json`), маппинг жанров и
городов повторяет логику `genre.html`, так что бот показывает ровно то же, что и сайт.

## Как это работает

- Один процесс с long-polling (`python-telegram-bot`).
- Кнопки выбора жанров/городов/частоты — инлайн-клавиатуры.
- Расписание — встроенный `JobQueue` (время Крыма, `Europe/Simferopol`).
- Подписки хранятся в `bot_data.pickle` (`PicklePersistence`) и переживают рестарт,
  **если** файл лежит на постоянном диске (volume). Путь задаётся `DATA_DIR`.

## Команды

- `/start` — меню и настройка подписки
- `/digest` — прислать подборку прямо сейчас
- `/stop` — отписаться

## 1. Создать бота

1. В Telegram открой [@BotFather](https://t.me/BotFather) → `/newbot` → задай имя.
2. Скопируй токен — это `BOT_TOKEN`.

## 2. Запуск локально (для теста)

```bash
cd bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN=123456:ABC...        # свой токен
python bot.py
```

Потом напиши боту `/start` в Telegram.

## 3. Деплой на бесплатный хост

Боту нужен процесс, работающий 24/7 (polling), и **постоянный диск** для подписок.

### Railway (проще всего)

1. Зарегистрируйся на [railway.app](https://railway.app), `New Project → Deploy from GitHub repo`.
2. Root Directory → `bot` (чтобы Railway взял этот Dockerfile).
3. Variables → добавь `BOT_TOKEN`.
4. Add Volume → mount path `/data` (Dockerfile уже ставит `DATA_DIR=/data`).
5. Deploy. Логи покажут `Bot started`.

### Fly.io

```bash
cd bot
fly launch --no-deploy        # создаст fly.toml; тип — Dockerfile
fly volumes create data --size 1
fly secrets set BOT_TOKEN=123456:ABC...
```
В `fly.toml` примонтируй volume к `/data`:
```toml
[[mounts]]
  source = "data"
  destination = "/data"
```
Затем `fly deploy`. (Бот на polling — HTTP-порт/health-check не нужен.)

### Render

`New → Background Worker` → подключи репозиторий, root `bot`, env `BOT_TOKEN`,
добавь Persistent Disk на `/data`. (Free-план Render усыпляет web-сервисы, поэтому
именно **Background Worker**, не Web Service.)

## Заметки

- Без volume бот тоже работает, но при рестарте/редеплое подписки сбросятся.
- Время в расписании — крымское (МСК). Поменять зону — константа `TZ` в `bot.py`.
- Крым-wide события (город «Крым» и непривязанные посёлки) попадают в подборку
  при любом выборе городов — как и общая лента сайта.
