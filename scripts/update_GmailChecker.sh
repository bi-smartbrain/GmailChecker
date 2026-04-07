set -e

echo "=== Безопасное обновление GmailChecker ==="

# 1. Обновляем код из git
echo "1. Обновляем код..."
cd /opt/GmailChecker
git fetch origin master
git reset --hard origin/master

# 2. Пересобираем и перезапускаем сервис без лишнего даунтайма
echo "2. Пересобираем и запускаем контейнер..."
docker-compose up -d --build --remove-orphans

# 3. Чистим неиспользуемые образы и build cache (safe)
echo "3. Чистим Docker мусор (safe)..."
docker image prune -f
docker builder prune -f --filter "until=168h"

# 4. Обновляем скрипт в /opt/auto
echo "4. Обновляем /opt/auto/update_GmailChecker.sh..."
cp scripts/update_GmailChecker.sh /opt/auto/update_GmailChecker.sh
chmod +x /opt/auto/update_GmailChecker.sh

echo "=== Обновление завершено ==="
echo "=== Контейнер запущен, cleanup выполнен ==="
