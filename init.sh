#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=".env"

if [[ ! -f "$ENV_FILE" ]]; then
  cp .env.example "$ENV_FILE"
  if command -v openssl >/dev/null 2>&1; then
    secret="$(openssl rand -hex 32)"
  else
    secret="$(date +%s)-change-this-secret"
  fi
  sed -i "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=$secret|" "$ENV_FILE"
  echo "Created $ENV_FILE from .env.example. Review database and host settings before continuing."
fi

docker compose up -d --build
docker compose exec daoju-django python manage.py migrate
docker compose exec daoju-django python manage.py init
docker compose exec daoju-django python manage.py init_area

echo "The local services are running. Open http://localhost:18080 after checking the generated configuration."
