from django.urls import path

from apps.lab.views import email_test, index, results

urlpatterns = [
    path("lab/", index, name="lab"),
    path("lab/results", results, name="lab-results"),
    path("lab/email", email_test, name="email-test"),
]
