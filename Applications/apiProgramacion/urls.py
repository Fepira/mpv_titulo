from django.urls import path

from . import views

app_name = 'apiProgramacion'

urlpatterns = [
    path('programacion/', views.programacion_seleccion, name='programacion_seleccion'),
    path('programacion/<int:id_periodo>/', views.configuracion_periodo, name='configuracion_periodo'),
    path('programacion/<int:id_periodo>/ejecutar/', views.ejecutar_programacion, name='ejecutar_programacion'),
    path('programacion/<int:id_periodo>/horario/', views.horario_programado, name='horario_programado'),
    path('programacion/<int:id_periodo>/horario/exportar/', views.exportar_horario_csv, name='exportar_horario_csv'),
    path('programacion/<int:id_periodo>/historial/', views.historial_programacion, name='historial_programacion'),
    path('programacion/resultado/<int:id_resultado>/activar/', views.activar_programacion, name='activar_programacion'),
    path('programacion/resultado/<int:id_resultado>/eliminar/', views.eliminar_programacion, name='eliminar_programacion'),
    path('programacion/<int:id_periodo>/curso/<int:id_curso>/', views.configuracion_curso, name='configuracion_curso'),
    path('programacion/<int:id_periodo>/curso/<int:id_curso>/guardar/', views.guardar_configuracion_curso, name='guardar_configuracion_curso'),
    path('programacion/<int:id_periodo>/parametros/', views.parametros_periodo, name='parametros_periodo'),
    path('programacion/<int:id_periodo>/parametros/guardar/', views.guardar_parametros, name='guardar_parametros'),
    path('programacion/parametros-ag/', views.parametros_ag, name='parametros_ag'),
    path('programacion/parametros-ag/guardar/', views.guardar_parametros_ag, name='guardar_parametros_ag'),
]
