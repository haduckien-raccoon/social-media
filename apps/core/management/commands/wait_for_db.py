"""Wait until default database accepts connections."""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.db import connections


class Command(BaseCommand):
    help = "Wait for database readiness before starting the app"

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=60)
        parser.add_argument("--interval", type=float, default=2.0)

    def handle(self, *args, **options):
        timeout = int(options["timeout"])
        interval = float(options["interval"])

        deadline = time.monotonic() + timeout
        while True:
            try:
                connection = connections["default"]
                connection.ensure_connection()
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                self.stdout.write(self.style.SUCCESS("Database is ready"))
                return
            except Exception as exc:  # pragma: no cover - startup command
                if time.monotonic() >= deadline:
                    raise RuntimeError("Database is not ready before timeout") from exc
                self.stdout.write(f"Waiting for database: {exc}")
                time.sleep(interval)
