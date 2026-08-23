from django import forms

from config.settings import CustomFormRendererCompact

from .models import Note, NoteFolder


class NoteForm(forms.ModelForm):
    """Notes-tab rename modal: the title is the file name, so it stays
    unique among siblings (checked in the view against the note's own
    folder, case-insensitively)."""

    default_renderer = CustomFormRendererCompact

    class Meta:
        model = Note
        fields = ["title"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "span2"}),
        }


class NoteFolderForm(forms.ModelForm):
    class Meta:
        model = NoteFolder
        fields = ["name", "parent"]

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
        }

    def __init__(self, *args, exclude_folder=None, matter=None, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            matter = self.instance.matter  # edits never change scope
        else:
            # Stamp before validation: the ModelForm's _post_clean runs the
            # model's full_clean (matter-homogeneity check) pre-save
            self.instance.matter = matter
        self.matter = matter
        self.fields["name"].required = True
        self.fields["parent"].required = False
        self.fields["parent"].empty_label = "— None (root level) —"

        qs = NoteFolder.objects.filter(depth__lt=3, matter=matter).order_by("name")
        if exclude_folder and exclude_folder.pk:
            descendant_ids = [d.pk for d in exclude_folder.get_descendants()]
            exclude_ids = [exclude_folder.pk] + descendant_ids
            qs = qs.exclude(pk__in=exclude_ids)
        self.fields["parent"].queryset = qs

        # Indent choices to show hierarchy
        choices = [("", self.fields["parent"].empty_label)]
        for folder in qs:
            indent = "    " * folder.depth
            choices.append((folder.pk, f"{indent}{folder.name}"))
        self.fields["parent"].choices = choices

    def clean(self):
        # Sibling names are unique (case-insensitive) — the folder/file
        # metaphor must survive a filesystem export
        cleaned = super().clean()
        name = cleaned.get("name")
        parent = cleaned.get("parent")
        if name:
            clash = NoteFolder.objects.filter(
                matter=self.matter, parent=parent, name__iexact=name
            )
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error("name", f'A folder named "{name}" already exists here.')
        return cleaned


class NoteFolderMoveForm(forms.Form):
    destination = forms.ModelChoiceField(
        queryset=NoteFolder.objects.none(),
        required=False,
        empty_label="Root level",
        widget=forms.RadioSelect,
    )
