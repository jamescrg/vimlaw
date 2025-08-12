from django import forms

from config.settings import CustomFormRendererCompact

from .models import Transaction


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = (
            "contact",
            "date",
            "type",
            "description",
            "amount",
            "confirmed",
        )

        TYPE_CHOICES = (
            ("Deposit", "Deposit"),
            ("Withdrawal", "Withdrawal"),
        )

        ENTERED_CHOICES = (
            (0, "No"),
            (1, "Yes"),
        )

        CONFIRMED_CHOICES = (
            (0, "No"),
            (1, "Yes"),
        )

        widgets = {
            "contact": forms.Select(attrs={"class": "span2"}),
            "date": forms.DateInput(attrs={"type": "date"}),
            "type": forms.Select(choices=TYPE_CHOICES),
            "description": forms.Textarea(
                attrs={
                    "autofocus": "autofocus",
                    "onfocus": "moveFocusToEnd(this)",
                    "class": "span2",
                    "rows": 3,
                }
            ),
            "amount": forms.TextInput(),
            "confirmed": forms.Select(choices=CONFIRMED_CHOICES),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()

        self.fields["contact"].label = "Client"
