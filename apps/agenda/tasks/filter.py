import django_filters

from apps.accounts.models import CustomUser
from apps.agenda.tasks.models import Task
from apps.matters.models import Matter

STATUS_CHOICES = (
    ("Pending", "Pending"),
    ("Complete", "Complete"),
)


class TasksOrderingFilter(django_filters.OrderingFilter):

    def filter(self, qs, value):
        if value in (None, ""):
            return qs

        ordering = [self.get_ordering_value(param) for param in value]
        return qs.order_by("-status", *ordering)


class TasksFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=STATUS_CHOICES, empty_label="All")
    date_due = django_filters.DateFromToRangeFilter(
        widget=django_filters.widgets.RangeWidget(attrs={"type": "date"})
    )
    matter = django_filters.ModelChoiceFilter(
        queryset=Matter.objects.filter(status="Open").order_by("name"),
        empty_label="All",
    )
    user = django_filters.ModelChoiceFilter(
        queryset=CustomUser.objects.all(), empty_label="All"
    )

    order_by = TasksOrderingFilter(
        fields=(
            ("status", "status"),
            ("matter", "matter"),
            ("description", "description"),
            ("user", "user"),
            ("date_due", "date_due"),
            ("priority", "priority"),
        ),
    )

    class Meta:
        model = Task
        fields = ["status", "date_due", "matter", "user"]
