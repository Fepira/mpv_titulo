from django.contrib import admin
from django.urls import path, include
from Applications.apiDemanda.views import *
from Applications.Dashboard.views import *

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('Applications.apiDemanda.urls')),
    path('', include('Applications.Dashboard.urls')),
    ]