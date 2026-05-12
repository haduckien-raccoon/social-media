from os import error
import random
from datetime import datetime, timedelta

# =========================
# CONFIG
# =========================
TOTAL_SAMPLES = 800

IP_POOL = [
    "192.168.1.10",
    "192.168.1.15",
    "10.0.0.5",
    "172.16.0.2",
    "203.113.1.5",
    "8.8.8.8",
    "1.1.1.1",
]

METHODS = ["GET", "POST", "PUT", "DELETE"]

PATHS = [
    "/",
    "/login",
    "/register",
    "/dashboard",
    "/api/users",
    "/api/posts",
    "/api/comments",
    "/admin",
    "/profile",
    "/upload",
]

STATUS_CODES = [200, 201, 204, 301, 400, 401, 403, 404, 500]

USER_AGENTS = [
    "Mozilla/5.0 Chrome/124.0",
    "Mozilla/5.0 Firefox/125.0",
    "PostmanRuntime/7.36.0",
    "curl/8.0.1",
    "Python-requests/2.31.0",
]

ERROR_MESSAGES = [
    "Database connection timeout",
    "Permission denied",
    "JWT token invalid",
    "Internal server error",
    "Redis connection failed",
    "Object does not exist",
    "Upload failed",
    "Memory overflow detected",
]

# =========================
# GENERATE ACCESS LOG
# =========================
start_time = datetime.now() - timedelta(days=3)

with open("access.log", "w", encoding="utf-8") as access_file:
    for i in range(TOTAL_SAMPLES):
        timestamp = (
            start_time + timedelta(seconds=random.randint(1, 250000))
        ).strftime("%d/%b/%Y:%H:%M:%S +0700")

        ip = random.choice(IP_POOL)
        method = random.choice(METHODS)
        path = random.choice(PATHS)
        status = random.choice(STATUS_CODES)
        size = random.randint(200, 10000)
        agent = random.choice(USER_AGENTS)

        log_line = (
            f'{ip} - - [{timestamp}] '
            f'"{method} {path} HTTP/1.1" '
            f'{status} {size} '
            f'"-" "{agent}"\n'
        )

        access_file.write(log_line)

# =========================
# GENERATE ERROR LOG
# =========================
with open("error.log", "w", encoding="utf-8") as error_file:
    for i in range(TOTAL_SAMPLES):
        timestamp = (
            start_time + timedelta(seconds=random.randint(1, 250000))
        ).strftime("%Y/%m/%d %H:%M:%S")

        pid = random.randint(1000, 9999)
        tid = random.randint(10000, 99999)
        error_message = random.choice(ERROR_MESSAGES)

        log_line = (
            f'[{timestamp}] '
            f'[error] {pid}#{tid}: '
            f'*{random.randint(1, 9999)} '
            f'{error_message}\n'
        )

        error_file.write(log_line)

print("Done generating 800 samples for access.log and error.log")
