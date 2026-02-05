import django_filters

from apps.invoicing.invoices.models import INVOICE_STATUS, Invoice
from apps.matters.models import Matter
from config.helpers import MultipleOrderingFilter


class InvoiceFilter(django_filters.FilterSet):
    matter = django_filters.ModelChoiceFilter(
        queryset=Matter.objects.filter(invoice__isnull=False)
        .exclude(status__in=["Pending", "Closed"])
        .distinct()
        .order_by("name"),
        empty_label="All",
    )
    status = django_filters.ChoiceFilter(choices=INVOICE_STATUS, empty_label="All")
    date_issued = django_filters.DateFromToRangeFilter(
        widget=django_filters.widgets.RangeWidget(attrs={"type": "date"})
    )
    order_by = MultipleOrderingFilter(
        fields=[
            (("date_issued", "id"), "date_issued"),
            ("matter__name", "matter"),
            ("status", "status"),
            ("annotated_final_total", "total"),
            ("annotated_amount_remaining", "amount_due"),
        ],
        empty_label=None,
    )

    class Meta:
        model = Invoice
        fields = ["matter", "status", "date_issued"]
