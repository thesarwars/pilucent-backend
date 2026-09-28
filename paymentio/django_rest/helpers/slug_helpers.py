def get_payment_information_slug(instance):
    return f"payment-information-{instance.kind}-{str(instance.uid).split('-')[0]}"
