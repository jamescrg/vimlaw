from django.db import models

from apps.matters.models import Matter


class Proceeding(models.Model):
    user = models.ForeignKey(
        "accounts.CustomUser", on_delete=models.SET_NULL, null=True, blank=True
    )
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    date_filed = models.DateField(null=True)
    forum = models.CharField(max_length=150, null=True)
    case_number = models.CharField(max_length=50, null=True)
    nickname = models.CharField(max_length=50, blank=True, null=True)
    status = models.CharField(max_length=50, null=True)
    primary = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.case_number}"

    @property
    def display_name(self):
        """Return nickname if set, otherwise forum."""
        return self.nickname if self.nickname else self.forum

    class Meta:
        db_table = "app_proceeding"

    def save(self, *args, **kwargs):
        # If this is the primary proceeding, set all other proceedings to not primary
        if self.primary:
            Proceeding.objects.filter(matter=self.matter).exclude(pk=self.pk).update(
                primary=False
            )

        super().save(*args, **kwargs)
