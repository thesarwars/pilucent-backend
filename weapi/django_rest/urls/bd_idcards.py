from django.urls import path

from ..views import bd_idcards as v

# ID cards (docs/backend/id-cards-done.md §5). The public verification and the
# signed media live under /api/v1/public.
urlpatterns = [
    path(r"/setup", v.IdSetup.as_view(), name="weapi.bd-idcards-setup"),
    path(r"/settings", v.IdSettings.as_view(), name="weapi.bd-idcards-settings"),
    path(r"/gallery", v.IdGallery.as_view(), name="weapi.bd-idcards-gallery"),
    path(r"/employees/<str:code>", v.IdEmployee.as_view(), name="weapi.bd-idcards-employee"),
    path(r"/employees/<str:code>/photo", v.IdPhoto.as_view(), name="weapi.bd-idcards-photo"),
    path(r"/employees/<str:code>/fields", v.IdFieldValues.as_view(), name="weapi.bd-idcards-field-values"),
    path(r"/assets/<uuid:uid>", v.IdAsset.as_view(), name="weapi.bd-idcards-asset"),
    path(r"/cards", v.IdCards.as_view(), name="weapi.bd-idcards-cards"),
    path(r"/cards/bulk", v.IdCardsBulk.as_view(), name="weapi.bd-idcards-cards-bulk"),
    path(r"/cards/<uuid:uid>", v.IdCard.as_view(), name="weapi.bd-idcards-card"),
    path(r"/cards/<uuid:uid>/<str:action>", v.IdCardAction.as_view(), name="weapi.bd-idcards-card-action"),
    path(r"/templates", v.IdTemplates.as_view(), name="weapi.bd-idcards-templates"),
    path(r"/templates/<uuid:uid>", v.IdTemplate.as_view(), name="weapi.bd-idcards-template"),
    path(r"/templates/<uuid:uid>/contexts", v.IdTemplateContexts.as_view(), name="weapi.bd-idcards-contexts"),
    path(r"/templates/<uuid:uid>/<str:action>", v.IdTemplateAction.as_view(),
         name="weapi.bd-idcards-template-action"),
    path(r"/rules", v.IdRules.as_view(), name="weapi.bd-idcards-rules"),
    path(r"/rules/<uuid:uid>", v.IdRule.as_view(), name="weapi.bd-idcards-rule"),
    path(r"/print-check", v.IdPrintCheck.as_view(), name="weapi.bd-idcards-print-check"),
    path(r"/print-jobs", v.IdPrintJobs.as_view(), name="weapi.bd-idcards-print-jobs"),
    path(r"/print-jobs/<uuid:uid>", v.IdPrintJob.as_view(), name="weapi.bd-idcards-print-job"),
    path(r"/print-jobs/<uuid:uid>/download", v.IdPrintJobDownload.as_view(),
         name="weapi.bd-idcards-print-job-download"),
    path(r"/print-jobs/<uuid:uid>/<str:action>", v.IdPrintJobAction.as_view(),
         name="weapi.bd-idcards-print-job-action"),
    path(r"/fields", v.IdFields.as_view(), name="weapi.bd-idcards-fields"),
    path(r"/fields/<uuid:uid>", v.IdField.as_view(), name="weapi.bd-idcards-field"),
    path(r"/profiles", v.IdProfiles.as_view(), name="weapi.bd-idcards-profiles"),
    path(r"/profiles/<uuid:uid>", v.IdProfile.as_view(), name="weapi.bd-idcards-profile"),
]
