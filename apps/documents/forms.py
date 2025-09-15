from django import forms

from apps.documents.models import Document
from apps.matters.proceedings.models import Proceeding
from config.settings import CustomFormRendererCompact


class DocumentsForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["name", "matter", "date", "description", "category", "proceeding"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "span2"}),
            "date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3, "class": "span2"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()

        # Add HTMX attributes to matter field
        self.fields["matter"].widget.attrs.update(
            {
                "hx-get": "/documents/get-proceedings/",
                "hx-target": "#id_proceeding",
                "hx-trigger": "change",
                "hx-include": "this",
            }
        )

        # Initially show no proceedings
        self.fields["proceeding"].queryset = Proceeding.objects.none()

        # If editing and has a matter, show proceedings for that matter
        if self.instance.pk and self.instance.matter:
            self.fields["proceeding"].queryset = (
                self.instance.matter.proceeding_set.all()
            )
