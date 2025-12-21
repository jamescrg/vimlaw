import django_filters
from django import forms
from django.db.models import Q

from apps.case.models import Document, Label
from apps.matters.proceedings.models import Proceeding

IMPORTANCE_CHOICES = tuple((i, f"Importance {i}") for i in range(1, 11))


class ProceedingChoiceFilter(django_filters.ModelChoiceFilter):
    """Custom filter to display proceedings as 'Forum - Case Number'."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.field.label_from_instance = lambda obj: f"{obj.forum} - {obj.case_number}"


class FilesFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(
        method="filter_keyword",
        label="Keyword",
    )
    date_from = django_filters.DateFilter(
        field_name="date",
        lookup_expr="gte",
        label="Date From",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = django_filters.DateFilter(
        field_name="date",
        lookup_expr="lte",
        label="Date To",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    category = django_filters.ChoiceFilter(
        choices=[("", "All")] + Document.CATEGORY_CHOICES,
        empty_label=None,
        label="Category",
    )
    proceeding = ProceedingChoiceFilter(
        queryset=Proceeding.objects.none(),
        empty_label="All",
        label="Proceeding",
    )
    label = django_filters.ModelChoiceFilter(
        method="filter_label",
        queryset=Label.objects.none(),
        empty_label="All Labels",
        label="Label",
    )
    importance = django_filters.ChoiceFilter(
        field_name="importance",
        choices=IMPORTANCE_CHOICES,
        lookup_expr="lte",
        label="Importance (≤)",
        empty_label="All",
    )
    order_by = django_filters.OrderingFilter(
        fields=[
            ("name", "name"),
            ("created_at", "created_at"),
            ("date", "date"),
            ("importance", "importance"),
        ],
        label="Order By",
    )

    class Meta:
        model = Document
        fields = [
            "keyword",
            "date_from",
            "date_to",
            "category",
            "proceeding",
            "label",
            "importance",
            "order_by",
        ]

    def __init__(self, *args, matter=None, **kwargs):
        super().__init__(*args, **kwargs)
        if matter:
            proceeding_qs = Proceeding.objects.filter(matter=matter).order_by(
                "forum", "case_number"
            )
            label_qs = Label.objects.filter(
                Q(matter=matter) | Q(matter__isnull=True)
            ).order_by("name")

            # Set on both filter and form field to ensure validation works
            self.filters["proceeding"].queryset = proceeding_qs
            self.filters["label"].queryset = label_qs
            self.form.fields["proceeding"].queryset = proceeding_qs
            self.form.fields["label"].queryset = label_qs

    def filter_keyword(self, queryset, name, value):
        """Filter documents by keyword in name or description."""
        if value:
            return queryset.filter(
                Q(name__icontains=value) | Q(description__icontains=value)
            )
        return queryset

    def filter_label(self, queryset, name, value):
        """Filter documents by label."""
        if value:
            return queryset.filter(labels=value)
        return queryset
