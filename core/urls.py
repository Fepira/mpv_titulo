from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include
from Applications.apiDemanda.views import *
from Applications.Dashboard.views import *

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/logout/', auth_views.LogoutView.as_view(next_page='apiDemanda:proyeccion_demanda_form'), name='logout'),
    path('api/', include('Applications.apiDemanda.urls')),
    path('api/', include('Applications.apiProgramacion.urls')),
    path('api/', include('Applications.RadDocente.urls')),
    path('', include('Applications.Dashboard.urls')),
    ]