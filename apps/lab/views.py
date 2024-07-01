from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render


@login_required
def index(request):
    return HttpResponse("this is the response 11:20")


@login_required
def results(request):
    weather = request.POST.get("weather")
    # context = {
    #     'page': 'lab',
    # }

    response = HttpResponse(f"Content is {weather}")
    # return render(request, 'lab/content.html', context)
    return response


@login_required
def email_test(request):
    """Test whether I can send an email"""
    from django.core.mail import send_mail

    # from config import settings_local

    send_mail(
        "Test Message",
        "This is the message body.",
        # settings_local.SERVER_EMAIL,
        # settings_local.TEST_EMAIL_RECIPIENT,
        fail_silently=False,
    )

    context = {
        "page": "lab",
        "text": "This is some text.",
    }
    return render(request, "lab/content.html", context)
