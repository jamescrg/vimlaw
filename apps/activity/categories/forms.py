from django import forms

from apps.activity.models import ActivityCategory
from config.settings import CustomFormRendererCompact


class ActivityCategoriesForm(forms.ModelForm):
    """Add/edit form for a matter's activity categories.

    The matter comes from the tab context (the view binds an instance with
    it set); position comes from drag-reordering on the Categories tab.
    Claimed categories are the sections of the matter's Fee Claim Report.
    """

    class Meta:
        model = ActivityCategory
        fields = ["name", "color", "claimed"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "span2"}),
            "color": forms.Select(attrs={"class": "span1"}),
            "claimed": forms.Select(
                choices=[("False", "No"), ("True", "Yes")],
                attrs={"class": "span1"},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.renderer = CustomFormRendererCompact()

    def clean_name(self):
        # The per-matter unique constraint isn't form-validated because
        # matter isn't a form field, so check it here instead of 500ing.
        name = self.cleaned_data["name"]
        existing = ActivityCategory.objects.filter(
            matter=self.instance.matter, name=name
        ).exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError(
                "This matter already has a category with this name."
            )
        return name
