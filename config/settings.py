import ast
import os
from pathlib import Path

# noinspection PyPackageRequirements
import environ
from django.forms.renderers import TemplatesSetting

from utils.prepare_path import prepare_path


def parse_admins(value):
    try:
        return ast.literal_eval(value)
    except ValueError:
        return []


env = environ.Env(DEBUG=(bool, False), ADMINS=(parse_admins, []))

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

environ.Env.read_env(os.path.join(BASE_DIR, "config/.env"))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/3.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env("SECRET_KEY")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env("DEBUG")

# NOTE: Allows for insecure transport of OAuth tokens when running locally in DEBUG mode
if DEBUG:
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# check dev v. production environment
ENV = env("ENV")

# urls to which the application will respond
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

# trusted origins for CSRF (needed when behind nginx proxy)
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "mathfilters",
    # "crispy_forms",
    # "crispy_bootstrap5",
    "django.forms",
    "apps.accounts",
    "apps.activity",
    "apps.agenda",
    "apps.contacts",
    "apps.case",
    "apps.folders",
    "apps.intakes",
    "apps.lab",
    "apps.matters",
    "apps.search",
    "apps.settings",
    "apps.trust",
    "apps.invoicing",
    "apps.reports",
    "apps.management",
    "apps.notes",
    "django_filters",
    "django_cleanup.apps.CleanupConfig",
    "django_q",
    "watson",
    "simple_history",
]

# Django-Q2 Configuration
Q_CLUSTER = {
    "name": "law_admin",
    "workers": 2,
    "recycle": 500,
    "timeout": 600,  # 10 minutes for OCR tasks
    "retry": 900,
    "queue_limit": 50,
    "bulk": 10,
    "orm": "default",
    "catch_up": False,
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.common.BrokenLinkEmailsMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.agenda.middleware.DailyDashCheckMiddleware",
    "utils.middleware.CurrentUserMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
]

ROOT_URLCONF = "config.urls"

default_loaders = [
    "django.template.loaders.filesystem.Loader",
    "django.template.loaders.app_directories.Loader",
]

cached_loaders = [("django.template.loaders.cached.Loader", default_loaders)]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [str(BASE_DIR.joinpath("templates"))],
        # 'APP_DIRS': True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context.env",
                "config.context.site_handle",
            ],
            "loaders": default_loaders if DEBUG else cached_loaders,
            "libraries": {
                "phone_number": "apps.management.templatetags.phone_numbers",
                "cache_buster": "apps.management.templatetags.cache_buster",
            },
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database
# https://docs.djangoproject.com/en/3.2/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql_psycopg2",
        "NAME": env("DB_NAME"),
        "USER": env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": "localhost",
    }
}

STORAGES = {
    "default": {
        # S3 Storage for Digital Ocean Spaces
        "BACKEND": "storages.backends.s3.S3Storage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Digital Ocean Spaces Settings
AWS_S3_REGION_NAME = env("DIGITAL_OCEAN_REGION_NAME")
AWS_S3_ENDPOINT_URL = env("DIGITAL_OCEAN_ENDPOINT_URL")
AWS_STORAGE_BUCKET_NAME = env("DIGITAL_OCEAN_BUCKET_NAME")
AWS_S3_ACCESS_KEY_ID = env("DIGITAL_OCEAN_ACCESS_KEY_ID")
AWS_S3_SECRET_ACCESS_KEY = env("DIGITAL_OCEAN_SECRET_ACCESS_KEY")

# Password validation
# https://docs.djangoproject.com/en/3.2/ref/settings/#auth-password-validators

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
# https://docs.djangoproject.com/en/3.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "America/New_York"

USE_I18N = True

USE_TZ = True

STATIC_URL = "static/"
MEDIA_URL = "media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

if DEBUG is False:
    STATIC_ROOT = os.path.join(BASE_DIR, "static")
else:
    STATICFILES_DIRS = [
        os.path.join(BASE_DIR, "static"),
    ]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.CustomUser"

LOGIN_REDIRECT_URL = "agenda:tasks-index"
LOGOUT_REDIRECT_URL = "agenda:tasks-index"

INTERNAL_IPS = [
    "127.0.0.1",
]

X_FRAME_OPTIONS = "SAMEORIGIN"

# Email
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST")
EMAIL_USE_TLS = True
EMAIL_PORT = 587
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
SERVER_EMAIL = env("SERVER_EMAIL")
DEFAULT_FROM_EMAIL = env("SERVER_EMAIL")
ADMINS = env("ADMINS")

# set cookies (sessions) to last for two months
# default is two weeks, multiplying by four to get two months
SESSION_COOKIE_AGE = 1209600 * 4

SESSION_SAVE_EVERY_REQUEST = True

prepare_path(f"{BASE_DIR}/logs/debug.log")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "timestamped": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
        "simple": {
            "format": "[{levelname}] {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "file": {
            "level": "DEBUG",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs/debug.log",
            "maxBytes": 5 * 1024 * 1024,  # 5 MB
            "backupCount": 3,  # Keep 3 old files
            "formatter": "timestamped",
        },
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "loggers": {
        "": {
            "level": "DEBUG",
            "handlers": ["file"],
            "propagate": True,
        },
    },
}


# CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
# CRISPY_TEMPLATE_PACK = "bootstrap5"


class CustomFormRendererSpacious(TemplatesSetting):
    form_template_name = "components/form-fields-template-spacious.html"
    label_suffix = ""


class CustomFormRendererCompact(TemplatesSetting):
    form_template_name = "components/form-fields-template-compact.html"
    label_suffix = ""


FORM_RENDERER = "config.settings.CustomFormRendererSpacious"
FORM_SETTINGS = {"label_suffix": ""}

# Anthropic API Configuration
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")

# Google Gemini API Configuration
GEMINI_API_KEY = env("GEMINI_API_KEY", default="")

# CourtListener API Configuration (for citation verification)
COURTLISTENER_API_TOKEN = env("COURTLISTENER_API_KEY", default="")
