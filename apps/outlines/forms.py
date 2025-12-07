from django import forms

from .models import Outline


class OutlineForm(forms.ModelForm):
    """Form for creating/editing outlines."""

    class Meta:
        model = Outline
        fields = ["title", "date"]
        widgets = {
            "title": forms.TextInput(attrs={"autofocus": True, "class": "span2"}),
            "date": forms.DateInput(attrs={"type": "date", "class": "span2"}),
        }
