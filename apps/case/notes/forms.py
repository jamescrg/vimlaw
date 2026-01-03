from django import forms

from apps.matters.models import Matter
from apps.notes.models import Note
from config.settings import CustomFormRendererCompact


class NoteForm(forms.ModelForm):
    default_renderer = CustomFormRendererCompact

    class Meta:
        model = Note
        fields = ["matter", "category", "title"]
        widgets = {
            "matter": forms.Select(),
            "category": forms.Select(),
            "title": forms.TextInput(attrs={"autofocus": True, "class": "span2"}),
        }

    def __init__(self, *args, **kwargs):
        kwargs.pop("matter", None)
        super().__init__(*args, **kwargs)
        # Limit matter choices to open matters
        self.fields["matter"].queryset = Matter.objects.filter(status="Open").order_by(
            "name"
        )
