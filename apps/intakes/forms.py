from django import forms
from django.core.exceptions import ValidationError

from config.helpers import normalize_phone
from config.settings import CustomFormRendererCompact

from .models import Intake, Note


class IntakeForm(forms.ModelForm):
    class Meta:
        model = Intake

        fields = (
            "status",
            "date",
            "name",
            "phone",
            "email",
            "practice_area",
            "source",
            "address",
            "disputed_property",
            "value",
        )

        STATUSES = (
            ("Open", "Open"),
            ("Pending", "Pending"),
            ("Accepted", "Accepted"),
            ("Referred Out", "Referred Out"),
            ("Client Declined", "Client Declined"),
            ("Unresponsive", "Unresponsive"),
        )

        PRACTICE_AREAS = (
            ("General", "General"),
            ("Boundary", "Boundary"),
            ("Title", "Title"),
            ("LLT - LL", "LLT - LL"),
            ("LLT - T", "LLT - T"),
            ("QT", "QT"),
            ("HOA", "HOA"),
            ("Fraud", "Fraud"),
            ("Construction", "Construction"),
        )

        SOURCES = (
            ("Unknown", "Unknown"),
            ("Internet", "Internet"),
            ("Agent", "Agent"),
            ("Attorney - Internal", "Attorney - Internal"),
            ("Attorney - External", "Attorney - External"),
            ("Other", "Other"),
        )

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "autofocus": "autofocus",
                    "onfocus": "moveFocusToEnd(this)",
                    "class": "span2",
                }
            ),
            "address": forms.Textarea(
                attrs={
                    "class": "span2",
                    "rows": 4,
                }
            ),
            "disputed_property": forms.Textarea(
                attrs={
                    "class": "span2",
                    "rows": 4,
                }
            ),
            "value": forms.TextInput(attrs={"class": "span2"}),
            "status": forms.Select(choices=STATUSES),
            "practice_area": forms.Select(choices=PRACTICE_AREAS),
            "source": forms.Select(choices=SOURCES),
            "date": forms.DateInput(attrs={"type": "date"}),
        }

        labels = {
            "date": "Open Date",
            "practice_area": "Practice Area",
            "disputed_property": "Disputed Property (if different from address)",
            "value": "Disputed Property Value",
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

    def clean_address(self):
        address = self.cleaned_data["address"]
        if address:
            if len(address) > 250:
                raise ValidationError("Address must be fewer than 250 characters.")
        return address

    def clean_disputed_property(self):
        disputed_property = self.cleaned_data["disputed_property"]
        if disputed_property:
            if len(disputed_property) > 250:
                raise ValidationError(
                    "Disputed property must be fewer than 250 characters."
                )
        return disputed_property

    def clean_phone(self):
        value = self.cleaned_data.get("phone")
        if value:
            normalized, is_valid = normalize_phone(value)
            if not is_valid:
                raise ValidationError("Enter a valid 10-digit US phone number.")
            return normalized
        return value


class NoteForm(forms.ModelForm):
    class Meta:
        model = Note

        fields = (
            "date",
            "time",
            "type",
            "details",
        )

        TYPES = (
            ("Call In", "Call In"),
            ("Call Out", "Call Out"),
            ("Email In", "Email In"),
            ("Email Out", "Email Out"),
            ("VM In", "VM In"),
            ("VM Out", "VM Out"),
            ("Comment", "Comment"),
        )

        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "type": forms.Select(choices=TYPES),
            "details": forms.Textarea(attrs={"class": "span3", "rows": "8"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
