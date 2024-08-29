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

# check dev v. production environment
ENV = env("ENV")

# urls to which the application will respond
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

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
    "apps.events",
    "apps.folders",
    "apps.intakes",
    "apps.lab",
    "apps.matters",
    "apps.search",
    "apps.settings",
    "apps.trust",
    "apps.billing",
    "apps.management",
    "django_filters",
    "django_cleanup.apps.CleanupConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.common.BrokenLinkEmailsMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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

LOGIN_REDIRECT_URL = "agenda:tasks-list"
LOGOUT_REDIRECT_URL = "agenda:tasks-list"

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
ADMINS = env("ADMINS")

# set cookies (sessions) to last for two months
# default is two weeks, multiplying by four to get two months
SESSION_COOKIE_AGE = 1209600 * 4

SESSION_SAVE_EVERY_REQUEST = True

prepare_path(f"{BASE_DIR}/logs/debug.log")

LOGGING = {
    # The version number of our log
    "version": 1,
    # django uses some of its own loggers for internal operations.
    # In case you want to disable them just replace the False above with true.
    "disable_existing_loggers": False,
    "formatters": {
        "timestamped": {
            "format": "{asctime} {message}",
            "style": "{",
        },
    },
    # A handler for writing the messages to a file
    # A logger can have multiple handlers
    "handlers": {
        "file": {
            "level": "DEBUG",
            "class": "logging.FileHandler",
            "filename": BASE_DIR / "logs/debug.log",
            "formatter": "timestamped",
        },
    },
    "loggers": {
        # notice the blank ''
        # Usually you would put built in loggers like django or root here
        "": {
            "level": "DEBUG",
            "handlers": ["file"],  # notice how file variable is called ,
            "propagate": True,
        },
    },
}


# CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
# CRISPY_TEMPLATE_PACK = "bootstrap5"


class CustomFormRenderer(TemplatesSetting):
    form_template_name = "components/form-fields-template.html"


FORM_RENDERER = "config.settings.CustomFormRenderer"
