from django import forms

from .models import Transaction


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction

        fields = (
            "date",
            "type",
            "description",
            "amount",
            "entered",
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
            "description": forms.TextInput(attrs={"autofocus": "autofocus"}),
            "entered": forms.Select(choices=ENTERED_CHOICES),
            "confirmed": forms.Select(choices=CONFIRMED_CHOICES),
        }
