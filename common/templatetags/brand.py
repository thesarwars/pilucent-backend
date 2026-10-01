"""Brand values for templates, from settings -- so an email never hardcodes a
domain, address or logo URL (master/settings.py, "Brand and public endpoints").

    {% load brand %}
    <img src="{% brand "BRAND_LOGO_URL" %}">  <a href="mailto:{% brand "SUPPORT_EMAIL" %}">
"""

from django import template
from django.conf import settings

register = template.Library()

ALLOWED = {
    "PRODUCT_NAME", "APP_URL", "PUBLIC_API_URL", "SELF_SERVICE_URL",
    "SUPPORT_EMAIL", "BRAND_LOGO_URL", "BRAND_ICON_URL",
}


@register.simple_tag
def brand(key):
    if key not in ALLOWED:
        raise template.TemplateSyntaxError(f"brand: unknown key {key!r}")
    return getattr(settings, key)
