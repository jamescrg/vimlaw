from django import template

register = template.Library()


@register.filter
def contrast_color(hex_color):
    """
    Calculate the contrast color (black or white) for a given hex color.
    """
    if not hex_color:
        return "black"

    # Remove '#' if present
    hex_color = hex_color.lstrip("#")

    if len(hex_color) != 6:
        return "black"

    try:
        # Convert to RGB
        red = int(hex_color[0:2], 16)
        green = int(hex_color[2:4], 16)
        blue = int(hex_color[4:6], 16)

        # Calculate luminance
        luminance = ((0.299 * red) + (0.587 * green) + (0.114 * blue)) / 255

        return "black" if luminance > 0.5 else "white"
    except ValueError:
        return "black"
