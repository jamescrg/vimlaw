from django import forms

from apps.matters.rates.models import Rate
from config.settings import CustomFormRendererCompact


class RateForm(forms.ModelForm):
    class Meta:
        model = Rate

        fields = (
            "user",
            "matter_rate",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
