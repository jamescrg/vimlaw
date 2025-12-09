from django import forms

from config.settings import CustomFormRendererCompact

from .models import Outline


class OutlineForm(forms.ModelForm):
    """Form for creating/editing outlines."""

    default_renderer = CustomFormRendererCompact

    class Meta:
        model = Outline
        fields = ["date", "category", "title"]
        widgets = {
            "title": forms.TextInput(attrs={"autofocus": True}),
            "date": forms.DateInput(attrs={"type": "date"}),
            "category": forms.Select(),
        }
