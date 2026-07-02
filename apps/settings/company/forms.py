from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from apps.settings.models import Company

MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2MB
ALLOWED_LOGO_TYPES = ["image/png", "image/jpeg", "image/svg+xml"]


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = [
            "name",
            "address_line_1",
            "address_line_2",
            "city",
            "state",
            "zip_code",
            "phone",
            "email",
            "invoice_bcc",
            "logo",
        ]
        widgets = {
            "logo": forms.ClearableFileInput(attrs={"accept": ".png,.jpg,.jpeg,.svg"}),
        }
        labels = {
            "invoice_bcc": "Invoice BCC",
        }
        help_texts = {
            "logo": "PNG, JPG, or SVG. Max 2 MB.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        text_fields = [
            "name",
            "address_line_1",
            "address_line_2",
            "city",
            "state",
            "zip_code",
            "phone",
            "email",
            "invoice_bcc",
        ]
        for field_name in text_fields:
            self.fields[field_name].widget.attrs["autocomplete"] = "off"

    def clean_invoice_bcc(self):
        """Normalize + validate the comma/semicolon-separated BCC list."""
        raw = self.cleaned_data.get("invoice_bcc", "")
        addresses = [a.strip() for a in raw.replace(";", ",").split(",") if a.strip()]
        invalid = []
        for addr in addresses:
            try:
                validate_email(addr)
            except ValidationError:
                invalid.append(addr)
        if invalid:
            raise ValidationError(f"Invalid email address(es): {', '.join(invalid)}")
        return ", ".join(addresses)

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")

        if not logo or not hasattr(logo, "content_type"):
            return logo

        if logo.content_type not in ALLOWED_LOGO_TYPES:
            raise ValidationError("Only PNG, JPG, and SVG files are allowed.")

        if logo.size > MAX_LOGO_SIZE:
            raise ValidationError("Logo must be under 2 MB.")

        return logo


class CompanyBillingForm(forms.ModelForm):
    """Billing subsection: look of the client payment page + payment emails."""

    class Meta:
        model = Company
        fields = ["payment_font", "payment_background"]
        widgets = {
            "payment_font": forms.RadioSelect,
            "payment_background": forms.RadioSelect,
        }
        labels = {
            "payment_font": "Font",
            "payment_background": "Background",
        }


class CompanyResearchForm(forms.ModelForm):
    """Research subsection (e.g. default jurisdiction for legal research)."""

    class Meta:
        model = Company
        fields = ["jurisdiction"]
