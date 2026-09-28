from journalio.models import JournalEntryConnector
from datetime import date, timedelta
from decimal import Decimal

def get_transaction_match_details(transaction):
    """
    Get detailed information about transaction matches.
    Optimized to filter by company for better performance.

    Args:
        transaction: TransactionInformation instance

    Returns:
        Dictionary with match details including:
        - matched_items: List of matched journal entries
        - match_count: Number of matches
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=30)

    # Get the company from the transaction
    company = transaction.company

    # Get journal entry connectors in date range filtered by company
    journal_connectors = JournalEntryConnector.objects.filter(
        date__range=(start_date, end_date),
        journal__company=company,
    ).select_related("journal", "account")

    matched_items = []

    for connector in journal_connectors:
        match_info = None

        # Match received amount with debit
        if (
            transaction.received
            and connector.debit
            and abs(Decimal(str(transaction.received)) - connector.debit)
            < Decimal("0.01")
        ):
            match_info = {
                "journal_entry_uid": str(connector.journal.uid),
                "connector_uid": str(connector.uid),
                "account_name": connector.account.title if connector.account else None,
                "amount": float(connector.debit),
                "match_type": "received_to_debit",
                "date": connector.date.isoformat(),
                "description": connector.description or connector.journal.description,
            }

        # Match spent amount with credit
        elif (
            transaction.spent
            and connector.credit
            and abs(Decimal(str(transaction.spent)) - connector.credit)
            < Decimal("0.01")
        ):
            match_info = {
                "journal_entry_uid": str(connector.journal.uid),
                "connector_uid": str(connector.uid),
                "account_name": connector.account.title if connector.account else None,
                "amount": float(connector.credit),
                "match_type": "spent_to_credit",
                "date": connector.date.isoformat(),
                "description": connector.description or connector.journal.description,
            }

        if match_info:
            matched_items.append(match_info)

    return {
        "matched_items": matched_items,
        "match_count": len(matched_items),
    }
