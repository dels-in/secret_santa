#!/bin/bash
echo "🚀 Запуск Secret Santa Bot..."

# Run migrations
python migrations.py

# Start bot
python bot.py