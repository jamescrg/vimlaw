from django import forms

from apps.documents.models import Document, Fact, Highlight, Label
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding
from config.settings import CustomFormRendererCompact

# Importance choices for select widget (1-10)
importance = []
for i in range(1, 11):
    importance.append((i, f"Importance {i}"))
IMPORTANCE = tuple(importance)


class ProceedingChoiceField(forms.ModelChoiceField):
    """Custom field to display proceedings as 'Forum - Case Number'."""

    def label_from_instance(self, obj):
        return f"{obj.forum} - {obj.case_number}"


class DocumentsForm(forms.ModelForm):
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
            "importance",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3, "class": "span2"}),
            "name": forms.TextInput(attrs={"class": "span2", "autofocus": True}),
            "importance": forms.Select(choices=IMPORTANCE),
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


class HighlightForm(forms.ModelForm):
    class Meta:
        model = Highlight
        fields = ["color", "slug", "importance"]
        widgets = {
            "color": forms.Select(),
            "slug": forms.TextInput(attrs={"class": "span2"}),
            "importance": forms.Select(choices=IMPORTANCE),
        }

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


class FactForm(forms.ModelForm):
    class Meta:
        model = Fact

        fields = (
            "date",
            "time",
            "description",
            "color",
            "importance",
        )

        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "time": forms.TimeInput(
                attrs={"type": "time", "tabindex": "5"}, format="%H:%M"
            ),
            "description": forms.Textarea(
                attrs={
                    "autofocus": "autofocus",
                    "onfocus": "moveFocusToEnd(this)",
                    "class": "span2",
                    "rows": 3,
                }
            ),
            "color": forms.Select(),
            "importance": forms.Select(choices=IMPORTANCE),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
