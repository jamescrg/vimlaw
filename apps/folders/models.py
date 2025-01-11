from django.db import models

CLIENT_FOLDERS = [
    {"id": "current", "name": "Current"},
    {"id": "former", "name": "Former"},
]


class Folder(models.Model):
    id = models.BigAutoField(primary_key=True)
    app = models.CharField(max_length=50, null=True)
    name = models.CharField(max_length=50, null=True)
    selected = models.IntegerField(blank=True, null=True)
    active = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return f"{self.name}"

    class Meta:
        db_table = "app_folder"
