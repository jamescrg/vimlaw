from django.db import models

from utils.models import AuditMixin


class Company(AuditMixin):
    PAYMENT_FONT_CHOICES = [
        ("serif", "Serif (Noto Serif)"),
        ("sans", "Sans-serif (Noto Sans)"),
    ]
    PAYMENT_BACKGROUND_CHOICES = [
        ("gray", "Gray"),
        ("blue", "Blue"),
    ]

    name = models.CharField(max_length=255)
    address_line_1 = models.CharField(max_length=255, blank=True)
    address_line_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    invoice_bcc = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Comma-separated addresses BCC'd on every invoice email.",
    )
    logo = models.ImageField(upload_to="company/", blank=True, null=True)
    jurisdiction = models.CharField(max_length=100, blank=True)
    # Branding for the client-facing payment page + payment emails. Kept in data
    # (not hardcoded) so each firm running this open-source app picks its own look.
    payment_font = models.CharField(
        max_length=10, choices=PAYMENT_FONT_CHOICES, default="serif"
    )
    payment_background = models.CharField(
        max_length=10, choices=PAYMENT_BACKGROUND_CHOICES, default="gray"
    )

    class Meta:
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name
