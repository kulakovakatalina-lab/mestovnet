# Бот «Местов.Нет» на Deno Deploy

Serverless-версия телеграм-бота. Работает на **webhook** (Telegram сам шлёт апдейты),
рассылка — через **Deno.cron**, подписки хранятся в **Deno KV**. Бесплатно, без карты.

Файл: [`main.ts`](main.ts). Функции те же, что у Python-версии: выбор жанров/городов/частоты,
`/start`, `/digest`, `/stop`, `/stats`, подборка на неделю со ссылками.

## Переменные окружения

| Переменная | Назначение |
|---|---|
| `BOT_TOKEN` | токен бота от @BotFather |
| `WEBHOOK_SECRET` | любая случайная строка (защита webhook от чужих запросов) |
| `ADMIN_ID` | Telegram ID администратора для `/stats` (необязательно, есть значение по умолчанию) |

## Деплой (через GitHub)

1. Зайди на [dash.deno.com](https://dash.deno.com) → **Sign in with GitHub** (карта не нужна).
2. **New Project** → выбери репозиторий `mestovnet`.
3. Настрой:
   - **Entrypoint**: `bot-deno/main.ts`
   - **Branch**: `main`
4. В разделе **Settings → Environment Variables** добавь `BOT_TOKEN`, `WEBHOOK_SECRET`
   (придумай строку, напр. 20+ случайных символов) и при желании `ADMIN_ID`.
5. Дождись деплоя — получишь адрес вида `https://ИМЯ.deno.dev`.

> Deno KV и Deno.cron на Deploy включаются автоматически, ничего настраивать не нужно.

## Привязать webhook к Telegram

Один раз выполни (подставь токен, адрес проекта и тот же секрет):

```bash
curl "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://<ИМЯ>.deno.dev/&secret_token=<WEBHOOK_SECRET>"
```

Должно вернуть `{"ok":true,...}`. После этого пиши боту `/start`.

Проверить, что webhook стоит:
```bash
curl "https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo"
```

## Локальный запуск (для проверки логики)

```bash
deno run --unstable-kv --allow-net --allow-env \
  --env-file=.env main.ts
```
(нужны `BOT_TOKEN` и `WEBHOOK_SECRET` в `.env`). Локально webhook от Telegram не дойдёт —
для полноценного теста нужен публичный адрес (Deno Deploy). Локально удобно проверять
загрузку/фильтрацию событий.

## Заметки

- Рассылка идёт в 13:20 UTC = **16:20 по Крыму** (см. `Deno.cron` в `main.ts`).
- Еженедельные подписчики получают подборку только в свой день недели.
- Подписки в Deno KV переживают редеплой автоматически (в отличие от файла-pickle).
