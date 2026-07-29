from django import forms

from apps.intakes.client_forms.models import FormTemplate
from config.settings import CustomFormRendererCompact


class FormTemplateForm(forms.ModelForm):
    """Everything about a form except its questions — those are the builder's."""

    class Meta:
        model = FormTemplate
        fields = ("name", "description", "intro_text")

        widgets = {
            "name": forms.TextInput(attrs={"class": "span2"}),
            "description": forms.TextInput(attrs={"class": "span2"}),
            "intro_text": forms.Textarea(attrs={"class": "span2", "rows": 4}),
        }

        labels = {
            "description": "Description (staff only)",
            "intro_text": "Caption shown to the client",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
        # Start from the standard caption rather than a blank box — the page
        # will show it either way, so the modal should show what will happen,
        # and editing a default beats composing from nothing.
        # Assigned, not setdefault: model_to_dict already seeded initial with
        # the instance's empty string, so a default would never take.
        if not self.initial.get("intro_text"):
            self.initial["intro_text"] = FormTemplate.DEFAULT_CAPTION


class AddFormForm(forms.Form):
    """Step one of two: which form to prepare for this intake. Sending is a
    separate step, so nothing about delivery is asked here."""

    # No empty option: the modal is one choice and one button, so the first
    # form is preselected and a plain Add works. The select carries an
    # aria-label because the modal shows no visible one.
    template = forms.ModelChoiceField(
        queryset=FormTemplate.objects.none(),
        empty_label=None,
        widget=forms.Select(attrs={"aria-label": "Form"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
        # Every form is available — is_active is retired (the column stays,
        # unread, until a cleanup migration).
        self.fields["template"].queryset = FormTemplate.objects.all()

    def clean_template(self):
        template = self.cleaned_data["template"]
        if template.question_count == 0:
            raise forms.ValidationError(
                "This form has no questions yet. Add some in the builder first."
            )
        return template


class SendFormForm(forms.Form):
    """Step two: where an already-created form goes."""

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


# A reminder asks for exactly the same three things as the first send; the
# views differ, the questions don't.
ResendFormForm = SendFormForm
