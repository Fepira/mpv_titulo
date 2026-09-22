from django.urls import include, path
from . import views

urlpatterns = [
    path('dashboard/', views.DashboardAcademicoView.as_view(), name='dashboard'),
]