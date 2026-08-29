# Бот «Местов.Нет» на Cloudflare Workers

Мгновенный бесплатный serverless: webhook (instant), хранилище Cloudflare KV,
рассылка через Cron Trigger. Серверы Cloudflare за границей → Telegram доступен.

Файл: [`worker.js`](worker.js) — один файл на чистом JS, деплоится из дашборда без инструментов.

## Настройка (в дашборде Cloudflare)

1. **Создать Worker:** Workers & Pages → Create → Create Worker → имя `mestov-bot` → Deploy.
2. **Вставить код:** Edit code → заменить содержимое на `worker.js` → Deploy.
3. **KV namespace:** Storage & Databases → KV → Create namespace `mestov-bot-kv`.
4. **Привязать KV:** Worker → Settings → Bindings → Add → KV namespace:
   - Variable name: **`KV`**
   - Namespace: `mestov-bot-kv`
5. **Переменные:** Worker → Settings → Variables and Secrets → добавить:
   - `BOT_TOKEN` (тип Secret) — токен бота
   - `WEBHOOK_SECRET` — `6eQoa4vAL9cnI8cmoJv0nJeZeCi95Mlm`
   - `ADMIN_ID` — `267459702`
   - `MODERATION_SYNC_TOKEN` (тип Secret) — случайная длинная строка; это
     пароль для ночного парсера, который забирает решения модератора из KV.
   - `GITHUB_MODERATION_TOKEN` (тип Secret) — GitHub token с разрешением
     **Actions: Read and write** для запуска мгновенной публикации.
   - `GITHUB_REPOSITORY` — `kulakovakatalina-lab/mestovnet` (необязательно).
6. **Cron Trigger:** Worker → Settings → Triggers → Cron Triggers → Add →
   `20 13 * * *` (13:20 UTC = 16:20 Крым).
7. **URL Worker'а:** вида `https://mestov-bot.<твой-сабдомен>.workers.dev`.
8. **Webhook:**
   ```bash
   curl "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://mestov-bot.<сабдомен>.workers.dev/&secret_token=6eQoa4vAL9cnI8cmoJv0nJeZeCi95Mlm"
   ```

## Проверка
- GET на URL Worker'а вернёт «Местов.Нет бот работает 🎸».
- Логи: Worker → вкладка Logs (Real-time logs).
- `getWebhookInfo` не должен показывать ошибок.

## Модерация событий в Telegram

Ночной GitHub Actions-парсер публикует чистые карточки сразу, а спорные
оставляет в `moderation.json`. После деплоя бот присылает админу кнопку
«Разобрать события». В карточке есть ссылка на источник и кнопки
«Одобрить»/«Отклонить»; решения хранятся в KV.

Чтобы ночной процесс применял их, в GitHub Secrets добавьте те же значения:

- `MODERATION_WORKER_URL` — URL этого Worker-а, без завершающего `/`;
- `MODERATION_SYNC_TOKEN` — то же секретное значение, что в Worker.

Для немедленной публикации добавьте в секреты Worker-а:

- `GITHUB_MODERATION_TOKEN` — fine-grained GitHub token с доступом к этому
  репозиторию и разрешением **Actions: Read and write**;
- `GITHUB_REPOSITORY` — `kulakovakatalina-lab/mestovnet` (необязательно:
  это значение уже используется по умолчанию).

После «Одобрить» или «Отклонить» Worker сразу запускает короткую публикацию:
решение синхронизируется, страницы пересобираются и деплоятся. Обычно
изменение появляется через несколько минут. Если секрет GitHub не настроен
или GitHub временно недоступен, решение безопасно подхватит ночной процесс.
Если парсер обнаружит новый набор проблем, старое одобрение не используется
и карточка снова придёт на проверку.

## Лимиты бесплатного тарифа
- 100 000 запросов Worker/день, KV: 100k чтений + 1000 записей/день — для бота с запасом.
