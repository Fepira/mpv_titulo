from django.urls import include, path
from . import views

urlpatterns = [
    path('api/', views.HomeListView.as_view(), name='home'),
]