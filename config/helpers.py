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


def normalize_phone(value):
    """
    Normalize phone to raw digits with optional extension.
    Returns (normalized_value, is_valid).

    Examples:
        "(406) 363-1234" -> ("4063631234", True)
        "1-406-363-1234" -> ("4063631234", True)
        "406.363.1234 x123" -> ("4063631234x123", True)
        "invalid" -> ("invalid", False)
    """
    if not value:
        return value, True

    value = value.strip()

    # Extract extension if present
    extension = ""
    ext_patterns = [" x", " ext", " ext.", ","]
    lower = value.lower()
    for pattern in ext_patterns:
        if pattern in lower:
            idx = lower.index(pattern)
            ext_part = value[idx:].lower()
            # Extract just the digits from extension
            ext_digits = "".join(c for c in ext_part if c.isdigit())
            if ext_digits:
                extension = f"x{ext_digits}"
            value = value[:idx]
            break

    # Strip all non-numeric characters
    digits = "".join(c for c in value if c.isdigit())

    # Handle +1 country code
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    # Validate: must be exactly 10 digits
    if len(digits) == 10:
        return digits + extension, True

    # Invalid - return original
    return value.strip() + (" " + extension if extension else ""), False


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
