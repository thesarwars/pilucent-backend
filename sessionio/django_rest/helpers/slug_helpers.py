def get_transaction_session_slug(instance):
    return f"transaction-session-{str(instance.uid).split('-')[0]}"
