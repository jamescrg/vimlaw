import django_filters
from django.db import models

from apps.documents.models import Document, Label
from apps.matters.models import Matter


class DocumentsFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains", label="Name")
    matter = django_filters.ModelChoiceFilter(
        queryset=Matter.objects.filter(documents__isnull=False)
        .distinct()
        .order_by("name"),
        empty_label="All",
    )
    label = django_filters.ModelChoiceFilter(
        queryset=Label.objects.filter(documents__isnull=False)
        .distinct()
        .order_by("name"),
        empty_label="All",
        field_name="labels",
    )
    order_by = django_filters.OrderingFilter(
        fields=[
            ("name", "name"),
            ("matter__name", "matter"),
            ("uploaded_by__first_name", "uploaded_by"),
            ("uploaded_at", "uploaded_at"),
            ("date", "date"),
        ]
    )
    keyword = django_filters.CharFilter(method="filter_by_keyword", label="Keyword")

    def filter_by_keyword(self, queryset, name, value):
        return queryset.filter(
            models.Q(name__icontains=value)
            | models.Q(description__icontains=value)
            | models.Q(matter__name__icontains=value)
        )

    class Meta:
        model = Document
        fields = ["name", "matter", "label", "order_by", "keyword"]


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
