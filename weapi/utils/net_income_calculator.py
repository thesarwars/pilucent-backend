from collections import defaultdict
from decimal import Decimal
from django.db.models import Sum, Q

from accounts.models import ChartOfAccount
from accounts.choices import ChartOfAccountKindChoices
from journalio.models import JournalEntry, JournalEntryConnector


class NetIncomeCalculator:
    """
    A utility class to calculate net income for a company
    by analyzing income and expense accounts.
    """

    def __init__(self, company):
        self.company = company

    def calculate_net_income(self, start_date=None, end_date=None):
        """
        Calculate net income using aggregation queries similar to profit/loss reports

        Args:
            start_date (datetime, optional): Start date for the calculation period
            end_date (datetime, optional): End date for the calculation period

        Returns:
            dict: A dictionary containing net income data
        """
        if not self.company:
            return {
                "total_income": 0,
                "total_expenses": 0,
                "net_income": 0,
            }

        # Create base queryset with date filtering if applicable
        queryset = ChartOfAccount.objects.filter(company=self.company)

        # Apply date filters to related journal entries if dates are provided
        journal_filters = {}
        if start_date:
            journal_filters["journalentryconnector__journal__date__gte"] = start_date
        if end_date:
            journal_filters["journalentryconnector__journal__date__lte"] = end_date

        if journal_filters:
            queryset = queryset.filter(**journal_filters)

        # Calculate financial metrics using Django's aggregation
        data = queryset.aggregate(
            total_income=Sum(
                "opening_balance",
                filter=Q(kind=ChartOfAccountKindChoices.INCOMES),
            ),
            total_expenses=Sum(
                "opening_balance",
                filter=Q(kind=ChartOfAccountKindChoices.EXPENSES),
            ),
        )

        # Handle None values from aggregation
        data["total_income"] = data["total_income"] or 0
        data["total_expenses"] = data["total_expenses"] or 0

        # Calculate net income directly
        data["net_income"] = data["total_income"] - data["total_expenses"]

        return data
