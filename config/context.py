from . import settings
from . import settings_local


def env(request):
    return {
        "env": settings.ENV,
    }


def site_handle(request):
    return {
        "site_handle": settings_local.SITE_NAME,
    }
