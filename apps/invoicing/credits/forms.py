from datetime import datetime

from django import forms

from apps.invoicing.credits.models import Credit
from config.settings import CustomFormRendererCompact


class CreditsForm(forms.ModelForm):
    class Meta:
        model = Credit
        fields = [
            "date",
            "matter",
            "amount",
            "detail",
        ]
        widgets = {
            "matter": forms.Select(attrs={"class": ""}),
            "date": forms.DateInput(attrs={"type": "date", "class": ""}),
            "amount": forms.TextInput(attrs={"class": ""}),
            "detail": forms.TextInput(attrs={"required": False, "class": "span3"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()

        self.fields["date"].initial = datetime.now().date()
