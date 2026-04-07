"""Wait until Redis endpoint is reachable."""

from __future__ import annotations

import os
import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Wait for redis readiness before starting realtime components"

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=60)
        parser.add_argument("--interval", type=float, default=2.0)

    def handle(self, *args, **options):
        try:
            import redis
        except ImportError:
            self.stdout.write("redis package not installed, skip wait_for_redis")
            return

        timeout = int(options["timeout"])
        interval = float(options["interval"])
        redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/1")

        deadline = time.monotonic() + timeout
        while True:
            try:
                client = redis.Redis.from_url(redis_url, decode_responses=True)
                client.ping()
                self.stdout.write(self.style.SUCCESS("Redis is ready"))
                return
            except Exception as exc:  # pragma: no cover - startup command
                if time.monotonic() >= deadline:
                    raise RuntimeError("Redis is not ready before timeout") from exc
                self.stdout.write(f"Waiting for redis: {exc}")
                time.sleep(interval)
