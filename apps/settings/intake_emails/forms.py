from django import forms

from apps.intakes.models import IntakeEmailTemplate
from config.settings import CustomFormRendererCompact


class IntakeEmailTemplateForm(forms.ModelForm):
    class Meta:
        model = IntakeEmailTemplate
        fields = ["name", "subject", "body"]

        widgets = {
            "body": forms.Textarea(attrs={"rows": 12}),
        }

        help_texts = {
            "name": "How the template appears in the send menu.",
            "body": (
                "Plain text, sent as written. No merge fields - the send "
                "modal allows editing the salutation per send."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
