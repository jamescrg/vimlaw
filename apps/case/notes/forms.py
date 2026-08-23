from django import forms

from apps.accounts.access import filter_matters_for_user
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
            "title": forms.TextInput(attrs={"class": "span2"}),
        }

    def __init__(self, *args, **kwargs):
        kwargs.pop("matter", None)
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        # Limit matter choices to open matters
        queryset = Matter.objects.filter(status="Open").order_by("name")
        if user:
            queryset = filter_matters_for_user(queryset, user)
        self.fields["matter"].queryset = queryset
