from django.db import models

from utils.models import AuditMixin


class Firm(AuditMixin):
    name = models.CharField(max_length=255)
    address_line_1 = models.CharField(max_length=255, blank=True)
    address_line_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    billing_email = models.EmailField(blank=True)
    invoice_bcc = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Comma-separated addresses BCC'd on every invoice email.",
    )
    # Cc + Reply-To on template emails sent to intakes. Must be a human
    # inbox, not the Mailgun intake pipeline address - the pipeline would
    # log our own outbound copies as duplicate notes.
    intake_email = models.EmailField(blank=True)
    logo = models.ImageField(upload_to="company/", blank=True, null=True)
    jurisdiction = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name_plural = "firms"

    def __str__(self):
        return self.name
