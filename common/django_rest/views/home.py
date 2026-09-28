from django.http import HttpResponse


def home_view(request):
    return HttpResponse(
        f"Hi {request.user.name if request.user.is_authenticated else ','} wellcome to the balanzify backend!"
    )
