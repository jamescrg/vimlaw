from django import forms

from .models import Fact


class FactForm(forms.ModelForm):
    class Meta:
        model = Fact

        fields = (
            "date",
            "time",
            "description",
            "citations",
            "color",
        )

        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "time": forms.TimeInput(
                attrs={"type": "time", "tabindex": "5"}, format="%H:%M"
            ),
            "description": forms.TextInput(
                attrs={"autofocus": "autofocus", "onfocus": "moveFocusToEnd(this)"}
            ),
            "color": forms.Select(),
        }
