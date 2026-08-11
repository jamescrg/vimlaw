import ast
import os
from pathlib import Path

# noinspection PyPackageRequirements
import environ
from django.core.exceptions import ImproperlyConfigured
from django.forms.renderers import TemplatesSetting


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
    "apps.calendar",
    "apps.checklists",
    "apps.tasks",
    "apps.dash",
    "apps.contacts",
    "apps.case",
    "apps.folders",
    "apps.intakes",
    "apps.matters",
    "apps.search",
    "apps.settings",
    "apps.trust",
    "apps.invoicing",
    "apps.reports",
    "apps.management",
    "apps.notes",
    "apps.drive",
    "apps.drafts",
    "apps.mail",
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
    "apps.dash.middleware.DailyDashCheckMiddleware",
    "utils.middleware.CurrentUserMiddleware",
    "apps.accounts.middleware.HtmxLoginRedirectMiddleware",
    "apps.accounts.middleware.PermissionMiddleware",
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
        "HOST": env("DB_HOST", default="localhost"),
        "PORT": env("DB_PORT", default="5432"),
    }
}

# Cache. Same LocMemCache Django defaults to, but with the entry cap
# raised: the default 300-entry cap culls a random third of the cache on
# every write once full, and this cache holds AI chat status/completion
# payloads (ai_status_*), CourtListener opinion payloads and rate-limit
# counters. Under the default cap a mid-run cull could evict a research
# run's live status (the trail flashing back to "Checking...") or, worse,
# a finished run's completion payload before the browser polled it.
# Per-process is fine here: gunicorn runs a single worker and AI requests
# run on threads inside it.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "OPTIONS": {"MAX_ENTRIES": 10_000},
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
MEDIA_ROOT = BASE_DIR / "media"

# User-uploaded media can live on the local filesystem or in an S3-compatible
# object store such as DigitalOcean Spaces. Local is deliberately the default
# so a checkout can run without cloud credentials. Production never exposes
# MEDIA_ROOT through Django's public URL configuration; protected download
# views continue to stream confidential files through Django's storage API.
STORAGE_BACKEND = env("STORAGE_BACKEND", default="local").strip().lower()
if STORAGE_BACKEND not in {"local", "s3"}:
    raise ImproperlyConfigured("STORAGE_BACKEND must be either 'local' or 's3'.")

STORAGES = {
    "default": {
        "BACKEND": (
            "django.core.files.storage.FileSystemStorage"
            if STORAGE_BACKEND == "local"
            else "storages.backends.s3.S3Storage"
        ),
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

if STORAGE_BACKEND == "s3":
    AWS_S3_REGION_NAME = env("DIGITAL_OCEAN_REGION_NAME")
    AWS_S3_ENDPOINT_URL = env("DIGITAL_OCEAN_ENDPOINT_URL")
    AWS_STORAGE_BUCKET_NAME = env("DIGITAL_OCEAN_BUCKET_NAME")
    AWS_S3_ACCESS_KEY_ID = env("DIGITAL_OCEAN_ACCESS_KEY_ID")
    AWS_S3_SECRET_ACCESS_KEY = env("DIGITAL_OCEAN_SECRET_ACCESS_KEY")
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = True

if DEBUG is False:
    STATIC_ROOT = os.path.join(BASE_DIR, "static")
else:
    STATICFILES_DIRS = [
        os.path.join(BASE_DIR, "static"),
    ]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.CustomUser"

LOGIN_REDIRECT_URL = "tasks:index"
LOGOUT_REDIRECT_URL = "tasks:index"

INTERNAL_IPS = [
    "127.0.0.1",
]

X_FRAME_OPTIONS = "SAMEORIGIN"

EMAIL_BACKEND_MODE = env(
    "EMAIL_BACKEND", default="console" if DEBUG else "smtp"
).strip()

_EMAIL_BACKENDS = {
    "console": "django.core.mail.backends.console.EmailBackend",
    "locmem": "django.core.mail.backends.locmem.EmailBackend",
    "smtp": "django.core.mail.backends.smtp.EmailBackend",
}

if EMAIL_BACKEND_MODE not in _EMAIL_BACKENDS:
    raise ImproperlyConfigured("EMAIL_BACKEND must be one of: console, locmem, smtp.")

EMAIL_BACKEND = _EMAIL_BACKENDS[EMAIL_BACKEND_MODE]
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
# Fail a dead SMTP connection in seconds. Without this, a blocked port hangs
# the request until gunicorn SIGKILLs the worker (bare "Internal Server
# Error") - synchronous sends like the login verification code must surface
# a real error page instead.
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
SERVER_EMAIL = env("SERVER_EMAIL", default="webmaster@localhost")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default=SERVER_EMAIL)
# From address for client-facing billing email (invoice transmissions and
# payment requests). Falls back to DEFAULT_FROM_EMAIL when unset.
BILLING_FROM_EMAIL = env("BILLING_FROM_EMAIL", default=DEFAULT_FROM_EMAIL)
ADMINS = env("ADMINS")
# Address(es) BCC'd on every invoice email the app sends, so the firm retains a
# faithful copy (cover message + attached PDF) of what each client received.
# Comma-separated; leave empty to disable.
# Note: invoice-email config — Reply-To, the contact address shown in the body,
# and the BCC list — all come from the Company settings record
# (apps.settings.Company), so the firm manages them in the UI in one place.

# set cookies (sessions) to last for two months
# default is two weeks, multiplying by four to get two months
SESSION_COOKIE_AGE = 1209600 * 4

SESSION_SAVE_EVERY_REQUEST = True

# On dev, keep sessions off the database. The nightly prod-snapshot import drops
# and recreates the DB, which would wipe the default db-backed django_session
# table and log us out on every device. Storing sessions as files on disk keeps
# them across the refresh (the user row is reimported unchanged, so the session
# auth hash still validates). Gated on ENV, which is stable — unlike DEBUG,
# which we sometimes toggle for testing.
if ENV == "dev":
    SESSION_ENGINE = "django.contrib.sessions.backends.file"
    SESSION_FILE_PATH = os.path.join(BASE_DIR, ".dev-sessions")
    os.makedirs(SESSION_FILE_PATH, exist_ok=True)

# Logging — standardized across all apps; logs live in <app>/logs/
(BASE_DIR / "logs").mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} [{levelname}] {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "file": {
            "class": "logging.FileHandler",
            "filename": BASE_DIR / "logs" / "django.log",
            "formatter": "verbose",
        },
        "null": {"class": "logging.NullHandler"},
    },
    "root": {"handlers": ["console", "file"], "level": "WARNING"},
    "loggers": {
        # Bot-driven bad Host headers are benign; drop them instead of dumping a
        # full traceback per hit (this was chf's 117 MB error-log flood).
        "django.security.DisallowedHost": {"handlers": ["null"], "propagate": False},
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

# Shared secret protecting the cl <-> Kosmos intake seam. Empty means
# auth is not enforced, so a one-sided deploy can't brick the seam;
# enforcement begins once both apps' envs carry the same key.
KOSMOS_SEAM_KEY = env("KOSMOS_SEAM_KEY", default="")

# Mailgun inbound-route webhook (intake-from-email). Empty means signature
# verification is not enforced, so the webhook can be deployed before the
# key is configured; enforcement begins once the key is set.
MAILGUN_WEBHOOK_SIGNING_KEY = env("MAILGUN_WEBHOOK_SIGNING_KEY", default="")
# Local part of the intake address this instance owns. The shared Mailgun
# route posts every message to prod AND dev; prod processes kosmos-intakes@,
# dev processes kosmos-dev-intakes@, each dropping the other's mail. This is what makes
# permanent integration testing against dev possible on a 1-route quota.
INTAKE_INBOUND_RECIPIENT = env(
    "INTAKE_INBOUND_RECIPIENT", default="kosmos-intakes"
).lower()

# Anthropic API Configuration
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")

# Google Gemini API Configuration
GEMINI_API_KEY = env("GEMINI_API_KEY", default="")

# Shared Google integration configuration. Keeping credentials beneath one
# configurable directory makes host, container, and secret-volume layouts use
# the same code paths.
_google_data_dir = Path(
    env("GOOGLE_DATA_DIR", default=str(BASE_DIR / "google"))
).expanduser()
GOOGLE_DATA_DIR = (
    _google_data_dir if _google_data_dir.is_absolute() else BASE_DIR / _google_data_dir
)
GOOGLE_CLIENT_SECRET_PATH = GOOGLE_DATA_DIR / "google_tokens.json"
GOOGLE_CONTACTS_TOKEN_PATH = GOOGLE_DATA_DIR / "contact_tokens.json"
GOOGLE_CALENDAR_TOKEN_PATH = GOOGLE_DATA_DIR / "calendar_tokens.json"
GOOGLE_DRIVE_TOKEN_PATH = GOOGLE_DATA_DIR / "drive_tokens.json"
GOOGLE_EMAIL_TOKEN_PATH = GOOGLE_DATA_DIR / "email_tokens.json"
CALENDAR_ID = env("CALENDAR_ID", default="")
LAW_FIRM_ID = env("LAW_FIRM_ID", default="")

# CourtListener API Configuration (for citation verification)
COURTLISTENER_API_TOKEN = env("COURTLISTENER_API_KEY", default="")

# Google Drive case-notes sync
# Root Drive folder whose <matter>/Notes/** files are synced into Note records.
DRIVE_NOTES_ROOT = env("DRIVE_NOTES_ROOT", default="Matters - Open")
# Optional: set if "Matters - Open" lives in a Shared Drive rather than My Drive.
DRIVE_SHARED_DRIVE_ID = env("DRIVE_SHARED_DRIVE_ID", default="")
# Any folder with this name inside a matter's Drive folder is a curated
# ingestion point: its PDFs sync in as Evidence documents (drag a file in to
# add it to the app). Convention-based; no per-matter linking. Blank disables.
DRIVE_KEY_DOCUMENTS_FOLDER = env("DRIVE_KEY_DOCUMENTS_FOLDER", default="Key Documents")

# Headless LibreOffice, used to apply AI-proposed edits to ODT drafts as
# tracked changes (apps/drive/redline.py). UNO_PYTHON must be an interpreter
# with UNO bindings — the system python3 with the python3-uno package, not the
# project venv (apt-get install libreoffice-writer-nogui python3-uno).
SOFFICE_BIN = env("SOFFICE_BIN", default="soffice")
UNO_PYTHON = env("UNO_PYTHON", default="/usr/bin/python3")

# Gmail case-email sync
# Parent label whose children are offered in the label-to-matter picker (shown
# without the prefix). Blank offers every user label in the mailbox.
GMAIL_LABEL_ROOT = env("GMAIL_LABEL_ROOT", default="Matters - Open")

# Online invoice payment collection (Phase 2)
# Active processor; "fake" simulates the full card+ACH lifecycle so dev/CI run
# without credentials. Switch to "lawpay" once sandbox keys are configured.
PAYMENT_PROCESSOR = env("PAYMENT_PROCESSOR", default="fake")
# LawPay/AffiniPay (8am) credentials. Public key -> client-side hosted fields;
# secret key -> server-side Basic auth; operating account_id pins funds to the
# operating (non-trust) account. Test-mode keys hit only sandbox accounts.
LAWPAY_PUBLIC_KEY = env("LAWPAY_PUBLIC_KEY", default="")
LAWPAY_SECRET_KEY = env("LAWPAY_SECRET_KEY", default="")
# Deposit accounts per (destination, method) — AffiniPay keeps card and eCheck
# in separate accounts, each with an operating/trust pair. Discover the ids with
# `manage.py lawpay_accounts`. Blank → the gateway auto-selects the primary.
LAWPAY_OPERATING_CARD_ACCOUNT_ID = env("LAWPAY_OPERATING_CARD_ACCOUNT_ID", default="")
LAWPAY_OPERATING_ECHECK_ACCOUNT_ID = env(
    "LAWPAY_OPERATING_ECHECK_ACCOUNT_ID", default=""
)
LAWPAY_TRUST_CARD_ACCOUNT_ID = env("LAWPAY_TRUST_CARD_ACCOUNT_ID", default="")
LAWPAY_TRUST_ECHECK_ACCOUNT_ID = env("LAWPAY_TRUST_ECHECK_ACCOUNT_ID", default="")
LAWPAY_API_BASE = env("LAWPAY_API_BASE", default="https://api.8am.com")
# Stripe credentials (direct, single-account: the self-hosting firm owns the
# Stripe account and provides its own keys). Publishable key -> client-side
# Stripe Elements; secret key -> server-side API; webhook secret -> signature
# verification. Use test-mode keys in the sandbox.
STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")
# Confido Legal (Gravity Legal) credentials. GraphQL API, authed with the firm
# secret token via the `x-api-key` header. BOTH bank-account ids are required —
# Confido has no auto-default, so a charge must name the operating (invoices) or
# trust (deposits) account; discover the ids with the `bankAccountsList` query or
# the portal. Webhooks are HMAC-SHA512 signed. Use the sandbox endpoint + js host
# with a sandbox key; switch both to `api.gravity-legal.com` / `js.gravity-legal.com`
# with a live key.
CONFIDO_API_KEY = env("CONFIDO_API_KEY", default="")
CONFIDO_API_BASE = env(
    "CONFIDO_API_BASE", default="https://api.sandbox.gravity-legal.com/v2"
)
CONFIDO_WEBHOOK_SECRET = env("CONFIDO_WEBHOOK_SECRET", default="")
CONFIDO_OPERATING_BANK_ACCOUNT_ID = env("CONFIDO_OPERATING_BANK_ACCOUNT_ID", default="")
CONFIDO_TRUST_BANK_ACCOUNT_ID = env("CONFIDO_TRUST_BANK_ACCOUNT_ID", default="")
CONFIDO_HOSTED_FIELDS_URL = env(
    "CONFIDO_HOSTED_FIELDS_URL",
    default="https://js.sandbox.gravity-legal.com/hosted-fields.js",
)
# How long a tokenized public payment link stays valid (seconds). Default 90
# days; staff can resend an invoice to mint a fresh link.
INVOICE_PAY_LINK_MAX_AGE = env.int(
    "INVOICE_PAY_LINK_MAX_AGE", default=60 * 60 * 24 * 90
)
# How long a tokenized client intake-form link stays valid (seconds). Shorter
# than the pay link — a prospective client should answer promptly, and staff
# can resend the form to mint a fresh token against the same submission.
INTAKE_FORM_LINK_MAX_AGE = env.int(
    "INTAKE_FORM_LINK_MAX_AGE", default=60 * 60 * 24 * 30
)
# Absolute base URL (scheme + host) for links built outside a request context,
# e.g. payment links in emails sent via async_task. Blank → fall back to the
# sending request's host when available.
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="")
