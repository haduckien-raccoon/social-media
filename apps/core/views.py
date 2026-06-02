import jwt
import redis
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from neo4j import GraphDatabase

from apps.accounts.models import User

def home(request):
    access_token = request.COOKIES.get("access")

    user = None
    is_authenticated = False

    if access_token:
        try:
            payload = jwt.decode(
                access_token,
                settings.SECRET_KEY,
                algorithms=["HS256"]
            )
            user_id = payload.get("user_id")
            user = User.objects.get(id=user_id)
            is_authenticated = True

        except jwt.ExpiredSignatureError:
            pass  # access token hết hạn
        except (jwt.InvalidTokenError, User.DoesNotExist):
            pass

    return render(request, "home.html", {
        "user": user,
        "is_authenticated": is_authenticated
    })


def health_check(request):
    checks = {}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc.__class__.__name__}"

    try:
        redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
        )
        redis_client.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc.__class__.__name__}"

    try:
        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
            connection_timeout=2,
        )
        try:
            driver.verify_connectivity()
        finally:
            driver.close()
        checks["neo4j"] = "ok"
    except Exception as exc:
        checks["neo4j"] = f"error: {exc.__class__.__name__}"

    healthy = all(value == "ok" for value in checks.values())

    return JsonResponse(
        {
            "status": "ok" if healthy else "degraded",
            "checks": checks,
        },
        status=200 if healthy else 503,
    )

def error_404_view(request, exception):
    return render(request, 'errors/error_404.html', status=404)

def error_500_view(request, exception):
    return render(request, 'errors/error_500.html', status=500)

def error_403_view(request, exception):
    return render(request, 'errors/error_403.html', status=403)

def error_401_view(request, exception):
    return render(request, 'errors/error_401.html', status=401)
