from django import forms

from apps.case.models import Document
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding
from config.settings import CustomFormRendererCompact


class ProceedingChoiceField(forms.ModelChoiceField):
    """Custom field to display proceedings as 'Forum - Case Number'."""

    def label_from_instance(self, obj):
        return f"{obj.forum} - {obj.case_number}"


class FilesForm(forms.ModelForm):
    matter = forms.ModelChoiceField(
        queryset=Matter.objects.none(),
        required=True,
        empty_label=None,
    )
    proceeding = ProceedingChoiceField(
        queryset=Proceeding.objects.none(),
        required=False,
        empty_label="Select Proceeding",
    )

    class Meta:
        model = Document
        fields = [
            "matter",
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

        # Populate matter choices with all open matters
        self.fields["matter"].queryset = Matter.objects.filter(status="Open").order_by(
            "name"
        )

        # If matter provided (new document), set it as initial
        if matter:
            self.fields["matter"].initial = matter
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

    def clean(self):
        cleaned_data = super().clean()
        matter = cleaned_data.get("matter")
        proceeding = cleaned_data.get("proceeding")

        # Clear proceeding if matter changed and proceeding doesn't belong to new matter
        if proceeding and matter and proceeding.matter_id != matter.id:
            cleaned_data["proceeding"] = None

        return cleaned_data


class BulkFilesForm(forms.ModelForm):
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
