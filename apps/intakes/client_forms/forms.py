from django import forms

from apps.intakes.client_forms.models import FormTemplate
from config.settings import CustomFormRendererCompact


class FormTemplateForm(forms.ModelForm):
    """Everything about a form except its questions — those are the builder's."""

    class Meta:
        model = FormTemplate
        fields = ("name", "description", "intro_text", "is_active")

        YESNO_CHOICES = (
            (True, "Yes"),
            (False, "No"),
        )

        widgets = {
            "name": forms.TextInput(attrs={"class": "span2"}),
            "description": forms.TextInput(attrs={"class": "span2"}),
            "intro_text": forms.Textarea(attrs={"class": "span2", "rows": 4}),
            "is_active": forms.Select(choices=YESNO_CHOICES),
        }

        labels = {
            "description": "Description (staff only)",
            "intro_text": "Introduction shown to the client",
            "is_active": "Available to send",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
        # The builder's toolbar owns the name of an existing form. Offering it
        # here too would let a rename in one place be silently overwritten by a
        # stale value posted from the other.
        if self.instance.pk:
            del self.fields["name"]


class SendFormForm(forms.Form):
    """Pick a form and say where it goes. Not a ModelForm — the submission it
    creates is assembled in the view, around a snapshot of the template."""

    template = forms.ModelChoiceField(
        queryset=FormTemplate.objects.none(),
        label="Form",
        empty_label="Choose a form…",
    )
    to = forms.CharField(
        label="To", required=False, widget=forms.TextInput(attrs={"class": "span2"})
    )
    cc = forms.CharField(
        label="Cc", required=False, widget=forms.TextInput(attrs={"class": "span2"})
    )
    message = forms.CharField(
        label="Message (optional)",
        required=False,
        widget=forms.Textarea(attrs={"class": "span2", "rows": 4, "maxlength": 500}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
        # Only forms that are switched on and actually ask something. Sending
        # an empty form wastes the one chance to ask.
        self.fields["template"].queryset = FormTemplate.objects.filter(is_active=True)

    def clean_template(self):
        template = self.cleaned_data["template"]
        if template.question_count == 0:
            raise forms.ValidationError(
                "This form has no questions yet. Add some in the builder first."
            )
        return template


class ResendFormForm(forms.Form):
    """Send an existing submission's link again. The form itself is already
    chosen and snapshotted, so only the addressing is up for grabs."""

    to = forms.CharField(
        label="To", required=False, widget=forms.TextInput(attrs={"class": "span2"})
    )
    cc = forms.CharField(
        label="Cc", required=False, widget=forms.TextInput(attrs={"class": "span2"})
    )
    message = forms.CharField(
        label="Message (optional)",
        required=False,
        widget=forms.Textarea(attrs={"class": "span2", "rows": 4, "maxlength": 500}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
