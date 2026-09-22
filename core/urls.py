from django.contrib import admin
from django.urls import path, include
from Applications.api.views import *
from Applications.Dashboard.views import *

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('Applications.api.urls')),
    path('', include('Applications.Dashboard.urls')),
    ]