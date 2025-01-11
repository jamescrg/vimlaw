from django import template

register = template.Library()


@register.filter("is_number")
def is_number(value):
    if type(value) is int or type(value) is float:
        return True

    elif type(value) is str:
        return value.isdigit()
