from django.urls import path

from ..views import bd_paylib as v

# Components & structures (docs/backend/components-n-structures-backend-done.md §6).
urlpatterns = [
    path(r"/summary", v.LibSummary.as_view(), name="weapi.bd-paylib-summary"),
    path(r"/components", v.LibComponents.as_view(), name="weapi.bd-paylib-components"),
    path(r"/components/<uuid:uid>", v.LibComponent.as_view(), name="weapi.bd-paylib-component"),
    path(r"/components/<uuid:uid>/flags", v.LibComponentFlags.as_view(), name="weapi.bd-paylib-component-flags"),
    path(r"/components/<uuid:uid>/gl", v.LibComponentGl.as_view(), name="weapi.bd-paylib-component-gl"),
    path(r"/gl-accounts", v.LibGlAccounts.as_view(), name="weapi.bd-paylib-gl-accounts"),
    path(r"/readiness", v.LibReadiness.as_view(), name="weapi.bd-paylib-readiness"),
    path(r"/effects", v.LibEffects.as_view(), name="weapi.bd-paylib-effects"),
    path(r"/templates", v.LibTemplates.as_view(), name="weapi.bd-paylib-templates"),
    path(r"/templates/<uuid:uid>", v.LibTemplate.as_view(), name="weapi.bd-paylib-template"),
    path(r"/templates/<uuid:uid>/preview", v.LibTemplatePreview.as_view(), name="weapi.bd-paylib-template-preview"),
    path(r"/templates/<uuid:uid>/<str:action>", v.LibTemplateAction.as_view(), name="weapi.bd-paylib-template-action"),
    path(r"/floors", v.LibFloors.as_view(), name="weapi.bd-paylib-floors"),
    path(r"/bulk-revisions", v.LibBulk.as_view(), name="weapi.bd-paylib-bulk"),
    path(r"/bulk-revisions/<uuid:uid>", v.LibBulkOne.as_view(), name="weapi.bd-paylib-bulk-one"),
    path(r"/bulk-revisions/<uuid:uid>/<str:action>", v.LibBulkAction.as_view(), name="weapi.bd-paylib-bulk-action"),
    path(r"/audit", v.LibAudit.as_view(), name="weapi.bd-paylib-audit"),
]
