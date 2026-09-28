from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard.envelope import build_card
from weapi.django_rest.helpers.dashboard.permissions import company_has_feature


# Static tile configuration. Each tile may require a subscription feature; when
# the company lacks the feature the tile is omitted. There is no per-user
# personalization model, so this is a role/feature-driven default set.
_QUICK_ACTIONS = [
    {"key": "create_invoice", "label": "Create Invoice", "action_route": "/sales/invoices/new", "feature": None},
    {"key": "record_expense", "label": "Record Expense", "action_route": "/purchases/expenses/new", "feature": None},
    {"key": "add_customer", "label": "Add Customer", "action_route": "/sales/customers/new", "feature": None},
    {"key": "add_product", "label": "Add Product", "action_route": "/inventory/products/new", "feature": None},
    {"key": "run_payroll", "label": "Run Payroll", "action_route": "/payroll/runs/new", "feature": "is_payroll"},
    {"key": "file_tax", "label": "File Tax", "action_route": "/tax-center", "feature": "is_agency_tax"},
]


class PrivateWeDashboardQuickActionsView(DashboardCardView):
    """Card 26 — Quick Actions (static role/feature-based tile config)."""

    card_key = "quick_actions"
    action_route = "/dashboard"

    def get_card_data(self, request, filters):
        tiles = [
            {k: v for k, v in action.items() if k != "feature"}
            for action in _QUICK_ACTIONS
            if company_has_feature(request.user, action["feature"])
        ]
        return build_card(
            self.card_key,
            value=len(tiles),
            list_items=tiles,
            action_route=self.action_route,
        )
