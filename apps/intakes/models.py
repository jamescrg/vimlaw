from django.db import models

from apps.accounts.models import CustomUser


class Intake(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=100)
    date = models.DateField(null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    email = models.CharField(max_length=100, blank=True, null=True)
    practice_area = models.CharField(max_length=50, null=True)
    source = models.CharField(max_length=50, null=True)
    status = models.CharField(max_length=50, default="Open")

    def __str__(self):
        return f"{self.name} : {self.id}"

    class Meta:
        db_table = "app_intake"


class Note(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True)
    intake = models.ForeignKey(Intake, on_delete=models.SET_NULL, null=True)
    date = models.DateField(null=True)
    time = models.TimeField(auto_now=False, auto_now_add=False, null=True, blank=True)
    type = models.CharField(max_length=50, blank=True, null=True)
    details = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.type} : {self.id}"

    class Meta:
        db_table = "app_intake_note"
