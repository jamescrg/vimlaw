from django.db import models

from utils.models import AuditMixin


class Company(AuditMixin):
    name = models.CharField(max_length=255)
    address_line_1 = models.CharField(max_length=255, blank=True)
    address_line_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    logo = models.ImageField(upload_to="company/", blank=True, null=True)

    class Meta:
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name
