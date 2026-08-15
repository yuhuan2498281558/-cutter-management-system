# Deployment notes

This document intentionally contains no hostnames, IP addresses, usernames, passwords, or project-specific infrastructure details. Adapt it to your own approved environment.

## Before deployment

- Provision PostgreSQL and Redis on a private network.
- Create a deployment-only `.env` from the repository `.env.example`.
- Generate a unique `DJANGO_SECRET_KEY`, database password, Redis password, and any optional integration keys.
- Set `DJANGO_DEBUG=false` and restrict `DJANGO_ALLOWED_HOSTS` to the real service domains.
- Configure TLS and a reverse proxy before exposing the application to the internet.

## Docker deployment

```bash
cp .env.example .env
# edit .env and replace every placeholder
docker compose up -d --build
docker compose exec daoju-django python manage.py migrate
docker compose exec daoju-django python manage.py init
docker compose exec daoju-django python manage.py init_area
```

The compose file binds the application service to localhost by default. Put it behind an authenticated reverse proxy when remote access is required. Do not commit the resulting `.env`, database volumes, media uploads, logs, or backups.

## Operational checks

- Confirm database backups and restore procedures before importing any real data.
- Monitor application, Celery, Redis, and reverse-proxy logs without storing credentials in them.
- Keep BIMFace, AMap, and AI integrations disabled unless their data-sharing and key-rotation policies are approved.
