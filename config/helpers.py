from datetime import datetime, timezone

import django_filters
import pytz
from django.db.models import Model
from django.db.models.query import F, QuerySet
from django.forms.models import model_to_dict
from django.http import JsonResponse


def dump_model(instance):
    """Convert a django model to to dict."""
    instance = model_to_dict(instance)
    return instance


def dump_set(queryset):
    """Convert a query set to a list of dicts."""
    my_list = []
    for instance in queryset:
        instance = model_to_dict(instance)
        my_list.append(instance)
    return my_list


def dump(result):
    """Dump a variable to the browser."""
    if issubclass(type(result), Model):
        result = dump_model(result)
    elif isinstance(result, QuerySet):
        result = dump_set(result)
    elif type(result) is dict or list or str or float or int:
        result = result
    else:
        result = "Input must be a a model instance, queryset, dict, string, int, list, or float."
    return JsonResponse(result, safe=False)


def timestamp_to_eastern(timestamp):
    dt = datetime.fromtimestamp(timestamp)
    dt = dt.replace(tzinfo=timezone.utc)
    tz = pytz.timezone("US/Eastern")
    dt = dt.astimezone(tz)
    return dt


def dictfetchall(cursor):
    """Returns all rows from a cursor as a dict"""
    # This is currently necessary for the trust app.
    desc = cursor.description
    return [dict(zip([col[0] for col in desc], row)) for row in cursor.fetchall()]


def format_phone(original):
    if original:
        new = (
            original.replace(" ", "")
            .replace("-", "")
            .replace(".", "")
            .replace("(", "")
            .replace(")", "")
        )
        if new.isnumeric() and len(new) == 10:
            # return f'({new[:3]}) {new[3:6]}-{new[6:]}'
            return f"{new[:3]}.{new[3:6]}.{new[6:]}"
        else:
            return original


class MultipleOrderingFilter(django_filters.OrderingFilter):

    # Override the default filter method to handle multiple fields
    def filter(self, qs, value):

        # If no ordering is provided, return the original queryset
        if value in (None, ""):
            return qs

        ordering = []

        # Iterate over the ordering parameteres
        for param in value:

            # Fetch the field from the mapping, and reverse the order if necessary
            fields = self.param_map[param.removeprefix("-")]

            # If fields is not a list or a tuple, convert it to a list
            if not isinstance(fields, (list, tuple)):
                fields = [fields]

            # Add the fields to the ordering list
            for field in fields:

                # If the field is a string, convert it to an F object so we can use the desc() method on it
                if isinstance(field, str):
                    field = F(field)

                # Append the field to the ordering list
                # If the parameter starts with a "-", use descending order, otherwise use ascending order
                ordering.append(field.desc() if param.startswith("-") else field)

        # Return the queryset with the ordering applied
        return qs.order_by(*ordering)
