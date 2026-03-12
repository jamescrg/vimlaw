from django import forms

from apps.activity.models import ActivityLabel
from config.settings import CustomFormRendererCompact


class ActivityLabelForm(forms.ModelForm):
    class Meta:
        model = ActivityLabel
        fields = ["name", "color"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "span2", "autofocus": True}),
            "color": forms.Select(attrs={"class": "span1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.renderer = CustomFormRendererCompact()
