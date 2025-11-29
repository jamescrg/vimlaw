from django import forms

from apps.documents.models import Document, Label
from apps.matters.proceedings.models import Proceeding
from config.settings import CustomFormRendererCompact


class ProceedingChoiceField(forms.ModelChoiceField):
    """Custom field to display proceedings as 'Forum - Case Number'."""

    def label_from_instance(self, obj):
        return f"{obj.forum} - {obj.case_number}"


class DocumentsForm(forms.ModelForm):
    proceeding = ProceedingChoiceField(
        queryset=Proceeding.objects.none(),
        required=False,
        empty_label="Select Proceeding",
    )

    class Meta:
        model = Document
        fields = [
            "category",
            "proceeding",
            "date",
            "name",
            "description",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3, "class": "span2"}),
            "name": forms.TextInput(attrs={"class": "span2", "autofocus": True}),
        }

    def __init__(self, *args, matter=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.renderer = CustomFormRendererCompact()
        self.matter = matter

        # If matter provided, populate proceedings for that matter
        if matter:
            self.fields["proceeding"].queryset = matter.proceeding_set.all().order_by(
                "forum", "case_number"
            )
        # If editing and has a matter, show proceedings for that matter
        elif self.instance.pk and self.instance.matter:
            self.fields[
                "proceeding"
            ].queryset = self.instance.matter.proceeding_set.all().order_by(
                "forum", "case_number"
            )
        else:
            self.fields["proceeding"].queryset = Proceeding.objects.none()


class BulkDocumentsForm(forms.ModelForm):
    proceeding = ProceedingChoiceField(
        queryset=Proceeding.objects.none(),
        required=False,
        empty_label="Select Proceeding",
    )

    class Meta:
        model = Document
        fields = ["proceeding"]

    def __init__(self, *args, matter=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.renderer = CustomFormRendererCompact()
        self.matter = matter

        if matter:
            self.fields["proceeding"].queryset = matter.proceeding_set.all().order_by(
                "forum", "case_number"
            )
        else:
            self.fields["proceeding"].queryset = Proceeding.objects.none()


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
