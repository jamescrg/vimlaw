from django import forms

from config.settings import CustomFormRendererCompact

from .models import Fact


class FactForm(forms.ModelForm):
    class Meta:
        model = Fact

        fields = (
            "date",
            "time",
            "description",
            "color",
        )

        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "time": forms.TimeInput(
                attrs={"type": "time", "tabindex": "5"}, format="%H:%M"
            ),
            "description": forms.Textarea(
                attrs={
                    "autofocus": "autofocus",
                    "onfocus": "moveFocusToEnd(this)",
                    "class": "span2",
                    "rows": 3,
                }
            ),
            "color": forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
