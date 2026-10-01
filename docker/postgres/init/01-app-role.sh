#!/bin/sh
# Runs once, when the docker-compose.yml Postgres volume is first created.
#
# The owner role (POSTGRES_USER, "pilucent") runs migrations and owns every
# table. The app connects as the role named by DB_USER in .env (default
# "pilucent_app"): not a superuser, NOBYPASSRLS, and DML only -- the same split
# production uses, so Row-Level Security is actually enforced locally (a
# superuser connection would silently bypass it). See scripts/rls/README.md.
#
# Its name and password come from .env (DB_USER / DB_PASSWORD) through
# docker-compose.yml. Changing them later needs a fresh volume:
# `docker compose down -v`.
set -eu

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v app_user="$PILUCENT_APP_DB_USER" \
     -v app_password="$PILUCENT_APP_DB_PASSWORD" \
     -v db="$POSTGRES_DB" \
     -v owner="$POSTGRES_USER" <<'SQL'
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password' NOSUPERUSER NOBYPASSRLS;
GRANT CONNECT ON DATABASE :"db" TO :"app_user";
GRANT USAGE ON SCHEMA public TO :"app_user";
-- Tables and sequences the owner creates later (every migration) inherit these.
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO :"app_user";
SQL
