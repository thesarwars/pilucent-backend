from salesio.choices import SaleReceptKindChoices


def get_sale_document_type(sale):
    if sale.is_estimated:
        return "estimate"
    if sale.is_invoice:
        return "invoice"
    if sale.is_sale_receipt and sale.kind == SaleReceptKindChoices.REFUND:
        return "refund_receipt"
    if sale.is_sale_receipt:
        return "sale_receipt"
    return "sale"


def document_matches_search(document, search_term):
    customer = document.get("customer") or {}
    searchable = " ".join(
        str(value)
        for value in [
            document.get("sale_type"),
            document.get("tracking_number"),
            document.get("invoice_id"),
            document.get("reference_number"),
            document.get("credit_note_number"),
            customer.get("display_name"),
            customer.get("email"),
            customer.get("first_name"),
            customer.get("last_name"),
            customer.get("company_name"),
        ]
        if value
    )
    return search_term in searchable.lower()
