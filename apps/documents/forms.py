from django import forms

from apps.documents.models import Document, Label
from apps.matters.proceedings.models import Proceeding
from config.settings import CustomFormRendererCompact


class DocumentsForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = [
            "name",
            "matter",
            "date",
            "description",
            "category",
            "proceeding",
            "labels",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "span2"}),
            "date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3, "class": "span2"}),
            "labels": forms.SelectMultiple(attrs={"class": "span2"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.renderer = CustomFormRendererCompact()

        self.fields["matter"].widget.attrs.update(
            {
                "hx-get": "/documents/get-proceedings-and-labels/",
                "hx-target": "closest form",
                "hx-trigger": "change",
                "hx-include": "this",
                "hx-swap": "none",
            }
        )

        # Initially show no proceedings
        self.fields["proceeding"].queryset = Proceeding.objects.none()
        self.fields["labels"].queryset = Label.objects.none()

        # If editing and has a matter, show proceedings for that matter
        if self.instance.pk and self.instance.matter:
            self.fields["proceeding"].queryset = (
                self.instance.matter.proceeding_set.all()
            )
            self.fields["labels"].queryset = self.instance.matter.labels.all()


class BulkDocumentsForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["matter"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.renderer = CustomFormRendererCompact()


class LabelsForm(forms.ModelForm):
    class Meta:
        model = Label
        fields = ["name", "matter", "color"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "span2"}),
            "matter": forms.Select(attrs={"class": "span1"}),
            "color": forms.TextInput(attrs={"type": "color", "class": "span1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.renderer = CustomFormRendererCompact()
