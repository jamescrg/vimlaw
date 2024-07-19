from django.db import models

from apps.accounts.models import CustomUser


class Folder(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    page = models.CharField(max_length=50, null=True)
    name = models.CharField(max_length=50, null=True)
    selected = models.IntegerField(blank=True, null=True)
    active = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return f"{self.name}"

    class Meta:
        db_table = "app_folder"
