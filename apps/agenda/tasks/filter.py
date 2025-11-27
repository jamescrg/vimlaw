import django_filters
from django.db.models import F, Q

from apps.accounts.models import CustomUser
from apps.agenda.tasks.models import Task
from apps.matters.models import Matter

STATUS_CHOICES = (
    ("Pending", "Pending"),
    ("In Progress", "In Progress"),
    ("Complete", "Complete"),
)


class DateCompletedFilter(django_filters.DateFromToRangeFilter):
    """Custom filter for date_completed that includes null values when no max date is set."""

    def filter(self, qs, value):
        if value:
            date_after = value.start
            date_before = value.stop

            if date_after and date_before:
                # Both dates set - standard range filter, exclude nulls
                return qs.filter(
                    date_completed__gte=date_after, date_completed__lte=date_before
                )
            elif date_after and not date_before:
                # Only "after" date set - include nulls (incomplete tasks)
                return qs.filter(
                    Q(date_completed__gte=date_after) | Q(date_completed__isnull=True)
                )
            elif date_before and not date_after:
                # Only "before" date set - exclude nulls
                return qs.filter(date_completed__lte=date_before)

        return qs


class TasksOrderingFilter(django_filters.OrderingFilter):
    def filter(self, qs, value):
        if value in (None, ""):
            return qs
        ordering = [self.get_ordering_value(param) for param in value]
        try:
            if ordering[0] == "date_due":
                return qs.order_by(
                    F("date_due").asc(nulls_first=True),
                    "priority",
                    "matter__name",
                    "description",
                    "id",
                )
            if ordering[0] == "priority":
                return qs.order_by(
                    "-status",
                    "priority",
                    "matter__name",
                    "description",
                    "id",
                )
            return qs.order_by("-status", *ordering, "id")
        except IndexError:
            return qs.order_by("-status", *ordering, "id")


class TasksFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=STATUS_CHOICES, empty_label="All")
    date_due = django_filters.DateFromToRangeFilter(
        widget=django_filters.widgets.RangeWidget(attrs={"type": "date"})
    )
    date_completed = DateCompletedFilter(
        widget=django_filters.widgets.RangeWidget(attrs={"type": "date"})
    )
    matter = django_filters.ModelChoiceFilter(
        queryset=Matter.objects.filter(status__in=["Pending", "Open"]).order_by("name"),
        empty_label="All",
    )
    user = django_filters.ModelChoiceFilter(
        queryset=CustomUser.objects.filter(is_active=True).order_by("username"),
        empty_label="All",
    )
    priority = django_filters.NumberFilter(
        field_name="priority",
        lookup_expr="lte",
        label="Priority (≤)",
    )

    order_by = TasksOrderingFilter(
        fields=(
            ("date_due", "date_due"),
            ("priority", "priority"),
            ("matter__name", "matter__name"),
            ("description", "description"),
            ("status", "status"),
            ("user__username", "user__username"),
        ),
    )

    class Meta:
        model = Task
        fields = [
            "status",
            "priority",
            "matter",
            "user",
            "date_due",
            "date_completed",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Customize user field to show title case usernames
        self.filters["user"].field.label_from_instance = (
            lambda obj: obj.username.title()
        )
