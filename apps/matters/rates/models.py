from django.db import models

from apps.accounts.models import CustomUser
from apps.matters.models import Matter


class Rate(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    matter_rate = models.IntegerField()

    def __str__(self):
        return f"{self.matter.name} - {self.user.username} - {self.matter_rate}"

    class Meta:
        db_table = "app_matter_rate"
