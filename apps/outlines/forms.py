from django import forms

from apps.matters.models import Matter

from .models import Outline


class OutlineForm(forms.ModelForm):
    """Form for creating/editing outlines."""

    matter = forms.ModelChoiceField(
        queryset=Matter.objects.none(),
        required=False,
        empty_label="No matter (standalone)",
    )

    class Meta:
        model = Outline
        fields = ["title", "matter"]
        widgets = {
            "title": forms.TextInput(attrs={"autofocus": True, "class": "span2"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields["matter"].queryset = Matter.objects.filter(
                user=user, status="Open"
            ).order_by("name")
