from django import forms
from django.core.exceptions import ValidationError

from apps.matters.models import PracticeArea
from config.helpers import normalize_phone
from config.settings import CustomFormRendererCompact

from .models import Intake, Note


class IntakeForm(forms.ModelForm):
    class Meta:
        model = Intake

        # Ordered to flow into a 3-column grid (see templates/intakes/form.html
        # `col3`): Status | Open Date | Source, then Name(span2) | Practice Area,
        # then Phone | Email | Value, then the two full-width property textareas.
        fields = (
            "status",
            "date",
            "source",
            "name",
            "practice_area",
            "phone",
            "email",
            "value",
            "address",
            "disputed_property",
        )

        STATUSES = (
            ("Open", "Open"),
            ("Pending", "Pending"),
            ("Accepted", "Accepted"),
            ("Referred Out", "Referred Out"),
            ("Client Declined", "Client Declined"),
            ("Unresponsive", "Unresponsive"),
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
                    "onfocus": "moveFocusToEnd(this)",
                    "class": "span2",
                }
            ),
            "address": forms.Textarea(
                attrs={
                    "class": "span3",
                    "rows": 3,
                }
            ),
            "disputed_property": forms.Textarea(
                attrs={
                    "class": "span3",
                    "rows": 3,
                }
            ),
            "value": forms.TextInput(),
            "status": forms.Select(choices=STATUSES),
            "source": forms.Select(choices=SOURCES),
            "date": forms.DateInput(attrs={"type": "date"}),
        }

        labels = {
            "date": "Open Date",
            "practice_area": "Practice Area",
            "disputed_property": "Disputed Property Address (if different)",
            "value": "Disputed Property Value",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()

        # Filter practice areas to only show active ones
        self.fields["practice_area"].queryset = PracticeArea.objects.filter(
            is_active=True
        )

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
