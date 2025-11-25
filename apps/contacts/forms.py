from django import forms
from django.core.exceptions import ValidationError

from config.helpers import normalize_phone
from config.settings import CustomFormRendererCompact

from .models import Contact


class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact

        fields = (
            "client_status",
            "folder",
            "name",
            "company",
            "address",
            "phone1",
            "phone1_label",
            "phone2",
            "phone2_label",
            "phone3",
            "phone3_label",
            "email",
            "notes",
        )

        PHONE_LABELS = (
            ("Mobile", "Mobile"),
            ("Home", "Home"),
            ("Work", "Work"),
            ("Fax", "Fax"),
            ("Other", "Other"),
        )

        CLIENT_STATUSES = (
            ("Nonclient", "Nonclient"),
            ("Pending", "Pending"),
            ("Current", "Current"),
            ("Former", "Former"),
        )

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "autofocus": "autofocus",
                    "onfocus": "moveFocusToEnd(this)",
                    "class": "span2",
                }
            ),
            "company": forms.TextInput(attrs={"class": "span2"}),
            "email": forms.TextInput(attrs={"class": "span2"}),
            "address": forms.Textarea(
                attrs={
                    "class": "span2",
                    "rows": "3",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "span2",
                    "rows": "3",
                }
            ),
            "phone1_label": forms.Select(choices=PHONE_LABELS),
            "phone2_label": forms.Select(choices=PHONE_LABELS),
            "phone3_label": forms.Select(choices=PHONE_LABELS),
            "client_status": forms.Select(choices=CLIENT_STATUSES),
        }

        labels = {
            "phone1": "Phone 1",
            "phone2": "Phone 2",
            "phone3": "Phone 3",
            "phone1_label": "For",
            "phone2_label": "For",
            "phone3_label": "For",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()

    def clean_name(self):
        name = self.cleaned_data["name"]
        if len(name) < 2:
            raise ValidationError("Name must be greater than 2 characters")
        if len(name) > 50:
            raise ValidationError("Name must be fewer than 50 characters")
        return name

    def clean_company(self):
        company = self.cleaned_data["company"]
        if company:
            if len(company) >= 50:
                raise ValidationError("Company must be fewer than 50 characters.")
        return company

    def clean_address(self):
        address = self.cleaned_data["address"]
        if address:
            if len(address) > 250:
                raise ValidationError("Address must be fewer than 250 characters.")
        return address

    def clean_phone1(self):
        value = self.cleaned_data.get("phone1")
        if value:
            normalized, is_valid = normalize_phone(value)
            if not is_valid:
                raise ValidationError("Enter a valid 10-digit US phone number.")
            return normalized
        return value

    def clean_phone2(self):
        value = self.cleaned_data.get("phone2")
        if value:
            normalized, is_valid = normalize_phone(value)
            if not is_valid:
                raise ValidationError("Enter a valid 10-digit US phone number.")
            return normalized
        return value

    def clean_phone3(self):
        value = self.cleaned_data.get("phone3")
        if value:
            normalized, is_valid = normalize_phone(value)
            if not is_valid:
                raise ValidationError("Enter a valid 10-digit US phone number.")
            return normalized
        return value

    def clean_notes(self):
        notes = self.cleaned_data["notes"]
        if notes:
            if len(notes) >= 250:
                raise ValidationError("Notes must be fewer than 250 characters.")
        return notes
