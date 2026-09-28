from django.core.cache import cache

ENTITLEMENT_CACHE_TTL = 300  # 5 minutes


def entitlement_cache_key(company_id):
    return f"subscription:entitlements:{company_id}"


def get_cached_entitlements(company_id):
    return cache.get(entitlement_cache_key(company_id))


def set_cached_entitlements(company_id, payload):
    cache.set(entitlement_cache_key(company_id), payload, ENTITLEMENT_CACHE_TTL)


def invalidate_entitlement_cache(company_id):
    if company_id:
        cache.delete(entitlement_cache_key(company_id))
