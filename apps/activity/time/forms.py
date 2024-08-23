from django import forms

from .models import TimeEntry


class TimeEntryForm(forms.ModelForm):
    class Meta:
        model = TimeEntry

        fields = (
            "date",
            "matter",
            "rate",
            "actions",
            "hours",
            "comp",
            "entered",
        )

        COMP_CHOICES = (
            (0, "No"),
            (1, "Yes"),
        )

        ENTERED_CHOICES = (
            (0, "No"),
            (1, "Yes"),
        )

        widgets = {
            "matter": forms.Select(attrs={"onchange": "updateRate()"}),
            "date": forms.DateInput(attrs={"type": "date"}),
            "actions": forms.Textarea(attrs={"autofocus": "autofocus"}),
            "comp": forms.Select(choices=COMP_CHOICES),
            "entered": forms.Select(choices=ENTERED_CHOICES),
        }

        labels = {"rate": "Rate"}
