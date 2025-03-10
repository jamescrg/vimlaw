from django import forms

from .models import Fact


class FactForm(forms.ModelForm):
    class Meta:
        model = Fact

        fields = (
            "date",
            "time",
            "description",
            "citation",
            "emphasis",
        )

        EMPHASIS_OPTIONS = (
            ("No", "No"),
            ("Yes", "Yes"),
        )

        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "emphasis": forms.Select(choices=EMPHASIS_OPTIONS),
        }
