#!/bin/bash
set -e

DAYS=${1:-14}

echo "=== Местов.Нет: обновление событий ==="
echo "Глубина: $DAYS дней"
echo ""

# 1. Парсинг
echo ">>> Парсинг источников..."
python3 parser.py --days "$DAYS"
python3 repair_event_data.py
python3 moderation_queue.py
echo ""

# 2. Генерация страниц
echo ">>> Генерация страниц..."
python3 generate_pages.py
echo ""

# 3. Коммит и деплой
echo ">>> Деплой..."
git add events.json moderation.json index.html cities/ genre/ venues/ artist/ event/ sitemap.xml robots.txt images/events/ settings.json

# Коммитим только если есть изменения
if git diff --cached --quiet; then
    echo "Нет изменений для коммита."
else
    COUNT=$(python3 -c "import json; d=json.load(open('events.json')); print(len(d))")
    git commit -m "Обновить события: $COUNT в базе"
    # Не перезаписываем изменения daily-parser/manual publish,
    # если main успел обновиться за время локального запуска.
    git pull --rebase origin main
    git push origin HEAD:main
    echo ""
    echo "✅ Задеплоено на mestov.net"
fi
