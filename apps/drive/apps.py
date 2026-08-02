from django.apps import AppConfig


class DriveConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.drive"

    def ready(self):
        import apps.drive.signals  # noqa: F401
