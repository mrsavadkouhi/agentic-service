#!/usr/bin/env bash
set -euo pipefail

# psql reads passwords from the environment, not command-line arguments.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv app_password APP_DB_PASSWORD
\getenv temporal_password TEMPORAL_DB_PASSWORD
CREATE ROLE agentic LOGIN PASSWORD :'app_password';
CREATE DATABASE agentic OWNER agentic;
CREATE ROLE temporal LOGIN PASSWORD :'temporal_password';
CREATE DATABASE temporal OWNER temporal;
CREATE DATABASE temporal_visibility OWNER temporal;
SQL

