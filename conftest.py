import pytest


@pytest.fixture(autouse=True)
def use_local_storage(settings, tmp_path):
    """Use local file system storage for tests instead of S3."""
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
