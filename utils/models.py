from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditMixin(models.Model):
    """
    Abstract mixin providing standard audit fields for tracking record
    creation and modification.

    Fields:
    - created_at: Timestamp when record was created
    - updated_at: Timestamp when record was last updated
    - created_by: User who created the record
    - updated_by: User who last updated the record

    User fields are automatically populated via CurrentUserMiddleware.
    """

    created_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
    )
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_updated",
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        from utils.middleware import get_current_user

        user = get_current_user()
        if user and hasattr(user, "is_authenticated") and user.is_authenticated:
            if not self.pk and not self.created_by_id:
                self.created_by = user
            self.updated_by = user

        super().save(*args, **kwargs)
