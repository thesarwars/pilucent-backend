from django.urls import path

from weapi.django_rest.views.nexus import (
    PrivateWeNexusAlertAcknowledgeView,
    PrivateWeNexusAlertListView,
    PrivateWeNexusDashboardView,
    PrivateWeNexusMarkNexusView,
    PrivateWeNexusSettingsView,
    PrivateWeNexusStartAgencySetupView,
    PrivateWeNexusStateDetailView,
    PrivateWeNexusRecalculateView,
)

urlpatterns = [
    path(
        r"/dashboard",
        PrivateWeNexusDashboardView.as_view(),
        name="weapi.nexus.dashboard",
    ),
    path(
        r"/recalculate",
        PrivateWeNexusRecalculateView.as_view(),
        name="weapi.nexus.recalculate",
    ),
    path(
        r"/settings",
        PrivateWeNexusSettingsView.as_view(),
        name="weapi.nexus.settings",
    ),
    path(
        r"/alerts/<uuid:uid>/acknowledge",
        PrivateWeNexusAlertAcknowledgeView.as_view(),
        name="weapi.nexus.alert-acknowledge",
    ),
    path(
        r"/alerts",
        PrivateWeNexusAlertListView.as_view(),
        name="weapi.nexus.alerts",
    ),
    path(
        r"/state/<str:state_code>/mark-nexus",
        PrivateWeNexusMarkNexusView.as_view(),
        name="weapi.nexus.mark-nexus",
    ),
    path(
        r"/state/<str:state_code>/start-agency-setup",
        PrivateWeNexusStartAgencySetupView.as_view(),
        name="weapi.nexus.start-agency-setup",
    ),
    path(
        r"/state/<str:state_code>",
        PrivateWeNexusStateDetailView.as_view(),
        name="weapi.nexus.state-detail",
    ),
]
