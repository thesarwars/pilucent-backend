#!/bin/bash
set -e
exec >> /var/log/balanzify-deploy.log 2>&1
echo "=== Deploy started at $(date) ==="

cd /home/ubuntu/balanzify/balanzify_backend

# 1. Build and restart containers, remove orphan containers (e.g. old db)
docker compose up --build -d --remove-orphans

# 2. Run Django Migrations as the DB OWNER.
#    The app container connects as the restricted `balanzify_app` role so
#    PostgreSQL Row-Level Security is enforced at runtime -- but that role has
#    DML only and CANNOT run migrations (no DDL / no FORCE RLS). Override the DB
#    credentials to the owner role for this one command.
#
#    The owner credentials live in /etc/balanzify/deploy-secrets on the deploy
#    host (root-only, never in git) since the RDS master password reset on
#    2026-08-21. The file sets DB_MIGRATION_USER / DB_MIGRATION_PASSWORD.
if [ -f /etc/balanzify/deploy-secrets ]; then
    . /etc/balanzify/deploy-secrets
fi
: "${DB_MIGRATION_USER:=postgres_dev}"
if [ -z "${DB_MIGRATION_PASSWORD:-}" ]; then
    echo "ERROR: DB_MIGRATION_PASSWORD is not set; put it in /etc/balanzify/deploy-secrets"
    exit 1
fi
docker compose exec -T \
    -e DB_USER="$DB_MIGRATION_USER" \
    -e DB_PASSWORD="$DB_MIGRATION_PASSWORD" \
    app python3 manage.py migrate --noinput

# 3. Collect Static files
docker compose exec -T app python3 manage.py collectstatic --noinput

# 4. Restart the service
docker compose restart app

# 5. Clean up unused images to save disk space on EC2
docker image prune -f

echo "=== Deploy finished at $(date) ==="