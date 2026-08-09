from django import forms

from config.settings import CustomFormRendererCompact

from .models import Note, NoteFolder


class NoteForm(forms.ModelForm):
    default_renderer = CustomFormRendererCompact

    class Meta:
        model = Note
        fields = ["title"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "span2"}),
        }


class NoteFolderForm(forms.ModelForm):
    YESNO_CHOICES = (
        (False, "No"),
        (True, "Yes"),
    )

    class Meta:
        model = NoteFolder
        fields = ["name", "parent", "ai_library"]

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Folder name",
                    "onfocus": "moveFocusToEnd(this)",
                }
            ),
            "parent": forms.Select(attrs={"class": "form-control"}),
        }

        labels = {
            "name": "Folder Name",
            "parent": "Parent Folder",
            "ai_library": "Include in AI Library",
        }

    def __init__(self, *args, exclude_folder=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = True
        self.fields["parent"].required = False
        self.fields["parent"].empty_label = "— None (root level) —"
        self.fields["ai_library"].widget = forms.Select(
            choices=self.YESNO_CHOICES, attrs={"class": "form-control"}
        )

        qs = NoteFolder.objects.filter(depth__lt=3).order_by("name")
        if exclude_folder and exclude_folder.pk:
            descendant_ids = [d.pk for d in exclude_folder.get_descendants()]
            exclude_ids = [exclude_folder.pk] + descendant_ids
            qs = qs.exclude(pk__in=exclude_ids)
        self.fields["parent"].queryset = qs

        # Indent choices to show hierarchy
        choices = [("", self.fields["parent"].empty_label)]
        for folder in qs:
            indent = "\u00a0\u00a0\u00a0\u00a0" * folder.depth
            choices.append((folder.pk, f"{indent}{folder.name}"))
        self.fields["parent"].choices = choices


class NoteFolderMoveForm(forms.Form):
    destination = forms.ModelChoiceField(
        queryset=NoteFolder.objects.none(),
        required=False,
        empty_label="Root level",
        widget=forms.RadioSelect,
    )
