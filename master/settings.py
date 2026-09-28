from celery.schedules import crontab
import os, sys

from dotenv import load_dotenv

from datetime import timedelta

from pathlib import Path

# Load environment variables from .env file
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("SECRET_KEY") or "django-insecure-pilucent-local-dev-only"

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DEBUG")

ALLOWED_HOSTS = ["*"]
# ALLOWED_HOSTS = [
#     "127.0.0.1",
#     "balanzifyapi.jumatechs.xyz",
#     "4xf0rlft-8000.asse.devtunnels.ms",
#     "localhost:8000",
#     "localhost",
#     "145.223.75.199",
# ]


# Application definition
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
THIRD_PARTY_APPS = [
    "channels",
    "corsheaders",
    "django_cleanup",
    "django_filters",
    "drf_spectacular",
    "rest_framework",
    "rest_framework_simplejwt",
    "simple_history",
    "versatileimagefield",
    "auditlog",
    "django_celery_results",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "storages",
]
BALANZIFY_APPS = [
    "accounts",
    "adminio",
    "addressio",
    "agencyio",
    "attendanceio",
    "attachmentio",
    "brandio",
    "categoryio",
    "chatio",
    "common",
    "companyio",
    "creditnoteio",
    "customerio",
    "currencyio",
    "datamigrationio",
    "employeeio",
    "fileroomio",
    "hris",
    "journalio",
    "livedemoio",
    "leaveio",
    "meapi",
    "messageio",
    "moovmoneyio",
    "notificationio",
    "publicapi",
    "purchaseio",
    "productio",
    "paymentio",
    "recurringio",
    "payrollio",
    "stockio",
    "nexusio",
    "salesio",
    "supplierio",
    "socailauthio",
    "subscriptionio",
    "tagio",
    "termio",
    "transactionio",
    "taxbanditsio",
    "weapi",
    "wirehouseio",
]

INSTALLED_APPS = ["daphne"] + DJANGO_APPS + THIRD_PARTY_APPS + BALANZIFY_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # whitenoise
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",  # cors
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "common.middleware.tenant.TenantContextMiddleware",  # multi-tenant company context (JWT -> contextvar + Postgres RLS GUC)
    "auditlog.middleware.AuditlogMiddleware",  # auditlog
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# django-silk is a request/SQL profiler that writes a row to the DB for every
# request and every query it sees. That is fine for local debugging but in
# production it adds a DB write (and a connection) to every request and bloats
# the database -- a real contributor to RDS connection-slot exhaustion. Enable
# it only in DEBUG, matching the silk URL gate in master/urls.py.
ENABLE_PROFILING = os.environ.get("DEBUG") == "True"
if ENABLE_PROFILING:
    INSTALLED_APPS += ["silk"]
    MIDDLEWARE += ["silk.middleware.SilkyMiddleware"]

ROOT_URLCONF = "master.urls"

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

WSGI_APPLICATION = "master.wsgi.application"
AUTH_USER_MODEL = "accounts.User"


# Database
# https://docs.djangoproject.com/en/4.1/ref/settings/#databases


# SQLite for testing
from django.core.exceptions import ImproperlyConfigured


def _require_env(name):
    """Read a required setting, or fail with a message that names it.

    `os.environ.get(name, "")` turns a missing setting into a confusing runtime
    error somewhere else; this turns it into an obvious one here.
    """
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(
            f"{name} is not set. Put it in the environment (.env on this host, "
            f"or the container env in production). It has no default."
        )
    return value


DATABASES = (
    {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
    if "test" in sys.argv
    else {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "balanzify_dev"),
            # The running app connects as the restricted role `balanzify_app` so
            # PostgreSQL Row-Level Security is actually enforced (a superuser like
            # postgres_dev bypasses RLS).
            #
            # IMPORTANT: `balanzify_app` has DML only (SELECT/INSERT/UPDATE/DELETE)
            # and CANNOT run migrations. Run `manage.py migrate` as the owner by
            # overriding the env for that step, e.g.:
            #     DB_USER=postgres_dev DB_PASSWORD='<postgres_dev pw>' python manage.py migrate
            "USER": os.environ.get("DB_USER", "balanzify_app"),
            # No fallback, deliberately. This carried the live `balanzify_app`
            # password as a literal default from 17b550ba until 2026-08-21, so
            # the production credential was readable by anyone with repo access
            # -- and it is in git history, which removing it here does not
            # undo. Rotate the role's password to actually close that.
            #
            # Required rather than defaulted to "": an empty password fails at
            # connect time with `password authentication failed`, which reads
            # like a wrong password and sends you looking in the wrong place.
            # The deploy has already lost an afternoon to exactly that
            # confusion. Missing configuration should say it is missing.
            #
            # Safe for the test suite: the SQLite branch above is chosen when
            # "test" is in sys.argv, and a conditional expression only
            # evaluates the branch it takes -- this dict is never built there.
            "PASSWORD": _require_env("DB_PASSWORD"),
            "HOST": os.environ.get(
                "DB_HOST", "balanzify-db-dev-v2.c9gk2imws53j.us-east-2.rds.amazonaws.com"
            ),
            "PORT": os.environ.get("DB_PORT", "5432"),
            # Keep connections NON-persistent. The RDS instance has a small
            # connection ceiling (max_connections=79); persistent connections
            # (CONN_MAX_AGE > 0) would pin a slot per worker thread and make the
            # exhaustion worse, not better. Connections are opened per request
            # and closed at request end.
            "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "0")),
            "OPTIONS": {
                "sslmode": "require",
                # Cap how long the app waits for a DB connection so a saturated
                # pool fails fast instead of piling up slow requests.
                "connect_timeout": int(os.environ.get("DB_CONNECT_TIMEOUT", "10")),
            },
        }
    }
    # else {
    #     "default": {
    #         "ENGINE": os.environ.get("DB_ENGINE"),
    #         "NAME": os.environ.get("DB_NAME"),
    #         "USER": os.environ.get("DB_USER"),
    #         "PASSWORD": os.environ.get("DB_PASSWORD"),
    #         "HOST": os.environ.get("DB_HOST"),
    #         "PORT": os.environ.get("DB_PORT"),
    #     }
    # }
)

# Opt-in: build the test schema directly from the current models instead of
# replaying the historical migrations. Useful because some legacy migrations
# emit backend-specific SQL that does not apply on the sqlite test database.
# Enable with DISABLE_MIGRATIONS=1 (typically only when running tests).
if os.environ.get("DISABLE_MIGRATIONS"):

    class _DisableMigrations:
        def __contains__(self, item):
            return True

        def __getitem__(self, item):
            return None

    MIGRATION_MODULES = _DisableMigrations()

# Settings for DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    # Turns Django's ProtectedError into a 409 instead of an unhandled 500.
    "EXCEPTION_HANDLER": "common.django_rest.exception_handler.exception_handler",
    # "DEFAULT_THROTTLE_CLASSES": [
    #     "rest_framework.throttling.AnonRateThrottle",
    #     "rest_framework.throttling.UserRateThrottle",
    # ],
    "DEFAULT_THROTTLE_RATES": {"anon": "60/minute", "user": "120/minute"},
    "DEFAULT_PAGINATION_CLASS": "common.django_rest.helpers.custome_pagination.CustomPageNumberPagination",
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "PAGE_SIZE": 10,
}

SPECTACULAR_SETTINGS = {
    "SCHEMA_PATH_PREFIX": r"/api/v[0-9]",
}

# Settings for JWT
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=7),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
}

# This settings now for development
CORS_ALLOWED_ORIGINS = [
    "https://localhost:3000",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:*",
    "https://balanzifyapi.jumatechs.xyz",
    "http://balanzifyapi.jumatechs.xyz",
    "https://balanzify.com",
    "https://4xf0rlft-8000.asse.devtunnels.ms",
    "https://balanzifyapi.jumatechs.xyz",
]
CORS_ALLOW_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "contenttype"]
CSRF_TRUSTED_ORIGINS = [
    "https://localhost:3000",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:*",
    "https://balanzifyapi.jumatechs.xyz",
    "http://balanzifyapi.jumatechs.xyz",
    "https://balanzify.com",
    "https://4xf0rlft-8000.asse.devtunnels.ms",
    "https://balanzifyapi.jumatechs.xyz",
]
ACCESS_CONTROL_ALLOW_ORIGIN = ["*"]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = True

X_FRAME_OPTIONS = "ALLOWALL"

# Password validation
# https://docs.djangoproject.com/en/4.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.1/topics/i18n/

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.1/howto/static-files/

# SSL Security settings - commented out for local development (avoid HTTPS redirect/timeouts)
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
USE_X_FORWARDED_HOST = True

# Default primary key field type
# https://docs.djangoproject.com/en/4.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Google OAuth2 settings
BASE_BACKEND_URL = os.environ.get("DJANGO_BASE_BACKEND_URL")
BASE_FRONTEND_URL = os.environ.get("DJANGO_BASE_FRONTEND_URL")
GOOGLE_OAUTH2_CLIENT_ID = os.environ.get("GOOGLE_OAUTH2_CLIENT_ID")
GOOGLE_OAUTH2_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH2_CLIENT_SECRET")
GOOGLE_OAUTH2_PROJECT_ID = os.environ.get("GOOGLE_OAUTH2_PROJECT_ID")

# Sending email settings
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST")
EMAIL_PORT = os.environ.get("EMAIL_PORT")
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER")
DEFAULT_HOST_USER = "no-reply@balanzify.com"
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS")

# TOTP / 2FA
OTP_TOTP_ISSUER = "Balanzify"

# Remove warning for urls check
SILENCED_SYSTEM_CHECKS = ["urls.W002", "security.W019"]

# Caching
# Default to a fast in-process cache (works without extra infra). Redis is
# already available in this stack (channels/celery), so production can swap the
# default backend to "django.core.cache.backends.redis.RedisCache" without any
# code changes — the dashboard only relies on the standard cache API.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "balanzify-default",
    }
}

# Short TTL (seconds) for v2 dashboard card responses. Cards are read-heavy and
# tolerate brief staleness; this absorbs rapid refreshes and the burst of ~26
# parallel card requests that make up a single dashboard load.
DASHBOARD_CARD_CACHE_TTL = int(os.environ.get("DASHBOARD_CARD_CACHE_TTL", 30))

# CHANNEL_LAYERS = {
#     "default": {
#         "BACKEND": "channels_redis.core.RedisChannelLayer",
#         "CONFIG": {
#             "hosts": [
#                 os.environ.get("redis_local_server", "redis://127.0.0.1:6379/1")
#             ],
#         },
#     },
# }
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [("redis", 6379)],
        },
    },
}
ASGI_APPLICATION = "master.asgi.application"

# Celery settings
CELERY_BROKER_URL = os.environ.get("redis_local_server")
CELERY_ACCEPT_CONTENT = ["application/json"]
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_SERIALIZER = "json"
CELERY_TIMEZONE = "Asia/Dhaka"
CELERY_RESULT_BACKEND = "django-db"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# Recurring transactions fire once a day. The templates carry a DATE, not a
# time, so a single daily pass is all the schedule needs -- and the job's own
# bounded catch-up means a missed run (deploy, outage) is picked up on the next
# one rather than lost. 02:00 Asia/Dhaka keeps generation away from the working
# day. Times are local because CELERY_TIMEZONE is set above.
CELERY_BEAT_SCHEDULE = {
    "run-recurring-templates": {
        "task": "recurringio.tasks.run_recurring_templates",
        "schedule": crontab(hour=2, minute=0),
    },
}


# moov settings sandbox
# MOOV_USERNAME = "IP5DSHyRhYzc64FT"  # 8PH_vXFoUdTXZGOH public key from moov
# MOOV_PASSWORD = "mFLY0YaTdxoJ7CA-fPWE5VzN108uFO6y"  # 4nZ0whIePNY45a8_NcjtJS4h9h_jYzn_  secret key from moov
# MOOV_ACCOUNT_UID = "36d656f4-adba-4160-be10-aabe853f3244"  # moov account uid for balanzify 8b55272b-6f2d-4ebd-a3ae-bf231567ceba // main account uid 2166eb98-c70d-4162-a168-e1940f11f903
# Frontend origin registered with Moov — used as the Origin header on server-to-server
# calls so Cloudflare does not block them. Must match the origin embedded in Moov tokens.
MOOV_ORIGIN = os.environ.get("MOOV_ORIGIN", "https://accounting.balanzify.com")


# moov settings production development
# SECURITY: these are Moov facilitator API credentials. They were previously
# hardcoded here (and the same pair was shipped in the frontend bundle), so they
# are compromised — ROTATE them in the Moov dashboard and set the new values via
# env (MOOV_USERNAME / MOOV_PASSWORD). The literals below are only a transition
# fallback; remove them once env is populated.
MOOV_USERNAME = os.environ.get("MOOV_USERNAME", "8PH_vXFoUdTXZGOH")
MOOV_PASSWORD = os.environ.get("MOOV_PASSWORD", "4nZ0whIePNY45a8_NcjtJS4h9h_jYzn_")
MOOV_ACCOUNT_UID = os.environ.get(
    "MOOV_ACCOUNT_UID", "2166eb98-c70d-4162-a168-e1940f11f903"
)
# Signing secret for the Moov webhook (from the Moov dashboard). The webhook
# receiver fails closed when this is unset, so set it in the environment.
MOOV_WEBHOOK_SECRET = os.environ.get("MOOV_WEBHOOK_SECRET", "")

# taxbandits settings
TAXBANDITS_CLIENT_ID = os.environ.get("TAXBANDITS_CLIENT_ID", "")
TAXBANDITS_CLIENT_SECRET = os.environ.get("TAXBANDITS_CLIENT_SECRET", "")
TAXBANDITS_USER_TOKEN = os.environ.get("TAXBANDITS_USER_TOKEN", "")
TAXBANDITS_OAUTH_URL = "https://testoauth.expressauth.net/v2/tbsauth"
TAXBANDITS_API_URL = "https://testapi.taxbandits.com"
TAXBANDITS_DOMAIN_REFERENCE_ID = (
    "1C122A13-BF70-4B22-891C-DF840A9CD4DB"  # Add your Domain Reference Id here
)
TAXBANDITS_ALLOWED_IPS = "34.194.128.121"
TAXBANDITS_TRUST_XFF = True
TAXBANDITS_MAX_SKEW_SECONDS = 600
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")


# Stripe settings
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")


# Local paths still needed for collectstatic and local file handling
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
MEDIA_ROOT = BASE_DIR / "media"

# AWS S3 settings
AWS_STORAGE_BUCKET_NAME = "balanzify-s3-511590151275-us-east-2-an"
AWS_S3_REGION_NAME = "us-east-2"
AWS_S3_CUSTOM_DOMAIN = (
    f"{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com"
)
STATIC_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/static/"
MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/media/"

STORAGES = {
    "default": {
        "BACKEND": "master.storages.MediaStorage",
    },
    "staticfiles": {
        "BACKEND": "master.storages.StaticStorage",
    },
}


AWS_ACCESS_KEY_ID = None
AWS_SECRET_ACCESS_KEY = None

AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = False
AWS_S3_FILE_OVERWRITE = False
AWS_S3_SIGNATURE_VERSION = "s3v4"
# Logging configuration
LOG_DIR = "/var/log/balanzify"
if not os.access(LOG_DIR, os.W_OK):
    LOG_DIR = os.path.join(BASE_DIR, "logs")
CELERY_LOG_DIR = os.path.join(LOG_DIR, "celery")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CELERY_LOG_DIR, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s [%(name)s] %(message)s",
        },
        "simple": {
            "format": "%(levelname)s [%(name)s] %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "app_out": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "out.log"),
            "maxBytes": 50 * 1024 * 1024,  # 50 MB
            "backupCount": 5,
            "formatter": "verbose",
        },
        "app_error": {
            "level": "ERROR",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "error.log"),
            "maxBytes": 50 * 1024 * 1024,  # 50 MB
            "backupCount": 5,
            "formatter": "verbose",
        },
        "celery_out": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(CELERY_LOG_DIR, "out.log"),
            "maxBytes": 50 * 1024 * 1024,  # 50 MB
            "backupCount": 5,
            "formatter": "verbose",
        },
        "celery_error": {
            "level": "ERROR",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(CELERY_LOG_DIR, "error.log"),
            "maxBytes": 50 * 1024 * 1024,  # 50 MB
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console", "app_out", "app_error"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
        },
        "weapi": {
            "handlers": ["console", "app_out", "app_error"],
            "level": "INFO",
            "propagate": False,
        },
        "moovmoneyio": {
            "handlers": ["console", "app_out", "app_error"],
            "level": "INFO",
            "propagate": False,
        },
        # Recurring generation runs unattended from celery beat, so its output
        # is the only account of what it did. Without an entry here its records
        # propagated to a root logger with no handlers and were discarded --
        # which is how a nightly firing wrote an unbalanced journal entry for
        # weeks without leaving a line anywhere.
        "recurringio": {
            "handlers": ["console", "app_out", "app_error"],
            "level": "INFO",
            "propagate": False,
        },
        # Carries the write-time balance check every posting path funnels
        # through. Same reasoning as above: without an entry the ERROR goes
        # nowhere, and an unbalanced entry is exactly the thing that must not be
        # possible to write silently.
        "journalio": {
            "handlers": ["console", "app_out", "app_error"],
            "level": "INFO",
            "propagate": False,
        },
        "celery": {
            "handlers": ["console", "celery_out", "celery_error"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
