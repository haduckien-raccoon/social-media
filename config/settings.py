# config/settings/base.py
import os
import sys
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
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# ---------------------------
# INSTALLED APPS
# ---------------------------
INSTALLED_APPS = [
    "channels",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    # Your apps
    "apps.core",
    "apps.accounts",
    "apps.friends",
    "apps.posts",
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
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "apps.core.request_context.RequestContextMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.middleware.jwt_auth.JWTAuthMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
MYSQL_TEST_USER = os.getenv("MYSQL_TEST_USER")
MYSQL_TEST_PASSWORD = os.getenv("MYSQL_TEST_PASSWORD")

if MYSQL_DATABASE and MYSQL_USER and MYSQL_PASSWORD:
    db_user = MYSQL_USER
    db_password = MYSQL_PASSWORD

    # Test runner needs CREATE/DROP DB permission for test_<db_name>.
    if "test" in sys.argv and MYSQL_TEST_USER:
        db_user = MYSQL_TEST_USER
        db_password = MYSQL_TEST_PASSWORD or ""

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": MYSQL_DATABASE,
            "USER": db_user,
            "PASSWORD": db_password,
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
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
SERVE_MEDIA_FROM_DJANGO = os.getenv("SERVE_MEDIA_FROM_DJANGO", "True").lower() == "true"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/1")
PRESENCE_TTL_SECONDS = int(os.getenv("PRESENCE_TTL_SECONDS", 30))
PRESENCE_GRACE_SECONDS = int(os.getenv("PRESENCE_GRACE_SECONDS", 30))
TYPING_TTL_SECONDS = int(os.getenv("TYPING_TTL_SECONDS", 6))
TYPING_THROTTLE_SECONDS = int(os.getenv("TYPING_THROTTLE_SECONDS", 1))
COMMENT_EDIT_WINDOW_MINUTES = int(os.getenv("COMMENT_EDIT_WINDOW_MINUTES", 15))
WS_RATE_WINDOW_SECONDS = int(os.getenv("WS_RATE_WINDOW_SECONDS", 10))
WS_RATE_MAX_MESSAGES = int(os.getenv("WS_RATE_MAX_MESSAGES", 20))
WS_RATE_TYPING_MAX = int(os.getenv("WS_RATE_TYPING_MAX", 8))
WS_RATE_HEARTBEAT_MAX = int(os.getenv("WS_RATE_HEARTBEAT_MAX", 15))
WS_RATE_VIOLATION_CLOSE_THRESHOLD = int(os.getenv("WS_RATE_VIOLATION_CLOSE_THRESHOLD", 5))
POST_MAX_ATTACHMENTS = int(os.getenv("POST_MAX_ATTACHMENTS", 4))
POST_ATTACHMENT_MAX_SIZE_MB = int(os.getenv("POST_ATTACHMENT_MAX_SIZE_MB", 20))
POST_ALLOWED_IMAGE_EXTENSIONS = os.getenv("POST_ALLOWED_IMAGE_EXTENSIONS", "jpg,jpeg,png,webp,gif").split(",")
POST_ALLOWED_AUDIO_EXTENSIONS = os.getenv("POST_ALLOWED_AUDIO_EXTENSIONS", "mp3,wav,ogg,m4a").split(",")
POST_ALLOWED_FILE_EXTENSIONS = os.getenv("POST_ALLOWED_FILE_EXTENSIONS", "pdf,txt,doc,docx,xls,xlsx,ppt,pptx,zip,rar").split(",")
POST_ALLOWED_IMAGE_CONTENT_TYPES = os.getenv(
    "POST_ALLOWED_IMAGE_CONTENT_TYPES",
    "image/jpeg,image/png,image/webp,image/gif",
).split(",")
POST_ALLOWED_AUDIO_CONTENT_TYPES = os.getenv(
    "POST_ALLOWED_AUDIO_CONTENT_TYPES",
    "audio/mpeg,audio/wav,audio/ogg,audio/mp4",
).split(",")

LOG_FORMAT = os.getenv("LOG_FORMAT", "json").lower()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
APP_PUBLIC_BASE_URL = os.getenv("APP_PUBLIC_BASE_URL", "http://127.0.0.1:8001").rstrip("/")

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.core.authentication.CookieJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
}

if LOG_FORMAT == "json":
    default_formatter = {"()": "apps.core.logging_utils.JSONLogFormatter"}
else:
    default_formatter = {
        "format": (
            "%(asctime)s %(levelname)s %(name)s %(message)s "
            "request_id=%(request_id)s user_id=%(user_id)s action=%(action)s"
        )
    }

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_context": {
            "()": "apps.core.logging_utils.RequestContextFilter",
        },
    },
    "formatters": {
        "default": default_formatter,
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["request_context"],
            "formatter": "default",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "apps.request": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}
