#!/bin/sh
set -eu

python manage.py wait_for_db
python manage.py wait_for_redis

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec daphne -b 0.0.0.0 -p "${PORT:-8080}" config.asgi:application