import pytest
from django.core.management import call_command


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Two pieces of schema come from commands, not migrations: the
    ai_status cache table (createcachetable) and watson's search_tsv
    column and trigger (installwatson), which the agent's search_materials
    queries directly."""
    with django_db_blocker.unblock():
        call_command("createcachetable")
        call_command("installwatson", verbosity=0)


@pytest.fixture(autouse=True)
def use_local_storage(settings, tmp_path):
    """Use local file system storage for tests instead of S3.

    MEDIA_ROOT is overridden as well: depending on how the storage handler
    rebuilds the default storage after the STORAGES override, the OPTIONS
    location can be dropped and FileSystemStorage falls back to MEDIA_ROOT —
    which leaked test files into the real media/ directory (found as
    media/drafts/<test-matter-ids> on dev, 2026-08-05).
    """
    settings.MEDIA_ROOT = str(tmp_path / "media")
    settings.STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {
                "location": str(tmp_path / "media"),
            },
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
