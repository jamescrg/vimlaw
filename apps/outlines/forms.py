from django import forms

from .models import Outline


class OutlineForm(forms.ModelForm):
    """Form for creating/editing outlines."""

    class Meta:
        model = Outline
        fields = ["title"]
        widgets = {
            "title": forms.TextInput(attrs={"autofocus": True, "class": "span2"}),
        }
