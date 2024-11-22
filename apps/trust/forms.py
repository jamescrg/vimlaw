from django import forms

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
            "date": forms.DateInput(attrs={"type": "date"}),
            "type": forms.Select(choices=TYPE_CHOICES),
            "description": forms.TextInput(
                attrs={"autofocus": "autofocus", "onfocus": "moveFocusToEnd(this)"}
            ),
            "confirmed": forms.Select(choices=CONFIRMED_CHOICES),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["contact"].label = "Client"
