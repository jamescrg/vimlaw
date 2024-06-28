from django import template

register = template.Library()


@register.filter("phone_number")
def phone_number(original):
    if original:
        new = (
            original.replace(" ", "")
            .replace("-", "")
            .replace(".", "")
            .replace("(", "")
            .replace(")", "")
        )
        if new.isnumeric() and len(new) == 10:
            return f"({new[:3]}) {new[3:6]}-{new[6:]}"
        else:
            return original
    else:
        return original
