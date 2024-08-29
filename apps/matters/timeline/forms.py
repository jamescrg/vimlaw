from django import forms

from .models import Fact


class FactForm(forms.ModelForm):
    class Meta:
        model = Fact

        fields = (
            "date",
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
            "emphasis": forms.Select(choices=EMPHASIS_OPTIONS),
        }
