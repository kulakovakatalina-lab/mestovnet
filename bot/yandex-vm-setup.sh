#!/bin/bash
# Скрипт автозапуска бота «Местов.Нет» для виртуальной машины Яндекс Облака.
# Вставляется в поле «user data» при создании VM (образ Ubuntu 22.04).
# При первом запуске машина сама установит и запустит бота через systemd.
#
# ВАЖНО: впиши свой токен в строку BOT_TOKEN ниже перед вставкой в форму.

set -e

# --- настройки ---
BOT_TOKEN="ВСТАВЬ_СЮДА_ТОКЕН"
ADMIN_ID="267459702"
REPO="https://github.com/kulakovakatalina-lab/mestovnet.git"
APP_DIR="/opt/mestovnet"
BOT_DIR="$APP_DIR/bot"

# --- установка системных пакетов ---
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git

# --- код бота ---
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull
else
  git clone "$REPO" "$APP_DIR"
fi

# --- виртуальное окружение и зависимости ---
python3 -m venv "$BOT_DIR/.venv"
"$BOT_DIR/.venv/bin/pip" install --upgrade pip
"$BOT_DIR/.venv/bin/pip" install -r "$BOT_DIR/requirements.txt"

# --- переменные окружения ---
cat > "$BOT_DIR/.env" <<EOF
BOT_TOKEN=$BOT_TOKEN
ADMIN_ID=$ADMIN_ID
DATA_DIR=$BOT_DIR
EOF

# --- systemd-сервис: автозапуск и перезапуск при сбое ---
cat > /etc/systemd/system/mestov-bot.service <<EOF
[Unit]
Description=Mestov.Net Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$BOT_DIR
ExecStart=$BOT_DIR/.venv/bin/python $BOT_DIR/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable mestov-bot.service
systemctl restart mestov-bot.service

echo "Бот установлен и запущен."
