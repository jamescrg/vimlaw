from django import forms

from apps.matters.rates.models import Rate


class RateForm(forms.ModelForm):
    class Meta:
        model = Rate

        fields = (
            "user",
            "matter_rate",
        )
