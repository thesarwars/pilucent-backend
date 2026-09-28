from django.urls import path, include

urlpatterns = [
    path("/ded-con", include("weapi.django_rest.urls.payroll.deduction_and_contribution")),
    path("/pay-schedule", include("weapi.django_rest.urls.payroll.pay_schedule")),
    path("/general-tax-setting", include("weapi.django_rest.urls.payroll.general_tax_setting")),
    path("/federal-tax-info-setting", include("weapi.django_rest.urls.payroll.federal_tax_setting")),
    path("/state-tax-settings", include("weapi.django_rest.urls.payroll.state_tax_setting")),
    path("/salary-process", include("weapi.django_rest.urls.payroll.salary_process")),
  	path("/work-location", include("weapi.django_rest.urls.payroll.work_location")),
    path("/accounting-preferences", include("weapi.django_rest.urls.payroll.accounting_preferences")),
  	path("/general-settings", include("weapi.django_rest.urls.payroll.general_settings")),
    path("/contact-info-setting", include("weapi.django_rest.urls.payroll.contact_info_setting")),
  	path("/reports", include("weapi.django_rest.urls.payroll.reports")),
	  path("/tax-center", include("weapi.django_rest.urls.payroll.tax_center")),
    path("/tax-config", include("weapi.django_rest.urls.payroll.tax_config")),
]