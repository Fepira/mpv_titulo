from django.urls import path

from . import views

app_name = 'RadDocente'

urlpatterns = [
    path('presupuesto/', views.seleccion_periodo_presupuesto, name='presupuesto_seleccion'),
    path('presupuesto/<int:id_periodo>/', views.gestionar_presupuesto, name='presupuesto_periodo'),
    path('presupuesto/<int:id_periodo>/curso/<int:id_curso>/', views.gestionar_presupuesto, name='presupuesto_curso'),
]
