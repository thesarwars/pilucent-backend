import random, logging

from django.db.models import Q

logger = logging.getLogger(__name__)


def get_unique_id(model_class, company_id, field_name, label=None):
    unique_id = random.randint(0, 999999)
    instance = model_class.objects.filter(Q(**{field_name: unique_id})).exists()
    if instance:
        unique_id = get_unique_id(model_class, company_id, field_name, label=None)

    return (
        f"#{label}-{unique_id:06d}{company_id}"
        if label
        else f"#{unique_id:06d}{company_id}"
    )
