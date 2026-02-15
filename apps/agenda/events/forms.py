from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.models import CustomUser
from config.settings import CustomFormRendererCompact

from .models import Event


class EventForm(forms.ModelForm):

    class Meta:
        model = Event
        fields = (
            "status",
            "party",
            "date",
            "matter",
            "description",
            "start_time",
            "end_time",
            "location",
            "assigned_to",
        )
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
                    "autofocus": "autofocus",
                    "onfocus": "moveFocusToEnd(this)",
                    "class": "span2",
                }
            ),
            "party": forms.Select(choices=PARTIES),
            "status": forms.Select(choices=STATUSES),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()

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
