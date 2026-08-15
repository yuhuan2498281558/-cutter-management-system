# Cutter Management System

盾构刀具全生命周期管理系统（Cutter Management System）用于记录盾构项目、盾构机、刀盘刀位、刀具档案、开仓换刀、磨损、成本和掘进数据，并提供分析、移动录入和可选的三维模型入口。

This project is a Django + Vue 3 application for shield-machine cutter lifecycle management. It is intended as a maintainable engineering software foundation and demo system. Real project drawings, reports, credentials, and operational data are not part of the public distribution.

## Features

- Project and shield-machine management
- Cutter categories, cutter positions, tool archives, and lifecycle history
- Warehouse-opening and tool-change records with stratum and ring-number context
- Wear condition, abnormal event, cost, and service-life tracking
- Analysis endpoints and export-oriented data views
- Mobile tool-change entry and permission-aware menus
- Optional AI assistant and BIMFace integration, both disabled until configured

## Architecture

- Backend: Python, Django, Django REST Framework, Channels, Celery
- Frontend: Vue 3, TypeScript, Vite, Element Plus, Fast CRUD
- Data services: PostgreSQL (recommended), Redis (Celery/Channels)
- HTTP/WS serving: Django ASGI with Daphne in development and production

The backend entry point is `backend/manage.py`; the frontend lives in `web/`. Shield business modules are under `backend/application/shield/` and `web/src/views/shield/`.

## Quick start

Requirements: Python 3.11+, Node.js 18+, PostgreSQL 14+ and Redis 6+ for the full stack.

1. Create a local environment file from `.env.example` and set a unique `DJANGO_SECRET_KEY`, database password, and allowed hosts.
2. Install backend dependencies:

   ```powershell
   cd backend
   python -m pip install -r requirements.txt
   python manage.py migrate
   python manage.py init
   python manage.py init_area
   python -m daphne -b 0.0.0.0 -p 8000 application.asgi:application
   ```

3. Install and start the frontend:

   ```powershell
   cd web
   npm install
   npm run dev
   ```

   The Vite development server normally runs at `http://localhost:5173` and proxies `/api` and `/ws` to the backend.

Docker definitions are provided in `docker-compose.yml` and `docker-compose.db.yml`. Review environment values and bind addresses before using them outside a local machine.

## Configuration and security

- Never commit `.env`, `backend/.env*`, `web/.env*`, database dumps, logs, generated builds, API keys, BIMFace identifiers, or real project files.
- Use `backend/conf/env.example.py` and the `web/.env.*.example` files as templates only.
- Set `DJANGO_SECRET_KEY` in every non-development deployment. The public fallback is deliberately development-only.
- AI, AMap, and BIMFace integrations require runtime credentials and are optional.
- Treat imported CSV/JSON data as potentially sensitive; publish only synthetic or explicitly authorized examples.

## Tests and checks

```powershell
cd backend
python manage.py check
python manage.py test application.shield.tests

cd ../web
npm run build
```

The repository is being prepared for repeatable CI. Visual pages and exports should also be checked in a browser when UI or reporting code changes.

## License and upstream

The repository is distributed under the Apache License 2.0. It contains code derived from [Django-Vue3-Admin](https://gitee.com/huge-dream/django-vue3-admin); its copyright and attribution notices are retained in `NOTICE`. Please read `LICENSE` and `NOTICE` before redistributing a modified copy.

## Contributing and security

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development conventions and [`SECURITY.md`](SECURITY.md) for responsible vulnerability reports. Do not open an issue containing credentials, customer data, drawings, or other confidential material.

The project is an evolving open-source foundation. See [`CHANGELOG.md`](CHANGELOG.md) for release notes and the GitHub issue tracker for the current roadmap.
