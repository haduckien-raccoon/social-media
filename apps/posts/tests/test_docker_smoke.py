import base64
import os
import socket
import subprocess
import time
from pathlib import Path

from django.test import SimpleTestCase
from django.test import tag


COMPOSE_FILE = "docker/docker-compose.yml"
APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_HOST_PORT = int(os.getenv("APP_HOST_PORT", "8001"))


def _run(command: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(command, returncode=127, stdout="", stderr=str(exc))


def _docker_available() -> bool:
    docker_bin = _run(["bash", "-lc", "command -v docker"], timeout=5)
    if docker_bin.returncode != 0:
        return False

    info = _run(["docker", "info"], timeout=10)
    return info.returncode == 0


def _wait_http_ready(url: str, timeout_seconds: int = 120) -> bool:
    import urllib.request
    import urllib.error

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status < 500:
                    return True
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def _probe_websocket_upgrade(host: str = APP_HOST, port: int = APP_HOST_PORT, path: str = "/ws/realtime/") -> int:
    """Open a raw websocket upgrade request and return HTTP status code."""

    websocket_key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {websocket_key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )

    with socket.create_connection((host, port), timeout=5) as conn:
        conn.sendall(request.encode("ascii"))
        response = conn.recv(4096).decode("utf-8", errors="ignore")

    first_line = response.splitlines()[0] if response else ""
    parts = first_line.split()
    if len(parts) < 2:
        return 0
    try:
        return int(parts[1])
    except ValueError:
        return 0


class DockerSmokeConfigTests(SimpleTestCase):
    def test_compose_contains_required_services(self):
        compose = Path(COMPOSE_FILE).read_text(encoding="utf-8")

        self.assertIn("app:", compose)
        self.assertIn("mysql:", compose)
        self.assertIn("redis:", compose)
        self.assertIn("depends_on:", compose)
        self.assertIn("condition: service_healthy", compose)
        self.assertIn("healthcheck:", compose)
        self.assertIn("socket.create_connection", compose)

    def test_compose_config_is_valid(self):
        result = _run(["docker", "compose", "-f", COMPOSE_FILE, "config"], timeout=60)
        if result.returncode != 0 and (
            "Cannot connect to the Docker daemon" in result.stderr
            or "No such file or directory" in result.stderr
        ):
            self.skipTest("Docker daemon is not available in current environment")
        self.assertEqual(result.returncode, 0, msg=f"docker compose config failed: {result.stderr}")

    def test_entrypoint_runs_auto_setup(self):
        entrypoint = Path("docker/entrypoint.sh").read_text(encoding="utf-8")

        self.assertIn("wait_for_db", entrypoint)
        self.assertIn("wait_for_redis", entrypoint)
        self.assertIn("migrate --noinput", entrypoint)
        self.assertIn("daphne", entrypoint)

    def test_dockerfile_is_production_ready(self):
        dockerfile = Path("docker/Dockerfile").read_text(encoding="utf-8")

        self.assertIn("python:3.12-slim", dockerfile)
        self.assertIn("ENTRYPOINT", dockerfile)
        self.assertIn("appuser", dockerfile)


@tag("docker_smoke")
class DockerComposeRuntimeSmokeTests(SimpleTestCase):
    def test_compose_up_health_api_and_ws(self):
        if os.getenv("RUN_DOCKER_SMOKE", "0") != "1":
            self.skipTest("Set RUN_DOCKER_SMOKE=1 to run docker runtime smoke test")

        if not _docker_available():
            self.skipTest("Docker daemon is not available")

        up_cmd = ["docker", "compose", "-f", COMPOSE_FILE, "up", "--build", "-d"]
        down_cmd = ["docker", "compose", "-f", COMPOSE_FILE, "down", "-v"]

        try:
            up_result = _run(up_cmd, timeout=600)
            self.assertEqual(up_result.returncode, 0, msg=f"docker compose up failed: {up_result.stderr}")

            healthy = _wait_http_ready(
                f"http://{APP_HOST}:{APP_HOST_PORT}/api/v1/posts",
                timeout_seconds=180,
            )
            self.assertTrue(healthy, "App HTTP endpoint is not reachable after compose up")

            ws_status = _probe_websocket_upgrade(APP_HOST, APP_HOST_PORT)
            # 101: upgraded. 401/403: endpoint exists but auth rejected.
            self.assertIn(ws_status, {101, 401, 403})
        finally:
            _run(down_cmd, timeout=120)
