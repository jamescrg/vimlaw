from django import forms

from apps.case.models import Label
from config.settings import CustomFormRendererCompact


class LabelsForm(forms.ModelForm):
    class Meta:
        model = Label
        fields = ["matter", "color", "name"]
        widgets = {
            "matter": forms.Select(attrs={"class": "span1"}),
            "color": forms.Select(attrs={"class": "span1"}),
            "name": forms.TextInput(attrs={"class": "span2"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.renderer = CustomFormRendererCompact()
        # Allow empty selection for global labels
        self.fields["matter"].required = False
        self.fields["matter"].empty_label = "Global (all matters)"
