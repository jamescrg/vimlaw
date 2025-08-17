from django import forms

from apps.documents.models import Document
from config.settings import CustomFormRendererCompact


class DocumentsForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["name", "matter", "description"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "span2"}),
            "matter": forms.Select(attrs={"class": "span2"}),
            "description": forms.Textarea(attrs={"rows": 3, "class": "span2"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
