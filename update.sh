#!/bin/bash
set -e

DAYS=${1:-14}

echo "=== Местов.Нет: обновление событий ==="
echo "Глубина: $DAYS дней"
echo ""

# 1. Парсинг
echo ">>> Парсинг источников..."
python3 parser.py --days "$DAYS"
echo ""

# 2. Генерация страниц
echo ">>> Генерация страниц..."
python3 generate_pages.py
echo ""

# 3. Коммит и деплой
echo ">>> Деплой..."
git add events.json index.html cities/ sitemap.xml robots.txt images/events/

# Коммитим только если есть изменения
if git diff --cached --quiet; then
    echo "Нет изменений для коммита."
else
    COUNT=$(python3 -c "import json; d=json.load(open('events.json')); print(len(d))")
    git commit -m "Обновить события: $COUNT в базе"
    git push origin HEAD:main
    echo ""
    echo "✅ Задеплоено на mestov.net"
fi
