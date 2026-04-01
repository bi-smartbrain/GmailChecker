set -e

echo "=== Быстрое обновление GmailChecker ==="

# 1. Останавливаем и удаляем старый контейнер
echo "1. Останавливаем контейнер..."
cd /opt/GmailChecker
docker-compose down

# 2. Обновляем код из git
echo "2. Обновляем код..."
git reset --hard HEAD
git pull origin master

# 3. Пересобираем образ
echo "3. Пересобираем образ..."
docker-compose build

# 4. Запускаем контейнер
echo "4. Запускаем контейнер..."
docker-compose up -d

echo "=== Обновление завершено ==="
echo "=== Контейнер запущен ==="
