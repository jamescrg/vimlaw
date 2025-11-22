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


@register.filter("phone_tel")
def phone_tel(original):
    """Format phone number for tel: protocol."""
    if original:
        # Strip all special characters
        new = (
            original.replace(" ", "")
            .replace("-", "")
            .replace(".", "")
            .replace("(", "")
            .replace(")", "")
            .replace("+", "")
        )

        # Check if it's a valid 10 or 11 digit number
        if new.isnumeric():
            if len(new) == 10:
                # 10 digit number - add +1 prefix for US
                return f"+1{new}"
            elif len(new) == 11 and new.startswith("1"):
                # 11 digit number starting with 1 - add + prefix
                return f"+{new}"

        # If not valid, return just digits (fallback)
        return new if new else original
    else:
        return ""
