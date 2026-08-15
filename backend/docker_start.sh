#!/bin/bash
set -e

wait_for_service() {
  local name="$1"
  local host="$2"
  local port="$3"

  if [ -z "$host" ] || [ -z "$port" ]; then
    return 0
  fi

  echo "Waiting for ${name} at ${host}:${port}..."
  python -c "import socket, sys, time
host = sys.argv[1]
port = int(sys.argv[2])
deadline = time.time() + 60
while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=2):
            print('Connected to %s:%s' % (host, port))
            raise SystemExit(0)
    except OSError:
        time.sleep(2)
raise SystemExit('Timed out waiting for %s:%s' % (host, port))
" "$host" "$port"
}

wait_for_service "database" "${DATABASE_HOST}" "${DATABASE_PORT:-5432}"
wait_for_service "redis" "${REDIS_HOST}" "${REDIS_PORT:-6379}"

if [ "${RUN_MIGRATIONS_ON_START:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi

if [ "${RUN_INIT_ON_START:-1}" = "1" ]; then
  python manage.py init -y || true
fi

uvicorn application.asgi:application --port 8000 --host 0.0.0.0 --workers 4
