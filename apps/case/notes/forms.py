from django import forms

from apps.case.models import Note
from config.settings import CustomFormRendererCompact

IMPORTANCE_CHOICES = tuple((i, f"Importance {i}") for i in range(1, 11))


class NoteForm(forms.ModelForm):
    class Meta:
        model = Note
        fields = ("title", "importance")
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "autofocus": "autofocus",
                    "placeholder": "Note title",
                }
            ),
            "importance": forms.Select(choices=IMPORTANCE_CHOICES),
        }

    def __init__(self, *args, **kwargs):
        kwargs.pop("matter", None)
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
