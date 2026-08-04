from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from apps.management.templatetags.phone_numbers import phone_number
from apps.settings.models import Firm
from config.helpers import normalize_phone

MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2MB
ALLOWED_LOGO_TYPES = ["image/png", "image/jpeg", "image/svg+xml"]


class FirmForm(forms.ModelForm):
    """Firm-settings form: contact details, invoice BCC, and research
    jurisdiction — saved together by the "Save Firm Details" button.

    The logo is intentionally NOT part of this form: it uploads/removes on its
    own (see FirmLogoForm + the firm-upload-logo/firm-remove-logo endpoints), so
    changing the logo never depends on saving the rest of the details."""

    class Meta:
        model = Firm
        fields = [
            "name",
            "address_line_1",
            "address_line_2",
            "city",
            "state",
            "zip_code",
            "phone",
            "email",
            "billing_email",
            "invoice_bcc",
            "intake_email",
            "jurisdiction",
        ]
        widgets = {
            "invoice_bcc": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {
            "billing_email": "Billing Email",
            "invoice_bcc": "Invoice BCC",
            "intake_email": "Intake Email",
        }
        help_texts = {
            "jurisdiction": "Default jurisdiction for legal research.",
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
            "billing_email",
            "invoice_bcc",
            "intake_email",
            "jurisdiction",
        ]
        # Keep browsers from offering to "save this address". Firefox/Chrome
        # capture addresses when they *classify* a group of fields as one — on
        # submit AND on navigation — and they ignore autocomplete="off" for that.
        # Tagging every field with a recognized *non-address* token
        # ("one-time-code") makes them classify each field by that token instead
        # of by its name, so no address profile is ever assembled to capture.
        # (Paired with the template posting via a button, not a <form> submit.)
        for field_name in text_fields:
            self.fields[field_name].widget.attrs["autocomplete"] = "one-time-code"

        # Show the stored digits formatted as (XXX) XXX-XXXX in the input;
        # clean_phone normalizes back to raw digits on save.
        if not self.is_bound and self.instance and self.instance.phone:
            self.initial["phone"] = phone_number(self.instance.phone)

    def clean_phone(self):
        """Normalize to raw digits (+ optional extension), matching contacts."""
        value = self.cleaned_data.get("phone", "")
        if value:
            normalized, is_valid = normalize_phone(value)
            if not is_valid:
                raise ValidationError("Enter a valid 10-digit US phone number.")
            return normalized
        return value

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


class FirmLogoForm(forms.ModelForm):
    """Standalone logo upload — auto-submits on file selection, independent of
    the main firm-details form."""

    class Meta:
        model = Firm
        fields = ["logo"]
        widgets = {
            "logo": forms.FileInput(
                attrs={
                    "accept": ".png,.jpg,.jpeg,.svg",
                    # Auto-upload the moment a file is chosen; CSRF rides on the
                    # global hx-headers set on <body>.
                    "hx-post": "/settings/firm/logo/upload/",
                    "hx-trigger": "change",
                    "hx-target": "#firm-logo",
                    "hx-encoding": "multipart/form-data",
                }
            ),
        }
        help_texts = {
            "logo": "PNG, JPG, or SVG. Max 2 MB.",
        }

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")

        if not logo or not hasattr(logo, "content_type"):
            return logo

        if logo.content_type not in ALLOWED_LOGO_TYPES:
            raise ValidationError("Only PNG, JPG, and SVG files are allowed.")

        if logo.size > MAX_LOGO_SIZE:
            raise ValidationError("Logo must be under 2 MB.")

        return logo
