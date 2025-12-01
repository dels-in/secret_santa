# Используем официальный образ Python
FROM python:3.11-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файл с зависимостями
COPY requirements.txt .

# Устанавливаем зависимости Python
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код проекта
COPY . .

# Создаем директории для логов и данных
RUN mkdir -p /app/logs /app/data

# Устанавливаем права на запись
RUN chmod -R 777 /app/logs /app/data

# Запускаем миграции и бота
CMD ["sh", "-c", "python migrations.py && echo 'Миграции выполнены, запускаем бота...' && python bot.py"]