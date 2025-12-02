from django import forms

from config.settings import CustomFormRendererCompact

from .models import Fact

# Importance choices for select widget (1-10)
importance = []
for i in range(1, 11):
    importance.append((i, f"Importance {i}"))
IMPORTANCE = tuple(importance)


class FactForm(forms.ModelForm):
    class Meta:
        model = Fact

        fields = (
            "date",
            "time",
            "description",
            "color",
            "importance",
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
            "importance": forms.Select(choices=IMPORTANCE),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
