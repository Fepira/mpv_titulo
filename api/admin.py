from django.contrib import admin
from .models import Carrera, Programa, Curso, Periodo, Seccion, Docente, Alumno

# Registramos los modelos principales para empezar a poblar el MVP
admin.site.register(Carrera)
admin.site.register(Programa)
admin.site.register(Curso)
admin.site.register(Periodo)
admin.site.register(Seccion)
admin.site.register(Docente)
admin.site.register(Alumno)
