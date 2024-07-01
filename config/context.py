import os


def env(request):
    return {
        "env": os.environ.get("ENV"),
    }


def site_handle(request):
    return {
        "site_handle": os.environ.get("SITE_NAME"),
    }
