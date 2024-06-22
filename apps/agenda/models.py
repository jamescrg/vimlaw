from django.db import models
from apps.folders.models import Folder
from accounts.models import CustomUser
from apps.matters.models import Matter


class Task(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True)
    folder = models.ForeignKey(Folder, on_delete=models.SET_NULL, null=True)
    description = models.CharField(max_length=200, null=True)
    date_due = models.DateField(blank=True, null=True)
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, blank=True, null=True)
    status = models.CharField(max_length=50, null=True)
    priority = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.description} : {self.id}"

    class Meta:
        db_table = "app_task"
