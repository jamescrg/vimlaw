from django import forms

from .models import Folder


class FolderForm(forms.ModelForm):
    class Meta:
        model = Folder
        fields = ["name"]

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Folder name",
                    "autofocus": True,
                    "onfocus": "moveFocusToEnd(this)",
                }
            ),
        }

        labels = {
            "name": "Folder Name",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = True
