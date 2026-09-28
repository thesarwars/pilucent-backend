from django.db import models


class CustomerStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    PENDING = "PENDING", "Pending"
    # Retired from data entry, kept in the books. The product spec lists
    # "Mark Customer as Inactive" as a customer action and expects the list to
    # offer an "include inactive customers" toggle, and neither existed --
    # delete was the only way to retire a customer, which is what made the
    # ledger-destroying `perform_destroy` reachable in the first place.
    #
    # NOT the same as REMOVED, and deliberately weaker than the account version:
    # an inactive customer keeps their balance in A/R and still appears on the
    # ageing report. Retiring them is a master-data change with no accounting
    # consequence -- see CUSTOMER_INDUSTRY_STANDARD.md section 4.
    INACTIVE = "INACTIVE", "Inactive"
    REMOVED = "REMOVED", "Removed"

class CustomerPaymentMethodChoices(models.TextChoices):
    CASH = "CASH", "Cash"
    CHEQUE = "CHEQUE", "Cheque"
    CREDIT_CARD = "CREDIT_CARD", "Credit Card"
    DIRECT_DEBIT = "DIRECT_DEBIT", "Direct Card"


class CustomerDeliveryOptionChoices(models.TextChoices):
    PRINT_LATTER = "PRINT_LATTER", "Print Latter"
    SEND_LETTER = "SEND_LETTER", "Send Latter"
    COMPANY_DEFAULT = "COMPANY_DEFAULT", "Company Default"
