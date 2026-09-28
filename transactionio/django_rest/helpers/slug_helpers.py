def get_transaction_information_slug(instance):
    return f"transaction-{str(instance.uid).split('-')[0]}"


def get_transaction_method_slug(instance):
    return f"transaction-{str(instance.uid).split('-')[0]}"


def trx_rule_slug(instance):
    return f"trx-rule-{str(instance.uid).split('-')[0]}"


def rule_params_slug(instance):
    return f"rule-params-{str(instance.uid).split('-')[0]}"


def rule_assign_slug(instance):
    return f"rule-assign-{str(instance.uid).split('-')[0]}"


def get_bank_deposit_slug(instance):
    return f"bank-deposit-{str(instance.uid).split('-')[0]}"


def get_bank_deposit_item_slug(instance):
    return f"deposit-item-{str(instance.uid).split('-')[0]}"


def get_bank_reconcile_slug(instance):
    return f"bank-reconcile-{str(instance.uid).split('-')[0]}"