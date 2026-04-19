#!/bin/sh
set -eu

MODE="${1:-web}"

python - <<'PY'
import os
import socket
import sys
import time

timeout_seconds = int(os.getenv("WAIT_TIMEOUT", "90"))
deadline = time.time() + timeout_seconds

services = [
    ("MySQL", os.getenv("MYSQL_HOST", "mysql"), int(os.getenv("MYSQL_PORT", "3306"))),
    ("Redis", os.getenv("REDIS_HOST", "redis"), int(os.getenv("REDIS_PORT", "6379"))),
]

for service_name, host, port in services:
    while True:
        try:
            with socket.create_connection((host, port), timeout=2):
                print(f"[boot] {service_name} is ready at {host}:{port}", flush=True)
                break
        except OSError as exc:
            if time.time() >= deadline:
                print(
                    f"[boot] Timeout waiting for {service_name} at {host}:{port}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                raise SystemExit(1)
            print(f"[boot] Waiting for {service_name} at {host}:{port}...", flush=True)
            time.sleep(2)
PY

echo "[boot] Applying migrations..."
python manage.py migrate --noinput

if [ "$MODE" = "test" ]; then
    echo "[boot] Running test suite..."
    exec python manage.py test -v 2
fi

echo "[boot] Starting ASGI server..."
exec uvicorn config.asgi:application --host 0.0.0.0 --port 8080 --workers "${UVICORN_WORKERS:-1}" --proxy-headers
