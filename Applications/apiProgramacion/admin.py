from django.contrib import admin

from .models import (
    BloqueProgramado,
    ConfiguracionProgramacion,
    ParametrosAG,
    ProgramacionResultado,
    VentanaHoraria,
)


class VentanaHorariaInline(admin.TabularInline):
    model = VentanaHoraria
    extra = 0


@admin.register(ConfiguracionProgramacion)
class ConfiguracionProgramacionAdmin(admin.ModelAdmin):
    list_display = ('id_configuracion', 'periodo')
    inlines = (VentanaHorariaInline,)


@admin.register(ParametrosAG)
class ParametrosAGAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'cant_dias', 'cant_bin_per_gen', 'max_iteraciones',
        'cant_poblacion', 'threshold_padres', 'prob_mutacion', 'umbral_early_stop',
    )

    def has_add_permission(self, request):
        # Registro único: se crea automáticamente con los valores por defecto.
        return not ParametrosAG.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class BloqueProgramadoInline(admin.TabularInline):
    model = BloqueProgramado
    extra = 0
    fields = ('id_gen', 'seccion', 'dia_semana', 'modulo_inicio', 'num_modulos', 'es_fijo')
    ordering = ('id_gen',)
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ProgramacionResultado)
class ProgramacionResultadoAdmin(admin.ModelAdmin):
    list_display = (
        'id_resultado', 'periodo', 'es_vigente', 'mejor_fitness', 'iteraciones',
        'cant_genes', 'max_horas_edificio', 'fecha_generacion',
    )
    list_filter = ('periodo', 'es_vigente')
    readonly_fields = ('fecha_generacion', 'parametros_snapshot', 'ventanas_snapshot')
    inlines = (BloqueProgramadoInline,)


@admin.register(BloqueProgramado)
class BloqueProgramadoAdmin(admin.ModelAdmin):
    list_display = (
        'id_bloque', 'resultado', 'id_gen', 'seccion',
        'dia_semana', 'modulo_inicio', 'num_modulos', 'es_fijo',
    )
    list_filter = ('resultado', 'dia_semana', 'es_fijo')
    list_select_related = ('resultado', 'seccion', 'seccion__curso')
