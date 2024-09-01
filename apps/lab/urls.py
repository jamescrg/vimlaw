from django.urls import path

from apps.lab.views import email_test, index, results

app_name = "lab"

# fmt: on
urlpatterns = [
    path("lab/", index, name="lab"),
    path("lab/results", results, name="results"),
    path("lab/email", email_test, name="email-test"),
]
# fmt: off
