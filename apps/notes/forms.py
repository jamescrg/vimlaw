from django import forms

from config.settings import CustomFormRendererCompact

from .models import Note


class NoteForm(forms.ModelForm):
    default_renderer = CustomFormRendererCompact

    class Meta:
        model = Note
        fields = ["category", "topic", "title"]
        widgets = {
            "title": forms.TextInput(attrs={"autofocus": True, "class": "span2"}),
            "category": forms.Select(),
            "topic": forms.TextInput(attrs={"class": "span2"}),
        }
