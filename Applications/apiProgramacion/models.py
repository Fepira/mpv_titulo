from django.conf import settings
from django.db import models

from Applications.apiDemanda.models import Periodo, Seccion


class ConfiguracionProgramacion(models.Model):
    """Configuración de programación académica de un periodo.

    Es el padre de las ventanas horarias: la geometría de módulos depende de
    qué semestres y tipos de asignatura se están programando en ese periodo.
    """

    id_configuracion = models.AutoField(primary_key=True)
    periodo = models.OneToOneField(
        Periodo,
        on_delete=models.CASCADE,
        db_column='id_periodo',
        related_name='configuracion_programacion',
    )

    class Meta:
        verbose_name = 'Configuración de programación'
        verbose_name_plural = 'Configuraciones de programación'

    def __str__(self):
        return f'Programación {self.periodo.nombre_periodo}'


class VentanaHoraria(models.Model):
    """Franja ("jaula matemática") de módulos permitidos para un semestre y tipo de asignatura.

    Los módulos se expresan en 1-based (módulo 1 = primera hora del día).
    El caso TRANSVERSAL se representa con `semestre = 0`.
    """

    TIPO_ASIGNATURA_CHOICES = [
        ('OBLIGATORIA', 'Obligatoria'),
        ('MENCION', 'Mención'),
        ('TRANSVERSAL', 'Transversal'),
    ]

    SEMESTRE_TRANSVERSAL = 0

    id_ventana = models.AutoField(primary_key=True)
    configuracion = models.ForeignKey(
        ConfiguracionProgramacion,
        on_delete=models.CASCADE,
        db_column='id_configuracion',
        related_name='ventanas',
    )
    semestre = models.PositiveIntegerField()
    tipo_asignatura = models.CharField(max_length=15, choices=TIPO_ASIGNATURA_CHOICES)
    modulo_inicio = models.PositiveIntegerField()
    modulo_fin = models.PositiveIntegerField()

    class Meta:
        unique_together = [('configuracion', 'semestre', 'tipo_asignatura')]
        ordering = ['semestre', 'tipo_asignatura']
        verbose_name = 'Ventana horaria'
        verbose_name_plural = 'Ventanas horarias'

    def __str__(self):
        return (
            f'Semestre {self.semestre} · {self.get_tipo_asignatura_display()} '
            f'({self.modulo_inicio}-{self.modulo_fin})'
        )


class ParametrosAG(models.Model):
    """Parámetros globales del Algoritmo Genético (registro único).

    No son por periodo ni por carrera: son la configuración técnica del motor
    de optimización, editable solo por Coordinador Académico y Administrador.
    """

    cant_dias = models.PositiveSmallIntegerField(default=5)
    cant_bin_per_gen = models.PositiveSmallIntegerField(default=6)
    max_iteraciones = models.PositiveIntegerField(default=1500)
    cant_poblacion = models.PositiveIntegerField(default=150)
    threshold_padres = models.PositiveSmallIntegerField(default=40)
    prob_mutacion = models.FloatField(default=0.05)
    umbral_early_stop = models.FloatField(default=0)

    class Meta:
        verbose_name = 'Parámetros del Algoritmo Genético'
        verbose_name_plural = 'Parámetros del Algoritmo Genético'

    def __str__(self):
        return 'Parámetros del AG'

    @classmethod
    def obtener(cls):
        """Devuelve la configuración única, creándola con los valores por defecto si no existe."""
        parametros, _ = cls.objects.get_or_create(pk=1)
        return parametros


class ProgramacionResultado(models.Model):
    """Corrida del Algoritmo Genético para un periodo (con historial).

    Cada ejecución crea una corrida nueva. La corrida vigente (`es_vigente=True`)
    es la que muestra el horario; las anteriores quedan en el historial para
    comparar. Se guarda un snapshot de los parámetros del AG y de las ventanas
    horarias usadas, porque las métricas (fitness) solo son comparables si las
    entradas también lo son.
    """

    id_resultado = models.AutoField(primary_key=True)
    periodo = models.ForeignKey(
        Periodo,
        on_delete=models.CASCADE,
        db_column='id_periodo',
        related_name='programaciones',
    )
    es_vigente = models.BooleanField(default=True)
    mejor_fitness = models.FloatField()
    iteraciones = models.PositiveIntegerField()
    cant_genes = models.PositiveIntegerField()
    max_horas_edificio = models.PositiveIntegerField()
    cant_dias = models.PositiveSmallIntegerField()
    parametros_snapshot = models.JSONField(default=dict, blank=True)
    ventanas_snapshot = models.JSONField(default=list, blank=True)
    fecha_generacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_generacion']
        constraints = [
            models.UniqueConstraint(
                fields=['periodo'],
                condition=models.Q(es_vigente=True),
                name='unica_corrida_vigente_por_periodo',
            ),
        ]
        verbose_name = 'Resultado de programación'
        verbose_name_plural = 'Resultados de programación'

    def __str__(self):
        return (
            f'Programación {self.periodo.nombre_periodo} '
            f'({self.fecha_generacion:%d/%m/%Y %H:%M} · fitness {self.mejor_fitness:g})'
        )


class BloqueProgramado(models.Model):
    """Paquete de módulos consecutivos asignado a una sección por el AG.

    Los módulos se expresan en 1-based. Ocupa los casilleros
    `modulo_inicio .. modulo_inicio + num_modulos - 1` del día indicado.
    """

    id_bloque = models.AutoField(primary_key=True)
    resultado = models.ForeignKey(
        ProgramacionResultado,
        on_delete=models.CASCADE,
        db_column='id_resultado',
        related_name='bloques',
    )
    seccion = models.ForeignKey(Seccion, on_delete=models.CASCADE, db_column='id_seccion')
    id_gen = models.PositiveIntegerField()
    dia_semana = models.CharField(max_length=15, choices=Seccion.DIA_SEMANA_CHOICES)
    modulo_inicio = models.PositiveIntegerField()
    num_modulos = models.PositiveIntegerField()
    es_fijo = models.BooleanField(default=False)

    class Meta:
        ordering = ['seccion_id', 'id_gen']
        unique_together = [('resultado', 'id_gen')]
        verbose_name = 'Bloque programado'
        verbose_name_plural = 'Bloques programados'

    def __str__(self):
        return (
            f'{self.seccion.curso.codigo_asignatura} · {self.dia_semana} '
            f'módulo {self.modulo_inicio} (+{self.num_modulos - 1})'
        )


class EstadoProgramacionPeriodo(models.Model):
    """Marca explícita de 'programación lista' para un periodo.

    La DOAE/escuela confirma con este flag que el horario quedó cerrado. El
    Dashboard considera el periodo 'listo' si este flag está marcado OR si
    existe una corrida vigente seleccionada (`ProgramacionResultado.es_vigente`).
    """

    id_estado = models.AutoField(primary_key=True)
    periodo = models.OneToOneField(
        Periodo,
        on_delete=models.CASCADE,
        db_column='id_periodo',
        related_name='estado_programacion',
    )
    esta_lista = models.BooleanField(default=False)
    marcado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        db_column='id_marcado_por',
        related_name='periodos_marcados_listos',
    )
    fecha_marcado = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Estado de programación'
        verbose_name_plural = 'Estados de programación'

    def __str__(self):
        estado = 'Lista' if self.esta_lista else 'No lista'
        return f'{self.periodo.nombre_periodo} · {estado}'
