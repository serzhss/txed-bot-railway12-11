#!/bin/bash
# Копируем bot.py в /app (куда примонтирован Volume)
cp bot.py /app/bot.py

# Запускаем бота
python /app/bot.py
