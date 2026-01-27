from django.db import models


class FirmProfile(models.Model):
    """
    Singleton model for firm/company profile information.
    Used in PDF templates for invoices, statements, and reports.
    """

    name = models.CharField(max_length=100, help_text="Firm name (e.g., Craig Legal)")
    name_suffix = models.CharField(
        max_length=20, blank=True, help_text="Legal suffix (e.g., LLC, LLP, PC)"
    )
    address_line1 = models.CharField(max_length=100)
    address_line2 = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=50)
    state = models.CharField(max_length=2)
    zip_code = models.CharField(max_length=10)
    phone = models.CharField(max_length=20)
    email = models.EmailField()
    logo = models.ImageField(upload_to="firm/", blank=True, null=True)
    trust_caption = models.TextField(
        blank=True,
        help_text="Explanation text shown on invoices when trust balance is displayed",
    )

    class Meta:
        verbose_name = "Firm Profile"
        verbose_name_plural = "Firm Profile"

    def __str__(self):
        if self.name_suffix:
            return f"{self.name}, {self.name_suffix}"
        return self.name

    @property
    def full_name(self):
        """Returns firm name with suffix if present."""
        if self.name_suffix:
            return f"{self.name}, {self.name_suffix}"
        return self.name

    @property
    def full_address(self):
        """Returns formatted full address."""
        lines = [self.address_line1]
        if self.address_line2:
            lines.append(self.address_line2)
        lines.append(f"{self.city}, {self.state} {self.zip_code}")
        return "\n".join(lines)

    @classmethod
    def get_instance(cls):
        """
        Returns the singleton FirmProfile instance.
        Creates one with empty values if none exists.
        """
        instance, _ = cls.objects.get_or_create(pk=1)
        return instance

    def save(self, *args, **kwargs):
        """Enforce singleton by always using pk=1."""
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Prevent deletion of the singleton instance."""
        pass
