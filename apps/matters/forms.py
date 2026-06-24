from django import forms

from config.settings import CustomFormRendererCompact

from .models import Matter, PracticeArea


class MatterForm(forms.ModelForm):
    class Meta:
        model = Matter

        fields = (
            "status",
            "date_start",
            "client",
            "name",
            "description",
            "work_status",
            "practice_area",
            "jurisdiction",
            "billable",
            "billing_type",
            "flat_fee_amount",
            "deferred_fees",
        )

        STATUSES = (
            ("Pending", "Pending"),
            ("Open", "Open"),
            ("Complete", "Complete"),
            ("Closed", "Closed"),
        )

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "onfocus": "moveFocusToEnd(this)",
                    "class": "span2",
                }
            ),
            "description": forms.TextInput(
                attrs={
                    "class": "span2",
                }
            ),
            "work_status": forms.TextInput(
                attrs={
                    "class": "span2",
                }
            ),
            "status": forms.Select(
                choices=STATUSES,
            ),
            "client": forms.Select(
                attrs={
                    "class": "span2",
                }
            ),
            "date_start": forms.DateInput(attrs={"type": "date"}),
            "jurisdiction": forms.TextInput(
                attrs={
                    "class": "span2",
                }
            ),
            "billable": forms.Select(
                choices=((True, "Yes"), (False, "No (Administrative)")),
            ),
            "billing_type": forms.Select(
                attrs={"onchange": "toggleFlatFeeAmount()"},
            ),
            "flat_fee_amount": forms.NumberInput(
                attrs={"step": "0.01"},
            ),
            "deferred_fees": forms.Select(
                choices=((False, "No"), (True, "Yes")),
            ),
        }

        labels = {
            "date_start": "Open Date",
            "clio_matter_id": "Clio Matter",
            "client_reference_id": "Client Reference",
            "practice_area": "Practice Area",
            "billing_type": "Billing Type",
            "flat_fee_amount": "Flat Fee Amount",
            "deferred_fees": "Deferred Fee Arrangement",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()

        # client and work_status are nullable on the model, so don't force them
        # in the form — otherwise matters without them (e.g. administrative
        # matters with no client) can't be saved at all.
        self.fields["client"].required = False
        self.fields["work_status"].required = False

        # Validate server-side (as the add view already does) rather than via
        # the HTML5 `required` attribute. Otherwise the browser silently refuses
        # to submit the edit modal when a required field is empty or not
        # focusable, with no error shown to the user.
        self.use_required_attribute = False

        # Filter practice areas to only show active ones
        self.fields["practice_area"].queryset = PracticeArea.objects.filter(
            is_active=True
        )
