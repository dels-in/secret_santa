FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories for logs
RUN mkdir -p /app/logs

# Run migrations and start bot
CMD ["sh", "-c", "python migrations.py && python bot.py"]