#!/bin/bash
echo "=== ДИАГНОСТИКА ПУТИ ==="
echo "Текущая папка: $(pwd)"
echo "Файлы в корне:"
ls -la
echo "Файлы в /app:"
ls -la /app
echo "Копируем bot.py → /app/bot.py"
cp bot.py /app/bot.py && echo "Копирование УСПЕШНО" || echo "ОШИБКА"
echo "Запускаем бота..."
python /app/bot.py
