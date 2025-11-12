#!/bin/bash
# Копируем bot.py в /app (куда примонтирован Volume)
cp /app/bot.py /app/bot.py 2>/dev/null || cp bot.py /app/bot.py

# Запускаем
python /app/bot.py
