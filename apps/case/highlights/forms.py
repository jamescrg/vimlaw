from django import forms

from apps.case.models import Highlight
from config.settings import CustomFormRendererCompact

# Importance choices for select widget (1-10)
IMPORTANCE_CHOICES = tuple((i, f"Importance {i}") for i in range(1, 11))


class HighlightForm(forms.ModelForm):
    class Meta:
        model = Highlight
        fields = [
            "importance",
            "color",
            "paragraph_number",
            "page_number",
            "slug",
            "text",
        ]
        widgets = {
            "color": forms.Select(),
            "importance": forms.Select(choices=IMPORTANCE_CHOICES),
            "paragraph_number": forms.TextInput(),
            "page_number": forms.TextInput(),
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

        # Show page_number for case highlights, paragraph_number for document highlights
        if self.instance and self.instance.pk and self.instance.caselaw_id:
            # Case highlight - remove paragraph_number, keep page_number
            del self.fields["paragraph_number"]
        else:
            # Document highlight - remove page_number, keep paragraph_number
            del self.fields["page_number"]
