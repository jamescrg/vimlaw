from django import forms
from django.core.exceptions import ValidationError

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
            "logo",
            "jurisdiction",
        ]
        widgets = {
            "logo": forms.ClearableFileInput(attrs={"accept": ".png,.jpg,.jpeg,.svg"}),
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
