from django.db import models

class RequestTypeChoices(models.TextChoices):
    LIVE_DEMO = "LIVE_DEMO", "Live Demo"
    ACCOUNTANT_SERVICE = "ACCOUNTANT_SERVICE", "Accountant Service"