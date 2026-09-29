from django.urls import include, path
from . import views

app_name = 'apiDemanda'

urlpatterns = [
    path('', views.HomeListView.as_view(), name='home'),

    path('proyeccion/', views.ProyeccionDemandaView.as_view(), name='proyeccion_demanda_form'),
    path('proyeccion/ejecutar/', views.ProyeccionDemandaView.as_view(), name='proyeccion_demanda_ejecutar'),
    path('proyeccion/periodos/', views.proyeccion_listar_periodos_api, name='proyeccion_listar_periodos'),
    path('proyeccion/<int:id_periodo>/resultados/', views.proyeccion_resultados_view, name='proyeccion_resultados'),

    path('programacion/<int:id_periodo>/', views.gestionar_programacion, name='gestionar_programacion_periodo'),
    path('programacion/<int:id_periodo>/curso/<int:id_curso>/', views.gestionar_programacion, name='gestionar_programacion_curso'),
]
