from django import forms

from apps.settings.models import Firm


class TasksSettingsForm(forms.ModelForm):
    """Firm-wide task entry behaviour (Settings > Tasks)."""

    # Typed coercion: the Select posts "True"/"False" strings, and
    # bool("False") is True — coerce compares instead. Not required so a
    # partial post reads as the safe default (off).
    quick_task_ai = forms.TypedChoiceField(
        coerce=lambda v: v in (True, "True"),
        choices=((False, "No"), (True, "Yes")),
        required=False,
        label="AI Quick Task Entry",
        help_text=(
            "Interpret the quick-add line with AI (matter, assignee, date, "
            'and priority from plain language). "No" uses the '
            '"Matter - Description" prefix matcher.'
        ),
    )

    class Meta:
        model = Firm
        fields = ["quick_task_ai", "quick_task_ai_model"]
        labels = {
            "quick_task_ai_model": "Quick Task AI Model",
        }
        help_texts = {
            "quick_task_ai_model": (
                "Used only when AI quick task entry is on; the provider's "
                "API key must be configured."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Optional so a partial post keeps the model default (see clean_*).
        self.fields["quick_task_ai_model"].required = False

    def clean_quick_task_ai(self):
        # required=False yields "" for an absent field; coerce that to off.
        return self.cleaned_data.get("quick_task_ai") or False

    def clean_quick_task_ai_model(self):
        return self.cleaned_data.get("quick_task_ai_model") or "gemini-flash"
