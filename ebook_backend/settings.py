import os
from pathlib import Path
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent


def read_env_file():
    # Simple .env reader, so beginners do not need one more package.
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        clean_line = line.strip()
        if not clean_line or clean_line.startswith("#") or "=" not in clean_line:
            continue
        key, value = clean_line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


read_env_file()

SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "dev-only-ebook-secret-key-change-before-production-2026",
)
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() == "true"
default_allowed_hosts = "*" if DEBUG else "127.0.0.1,localhost"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", default_allowed_hosts).split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "social_django",
    "accounts",
    "library",
    "content",
    "banners",
    "youtube_feed",
    "ebook_reader",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ebook_backend.urls"

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
                "social_django.context_processors.backends",
                "social_django.context_processors.login_redirect",
            ],
        },
    },
]

WSGI_APPLICATION = "ebook_backend.wsgi.application"

db_engine = os.environ.get("DB_ENGINE", "sqlite").strip().lower()

if db_engine == "mysql":
    import pymysql

    pymysql.install_as_MySQLdb()
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get("DB_NAME", "ebook_db"),
            "USER": os.environ.get("DB_USER", "root"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("DB_PORT", "3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = (
    "social_core.backends.google.GoogleOAuth2",
    "django.contrib.auth.backends.ModelBackend",
)

LOGIN_URL = "/auth/login/google-oauth2/"
LOGIN_REDIRECT_URL = "/api/auth/google/success/"
LOGIN_ERROR_URL = "/api/auth/google/error/"
LOGOUT_REDIRECT_URL = "/"

SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
SOCIAL_AUTH_GOOGLE_OAUTH2_SCOPE = ["email", "profile"]
SOCIAL_AUTH_URL_NAMESPACE = "social"
SOCIAL_AUTH_LOGIN_REDIRECT_URL = LOGIN_REDIRECT_URL
SOCIAL_AUTH_LOGIN_ERROR_URL = LOGIN_ERROR_URL
SOCIAL_AUTH_REDIRECT_IS_HTTPS = os.getenv("SOCIAL_AUTH_REDIRECT_IS_HTTPS", "True").lower() == "true"
SOCIAL_AUTH_PIPELINE = (
    "social_core.pipeline.social_auth.social_details",
    "social_core.pipeline.social_auth.social_uid",
    "social_core.pipeline.social_auth.auth_allowed",
    "social_core.pipeline.social_auth.social_user",
    "social_core.pipeline.user.get_username",
    "social_core.pipeline.social_auth.associate_by_email",
    "social_core.pipeline.user.create_user",
    "social_core.pipeline.social_auth.associate_user",
    "social_core.pipeline.social_auth.load_extra_data",
    "social_core.pipeline.user.user_details",
)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'static'
]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE", "@NidhivanRas")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:8081,http://127.0.0.1:8081",
    ).split(",")
    if origin.strip()
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.AllowAny",
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=7),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
}

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "False").lower() == "true"
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

EBOOK_SYSTEM_ENABLED = os.getenv("EBOOK_SYSTEM_ENABLED", os.getenv("EBOOK_READER_ENABLED", "True")).lower() == "true"
EBOOK_WEB_READER_ENABLED = os.getenv("EBOOK_WEB_READER_ENABLED", os.getenv("EBOOK_READER_ENABLED", "True")).lower() == "true"
EBOOK_MOBILE_READER_ENABLED = os.getenv("EBOOK_MOBILE_READER_ENABLED", "True").lower() == "true"
EBOOK_READER_STAFF_ONLY = os.getenv("EBOOK_READER_STAFF_ONLY", "True").lower() == "true"
EBOOK_PROCESSING_ENABLED = os.getenv("EBOOK_PROCESSING_ENABLED", "True").lower() == "true"
EBOOK_READER_ENABLED = EBOOK_SYSTEM_ENABLED and EBOOK_WEB_READER_ENABLED
EBOOK_READER_TOC_SCAN_PAGE_LIMIT = int(os.getenv("EBOOK_READER_TOC_SCAN_PAGE_LIMIT", "40"))
EBOOK_MAX_PDF_PAGES = int(os.getenv("EBOOK_MAX_PDF_PAGES", "2500"))
EBOOK_MAX_PDF_SIZE_MB = int(os.getenv("EBOOK_MAX_PDF_SIZE_MB", "500"))
EBOOK_SIGNED_URL_EXPIRES_SECONDS = int(os.getenv("EBOOK_SIGNED_URL_EXPIRES_SECONDS", "900"))
EBOOK_OCR_ENGINE = os.getenv("EBOOK_OCR_ENGINE", "tesseract")
EBOOK_OCR_LANGUAGES = os.getenv("EBOOK_OCR_LANGUAGES", "hin+eng")
EBOOK_OCR_TESSERACT_CONFIG = os.getenv("EBOOK_OCR_TESSERACT_CONFIG", "--psm 6")
EBOOK_RENDER_DPI = int(os.getenv("EBOOK_RENDER_DPI", "300"))
EBOOK_OCR_TIMEOUT_SECONDS = int(os.getenv("EBOOK_OCR_TIMEOUT_SECONDS", "60"))
EBOOK_OCR_PREPROCESSING = {
    "grayscale": os.getenv("EBOOK_OCR_GRAYSCALE", "True").lower() == "true",
    "threshold": os.getenv("EBOOK_OCR_THRESHOLD", "True").lower() == "true",
    "threshold_value": int(os.getenv("EBOOK_OCR_THRESHOLD_VALUE", "180")),
    "deskew": os.getenv("EBOOK_OCR_DESKEW", "False").lower() == "true",
    "border_removal": os.getenv("EBOOK_OCR_BORDER_REMOVAL", "False").lower() == "true",
}
