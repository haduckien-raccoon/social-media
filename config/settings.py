# config/settings/base.py
import os
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------
# BASE_DIR & load .env
# ---------------------------
BASE_DIR = Path(__file__).resolve().parent.parent  # project root
# đảm bảo load .env trước khi dùng bất kỳ biến nào
dotenv_path = BASE_DIR / ".env"
if dotenv_path.exists():
    load_dotenv(dotenv_path, override=True)

# ---------------------------
# SECRET KEY, DEBUG, ALLOWED HOSTS
# ---------------------------
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-secret-key")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() == "true"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]


def _env_int(name, default):
    raw_value = os.getenv(name, str(default))
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    raw_value = os.getenv(name, str(default))
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default


APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
AI_SERVICE_URL = os.getenv("AI_BASE_URL", "http://127.0.0.1:8082").rstrip("/")
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = _env_int("REDIS_PORT", 6379)
REDIS_DB = _env_int("REDIS_DB", 0)
REDIS_SOCKET_TIMEOUT = _env_float("REDIS_SOCKET_TIMEOUT", 0.2)
REDIS_SOCKET_CONNECT_TIMEOUT = _env_float("REDIS_SOCKET_CONNECT_TIMEOUT", 0.2)
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "your_password")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

# ---------------------------
# INSTALLED APPS
# ---------------------------
INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "channels",
    "corsheaders",
    "django_celery_beat",
    "django_celery_results",
    # Your apps
    "apps.admin.apps.CustomAdminConfig",
    "apps.core",
    "apps.accounts",
    "apps.friends",
    "apps.posts",
    "apps.search",
    "apps.groups",
    "apps.chat",
    "apps.notifications",
    "apps.moderation",
    "apps.middleware",
]

# ---------------------------
# MIDDLEWARE
# ---------------------------
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "apps.middleware.jwt_auth.JWTAuthMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    'apps.admin.middleware.SystemLoggingMiddleware',
]

ROOT_URLCONF = "config.urls"

# ---------------------------
# TEMPLATES
# ---------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

CHANNEL_LAYER_BACKEND = os.getenv("CHANNEL_LAYER_BACKEND", "inmemory").strip().lower()
if CHANNEL_LAYER_BACKEND == "redis":
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [(REDIS_HOST, REDIS_PORT)],
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        },
    }

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------
# DATABASES
# ---------------------------
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")

if MYSQL_DATABASE and MYSQL_USER and MYSQL_PASSWORD:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": MYSQL_DATABASE,
            "USER": MYSQL_USER,
            "PASSWORD": MYSQL_PASSWORD,
            "HOST": MYSQL_HOST,
            "PORT": MYSQL_PORT,
            "OPTIONS": {"init_command": "SET sql_mode='STRICT_TRANS_TABLES'"},
        }
    }
else:
    # fallback SQLite cho dev
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ---------------------------
# PASSWORD VALIDATION
# ---------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
# Security
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

# Email
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv("EMAIL_USER", "haduckien1709@gmail.com")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_PASSWORD", "app_password_here")
SITE_NAME = os.getenv("SITE_NAME", "Social Media Platform")
# ---------------------------
# INTERNATIONALIZATION
# ---------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Ho_Chi_Minh"
USE_I18N = True
USE_TZ = True

# ---------------------------
# STATIC & MEDIA
# ---------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/images/"
MEDIA_ROOT = BASE_DIR / "images"
IMAGES_URL = MEDIA_URL
IMAGES_ROOT = MEDIA_ROOT
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------
# LOGS
# ---------------------------
LOGGING_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOGGING_DIR, exist_ok=True)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} | {module} | {message}',
            'style': '{',
            'datefmt': '%d/%m/%Y %H:%M:%S'
        },
    },
    'handlers': {
        # Handler ghi access.log
        'access_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(LOGGING_DIR, 'access.log'),
            'maxBytes': 1024 * 1024 * 5, # Tối đa 5MB/file
            'backupCount': 3, # Giữ lại 3 file cũ nhất
            'formatter': 'verbose',
        },
        # Handler ghi error.log
        'error_file': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(LOGGING_DIR, 'error.log'),
            'maxBytes': 1024 * 1024 * 5,
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        # Logger tùy chỉnh cho các truy cập bình thường
        'system_access': {
            'handlers': ['access_file'],
            'level': 'INFO',
            'propagate': False,
        },
        # Logger mặc định của Django khi có lỗi 500 Server Error
        'django.request': {
            'handlers': ['error_file'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}