import django_filters
from django import forms
from django.db.models import Q

from apps.documents.models import Document, Fact, Highlight, Label
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding


class ProceedingChoiceFilter(django_filters.ModelChoiceFilter):
    """Custom filter to display proceedings as 'Forum - Case Number'."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.field.label_from_instance = lambda obj: f"{obj.forum} - {obj.case_number}"


class DocumentsFilter(django_filters.FilterSet):
    # Keyword filter (used by inline search, not shown in filter form)
    keyword = django_filters.CharFilter(method="filter_keyword")
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
    importance = django_filters.NumberFilter(
        field_name="importance",
        lookup_expr="lte",
        label="Importance (≤)",
    )
    order_by = django_filters.OrderingFilter(
        fields=[
            ("name", "name"),
            ("uploaded_at", "uploaded_at"),
            ("date", "date"),
        ]
    )

    class Meta:
        model = Document
        fields = [
            "date_from",
            "date_to",
            "category",
            "proceeding",
            "importance",
            "order_by",
        ]

    def __init__(self, *args, matter=None, **kwargs):
        super().__init__(*args, **kwargs)
        if matter:
            self.filters["proceeding"].queryset = Proceeding.objects.filter(
                matter=matter
            ).order_by("forum", "case_number")

    def filter_keyword(self, queryset, name, value):
        """Filter documents by keyword in name or description."""
        if value:
            return queryset.filter(
                Q(name__icontains=value) | Q(description__icontains=value)
            )
        return queryset


class HighlightsFilter(django_filters.FilterSet):
    """Filter for highlights list."""

    document = django_filters.ModelChoiceFilter(
        queryset=Document.objects.none(),
        empty_label="All",
        label="Document",
    )
    keyword = django_filters.CharFilter(method="filter_keyword", label="Keyword")
    importance = django_filters.NumberFilter(
        field_name="importance",
        lookup_expr="lte",
        label="Importance (≤)",
    )
    order_by = django_filters.OrderingFilter(
        fields=[
            ("document__name", "document"),
            ("slug", "slug"),
        ],
        field_labels={
            "document__name": "Document",
            "slug": "Slug",
        },
        label="Order By",
    )

    class Meta:
        model = Highlight
        fields = ["document", "keyword", "importance", "order_by"]

    def __init__(self, *args, matter=None, **kwargs):
        super().__init__(*args, **kwargs)
        if matter:
            self.filters["document"].queryset = Document.objects.filter(
                matter=matter
            ).order_by("name")

    def filter_keyword(self, queryset, name, value):
        """Filter highlights by keyword in slug or text."""
        if value:
            return queryset.filter(Q(slug__icontains=value) | Q(text__icontains=value))
        return queryset


class LabelsFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains", label="Name")
    matter = django_filters.ModelChoiceFilter(
        queryset=Matter.objects.filter(labels__isnull=False)
        .distinct()
        .order_by("name"),
        empty_label="All",
    )
    order_by = django_filters.OrderingFilter(
        fields=[
            ("name", "name"),
            ("matter__name", "matter"),
        ]
    )

    class Meta:
        model = Label
        fields = ["name", "matter", "order_by"]


class TimelineFilter(django_filters.FilterSet):
    date_start = django_filters.DateFilter(
        field_name="date", lookup_expr="gte", label="Start Date"
    )
    date_end = django_filters.DateFilter(
        field_name="date", lookup_expr="lte", label="End Date"
    )
    keyword = django_filters.CharFilter(method="filter_keyword", label="Keyword")
    importance = django_filters.NumberFilter(
        field_name="importance",
        lookup_expr="lte",
        label="Importance (≤)",
    )

    class Meta:
        model = Fact
        fields = ["date_start", "date_end", "keyword", "importance"]

    def filter_keyword(self, queryset, name, value):
        if value:
            return queryset.filter(Q(description__icontains=value))
        return queryset
