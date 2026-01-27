from django import forms

from apps.settings.models import FirmProfile
from config.settings import CustomFormRendererCompact


class FirmProfileForm(forms.ModelForm):
    class Meta:
        model = FirmProfile
        fields = [
            "name",
            "name_suffix",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "zip_code",
            "phone",
            "email",
            "logo",
            "trust_caption",
        ]
        widgets = {
            "trust_caption": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
