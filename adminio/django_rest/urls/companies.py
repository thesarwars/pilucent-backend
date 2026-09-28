from django.urls import path
from adminio.django_rest.views.companies import AdminCompanyList, AdminCompanyRetrieve, AdminUserRetrieve

urlpatterns = [
    path("/su", AdminCompanyList.as_view(), name="adminio.company-list"),       #api/v1/companies/adminio/su
    path("/su/create", AdminCompanyList.as_view(), name="adminio.company-create"),      #api/v1/adminio/companies/su/create
    path("/su/retrieve/<str:uid>", AdminCompanyRetrieve.as_view(), name="adminio.company-retrieve"),      #api/v1/adminio/companies/su/retrieve
    path("/su/user-retrieve/<str:email>", AdminUserRetrieve.as_view(), name="adminio.user-retrieve"),      #api/v1/adminio/companies/su/user-retrieve
]