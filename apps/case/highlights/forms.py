from django import forms

from apps.case.models import Highlight
from config.settings import CustomFormRendererCompact

# Importance choices for select widget (1-10)
IMPORTANCE_CHOICES = tuple((i, f"Importance {i}") for i in range(1, 11))


class HighlightForm(forms.ModelForm):
    class Meta:
        model = Highlight
        fields = ["importance", "color", "paragraph_number", "slug", "text"]
        widgets = {
            "color": forms.Select(),
            "importance": forms.Select(choices=IMPORTANCE_CHOICES),
            "paragraph_number": forms.TextInput(),
            "slug": forms.TextInput(
                attrs={"class": "span3", "required": True, "autofocus": True}
            ),
            "text": forms.Textarea(attrs={"class": "span3", "rows": 8}),
        }

    def __init__(self, *args, **kwargs):
        # Remove matter kwarg if passed (no longer needed)
        kwargs.pop("matter", None)
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = True
        self.renderer = CustomFormRendererCompact()
