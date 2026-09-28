from decimal import Decimal, ROUND_DOWN


def get_formated_amount(amount):
    amount = Decimal(amount if amount else 0)
    amount = amount.quantize(Decimal("0.001"), rounding=ROUND_DOWN)
    return amount
