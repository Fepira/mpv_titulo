from django.urls import include, path
from . import views

app_name = 'apiDemanda'

urlpatterns = [
    path('', views.HomeListView.as_view(), name='home'),

    path('proyeccion/', views.ProyeccionDemandaView.as_view(), name='proyeccion_demanda_form'),
    path('proyeccion/ejecutar/', views.ProyeccionDemandaView.as_view(), name='proyeccion_demanda_ejecutar'),
    path('proyeccion/periodos/', views.proyeccion_listar_periodos_api, name='proyeccion_listar_periodos'),
    path('proyeccion/resultados/', views.proyeccion_resultados_seleccion_view, name='proyeccion_resultados_seleccion'),
    path('proyeccion/<int:id_periodo>/resultados/', views.proyeccion_resultados_view, name='proyeccion_resultados'),
    path('proyeccion/<int:id_periodo>/limpiar/', views.proyeccion_limpiar_view, name='proyeccion_limpiar_periodo'),
]
