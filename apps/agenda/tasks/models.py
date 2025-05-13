from django.db import models

from apps.accounts.models import CustomUser
from apps.folders.models import Folder
from apps.matters.models import Matter


class Task(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True)
    folder = models.ForeignKey(Folder, on_delete=models.SET_NULL, null=True)
    description = models.CharField(max_length=200, null=True)
    date_due = models.DateField(blank=True, null=True)
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, blank=True, null=True)
    status = models.CharField(max_length=50, null=True)
    urgent = models.BooleanField(default=False)
    priority = models.IntegerField(default=5)

    def __str__(self):
        return f"{self.description} : {self.id}"

    class Meta:
        db_table = "app_task"

    @property
    def matter_display_name(self):
        if self.matter:
            full_name = self.matter.name
            short_name = self.matter.name[0:15]
            display_name = short_name
            if len(full_name) > len(short_name):
                display_name = short_name + " ..."
            return display_name
        else:
            return "Admin"
