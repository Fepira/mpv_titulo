from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from .models import *

class ProgramaAdmin(admin.ModelAdmin):
    list_display = ('id_programa',
                'carrera',
                'codigo_programa',
                'nombre_programa')

class CursoAdmin(admin.ModelAdmin):
    list_display = (
        'id_curso',
        'codigo_asignatura',
        'nombre_asignatura',
        'programa',
        'semestres',
        'periodicidad',
        'subperiodo',
        'creditos'
    )

    list_select_related = ('programa',)

    list_filter = (
        'programa',
        'periodicidad',
        'subperiodo',
        'es_bolsa'
    )

    search_fields = (
        'codigo_asignatura',
        'nombre_asignatura'
    )

class CarreraAdmin(admin.ModelAdmin):
    list_display = (
        'id_carrera',
        'nombre_carrera',
        'cuota_sala_comun'
    )


class AlumnoAdmin(admin.ModelAdmin):
    list_display = (
        'id_alumno',
        'nombre_alumno',
        'correo_alumno'
    )

class CategoriaDocenteAdmin(admin.ModelAdmin):
    list_display = (
        'id_categoria',
        'nombre_categoria',
        'tarifa_modulo'
    )

class DocenteAdmin(admin.ModelAdmin):
    list_display = (
        'id_docente',
        'categoria',
        'nombre_completo',
        'tipo_personal'
    )
    search_fields = ('nombre_completo', 'id_docente')

class MatriculaAdmin(admin.ModelAdmin):
    list_display = (
        'id_matricula',
        'alumno',
        'programa',
        'anio_ingreso',
        'estatus'
    )
    list_filter = ('estatus', 'programa', 'anio_ingreso')
    list_select_related = ('alumno', 'programa')


class UsuarioAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        ('Información Adicional', {
            'fields': ('rut', 'telefono'),
        }),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ('Información Adicional', {
            'fields': ('rut', 'telefono'),
        }),
    )
    list_display = ('username', 'email', 'first_name', 'last_name', 'rut', 'rol_principal', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups')
    search_fields = ('username', 'first_name', 'last_name', 'email', 'rut')
    readonly_fields = ('last_login', 'date_joined')

    def rol_principal(self, obj):
        return obj.rol_principal
    rol_principal.short_description = 'Rol Principal'

class EstimacionDemandaAdmin(admin.ModelAdmin):
    list_display = (
        'id_estimacion',
        'periodo',
        'curso',
        'alumnos_proyectados',
        'secciones_calculadas'
    )

class SeccionComponenteAdmin(admin.ModelAdmin):
    list_display = (
        'id_componente',
        'seccion',
        'componente_curso'
    )

class SeccionAdmin(admin.ModelAdmin):
    list_display = (
        'id_seccion',
        'periodo',
        'curso',
        'nrc_seccion'
    )


admin.site.register(Carrera, CarreraAdmin)
admin.site.register(Programa, ProgramaAdmin)
admin.site.register(Curso, CursoAdmin)
admin.site.register(Periodo)
admin.site.register(Docente, DocenteAdmin)
admin.site.register(Alumno, AlumnoAdmin)
admin.site.register(Seccion ,SeccionAdmin)
admin.site.register(Matricula, MatriculaAdmin)
admin.site.register(CategoriaDocente, CategoriaDocenteAdmin)
admin.site.register(AsignacionDocente)
admin.site.register(Usuario, UsuarioAdmin)
admin.site.register(EstimacionDemanda, EstimacionDemandaAdmin)
admin.site.register(SeccionComponente, SeccionComponenteAdmin)

