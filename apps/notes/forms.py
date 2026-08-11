from django import forms

from .models import NoteFolder


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
        if matter is not None:
            # Matter folders can never join the firm AI library
            del self.fields["ai_library"]
        else:
            self.fields["ai_library"].widget = forms.Select(
                choices=self.YESNO_CHOICES, attrs={"class": "form-control"}
            )

        qs = NoteFolder.objects.filter(depth__lt=3, matter=matter).order_by("name")
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
