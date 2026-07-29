"""Public, tokenized intake-form URLs — no login.

Deliberately mounted at /form/ rather than under /intakes/: PermissionMiddleware
gates that prefix on perm_intakes, and this page is for someone who has no
account at all.
"""

from django.urls import path

from apps.intakes.client_forms.public_views import form_page, form_save, form_submit

app_name = "intake_forms"

urlpatterns = [
    path("form/<str:token>/", form_page, name="fill"),
    path("form/<str:token>/save/", form_save, name="save"),
    path("form/<str:token>/submit/", form_submit, name="submit"),
]
