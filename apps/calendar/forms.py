from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.models import CustomUser
from config.settings import CustomFormRendererCompact

from .models import Event


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = (
            "date",
            "start_time",
            "end_time",
            "assigned_to",
            "matter",
            "description",
            "status",
            "party",
            "event_type",
            "location",
        )
        labels = {
            "event_type": "Type",
            "location": "Location",
        }
        PARTIES = (
            ("Client", "Client"),
            ("Opposing", "Opposing"),
            ("All", "All"),
            ("Other", "Other"),
        )
        STATUSES = (
            ("Pending", "Pending"),
            ("Complete", "Complete"),
            ("Missed", "Missed"),
        )
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
            "description": forms.TextInput(
                attrs={
                    "onfocus": "moveFocusToEnd(this)",
                    "class": "span3",
                }
            ),
            "party": forms.Select(choices=PARTIES),
            "status": forms.Select(choices=STATUSES),
            "location": forms.TextInput(
                attrs={
                    "class": "span3",
                    "placeholder": "Zoom link & passcode, or courthouse address & courtroom",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()

        # Matter spans the first two of the three columns
        self.fields["matter"].widget.attrs["class"] = "span2"

        # Filter assigned_to to active users, alphabetical, title case
        self.fields["assigned_to"].queryset = CustomUser.objects.filter(
            is_active=True
        ).order_by("first_name", "last_name")
        self.fields["assigned_to"].label_from_instance = lambda u: u.full_name
        self.fields["assigned_to"].empty_label = "Firm"

    def clean_description(self):
        description = self.cleaned_data["description"]
        if len(description) < 4:
            raise ValidationError("Description must be 4 or more characters.")
        if len(description) > 200:
            raise ValidationError("Description is limited to 200 character.")
        return description

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")
        if start_time and end_time and start_time >= end_time:
            self.add_error("end_time", "End time must be after start time.")
        return cleaned_data
