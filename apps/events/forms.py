from django import forms

from .models import Event


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = (
            "matter",
            "date",
            "party",
            "description",
            "status",
        )
        PARTIES = (
            ("Client", "Client"),
            ("Opposing", "Opposing"),
            ("All", "All"),
            ("Other", "Other"),
        )
        STATUSES = (
            ("Pending", "Pending"),
            ("Completed", "Completed"),
            ("Missed", "Missed"),
        )
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.TextInput(attrs={"autofocus": "autofocus"}),
            "party": forms.Select(choices=PARTIES),
            "status": forms.Select(choices=STATUSES),
        }
