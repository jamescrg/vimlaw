from datetime import datetime

from django import forms

from apps.invoicing.credits.models import Credit
from config.settings import CustomFormRendererCompact


class CreditsForm(forms.ModelForm):
    class Meta:
        model = Credit
        fields = ["matter", "date", "detail", "amount"]
        widgets = {
            "matter": forms.Select(attrs={"class": "span2"}),
            "date": forms.DateInput(attrs={"type": "date", "class": "span2"}),
            "detail": forms.TextInput(attrs={"required": False, "class": "span2"}),
            "amount": forms.TextInput(attrs={"class": "span2"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()

        self.fields["date"].initial = datetime.now().date()
