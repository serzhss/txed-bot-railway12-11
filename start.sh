#!/bin/bash
echo "=== ДИАГНОСТИКА ПУТИ ==="
echo "Текущая папка: $(pwd)"
echo "Файлы в корне:"
ls -la
echo "Файлы в /app:"
ls -la /app || echo "/app не существует"
echo "Копируем bot.py → /app/bot.py"
cp bot.py /app/bot.py && echo "Копирование УСПЕШНО" || echo "ОШИБКА копирования"
echo "Запускаем бота..."
python /app/bot.py
