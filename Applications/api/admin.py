from django.contrib import admin
from .models import *

class ProgramaAdmin(admin.ModelAdmin):
    list_display = ('id_programa',
                'carrera',
                'codigo_programa',
                'nombre_programa')

class CursoAdmin(admin.ModelAdmin):
    # 1. Las columnas que verás en la tabla principal
    list_display = (
        'codigo_asignatura',
        'nombre_asignatura',
        'programa',       # Llave foránea
        'semestres',      # Tu ArrayField
        'Periodicidad',
        'subperiodo',
        'Creditos'
    )
    
    # 2. Optimización: Hace un JOIN en SQL para evitar que Django haga 285 consultas extra para traer el nombre del programa
    list_select_related = ('programa',)
    
    # 3. Agrega un panel lateral derecho para filtrar rápidamente los cursos
    list_filter = (
        'programa', 
        'Periodicidad', 
        'subperiodo', 
        'es_bolsa'
    )
    
    # 4. Agrega una barra de búsqueda superior (busca por código o nombre)
    search_fields = (
        'codigo_asignatura', 
        'nombre_asignatura'
    )

# Registramos los modelos principales para empezar a poblar el MVP
admin.site.register(Carrera)
admin.site.register(Programa,ProgramaAdmin)
admin.site.register(Curso, CursoAdmin)
admin.site.register(Periodo)
admin.site.register(Docente)
admin.site.register(Alumno)
admin.site.register(Seccion)
admin.site.register(Matricula)
