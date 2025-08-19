from django import forms

from apps.documents.models import Document
from config.settings import CustomFormRendererCompact


class DocumentsForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["name", "matter", "date", "description"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "span2"}),
            "date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3, "class": "span2"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
