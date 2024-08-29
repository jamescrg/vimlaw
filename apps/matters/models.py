from django.db import models

from apps.contacts.models import Contact


class Matter(models.Model):
    user_id = models.IntegerField(null=True)
    name = models.CharField(max_length=50, null=True)
    description = models.CharField(max_length=255, null=True)
    status = models.CharField(max_length=50, null=True)
    date_start = models.DateField(null=True)
    date_end = models.DateField(blank=True, null=True)
    firm = models.CharField(max_length=50, null=True)
    clio_matter_id = models.CharField(max_length=500, null=True, blank=True)
    client_reference_id = models.CharField(max_length=50, blank=True, null=True)
    practice_area = models.CharField(max_length=50, null=True)
    contacts = models.ManyToManyField(Contact, through="Relationship")
    client = models.ForeignKey(
        Contact, related_name="client_matters", on_delete=models.SET_NULL, null=True
    )

    def __str__(self):
        return f"{self.name}"

    class Meta:
        db_table = "app_matter"
