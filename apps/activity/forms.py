from django import forms

from .models import TimeEntry
from .models import ExpenseEntry


class TimeEntryForm(forms.ModelForm):
    class Meta:
        model = TimeEntry

        fields = (
            "date",
            "matter",
            "firm_rate",
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

        labels = {
            "firm_rate": "Rate"
        }


class ExpenseEntryForm(forms.ModelForm):
    class Meta:
        model = ExpenseEntry

        fields = (
            "date",
            "matter",
            "category",
            "description",
            "amount",
            "comp",
            "entered",
        )

        CATEGORY_CHOICES = (
            (None, "----------"),
            ("Contract Services", "Contract Services"),
            ("Court Reporters", "Court Reporters"),
            ("Filing Fee", "Filing Fee"),
            ("Outside Counsel", "Outside Counsel"),
            ("Postage", "Postage"),
            ("Process Server", "Process Server"),
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
            "description": forms.Textarea(attrs={"autofocus": "autofocus"}),
            "comp": forms.Select(choices=COMP_CHOICES),
            "entered": forms.Select(choices=ENTERED_CHOICES),
            "category": forms.Select(choices=CATEGORY_CHOICES),
        }
