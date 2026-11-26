from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.contrib.auth.models import AbstractUser, Group
from django.conf import settings
from django.core.exceptions import ValidationError


class NombreRol:
    ADMIN = "Administrador"
    COORDINADOR = "Coordinador Académico"
    JEFE_CARRERA = "Jefe de Carrera"
    DOCENTE = "Docente"
    ASISTENTE = "Asistente de Gestión"
    DOAE = "DOAE"

    CHOICES = [
        (ADMIN, ADMIN),
        (COORDINADOR, COORDINADOR),
        (JEFE_CARRERA, JEFE_CARRERA),
        (DOCENTE, DOCENTE),
        (ASISTENTE, ASISTENTE),
        (DOAE, DOAE),
    ]


class Usuario(AbstractUser):
    rut = models.CharField(max_length=15, null=True, blank=True, unique=True)
    telefono = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        verbose_name = 'Usuario'
        verbose_name_plural = 'Usuarios'

    def __str__(self):
        return f"{self.get_full_name()} ({self.username})"

    @property
    def nombre_completo(self):
        return self.get_full_name()

    @property
    def correo_usuario(self):
        return self.email

    @property
    def estado_activo(self):
        return self.is_active

    @property
    def rol_principal(self):
        primer_grupo = self.groups.first()
        return primer_grupo.name if primer_grupo else "Sin Rol"

    @property
    def roles(self):
        return list(self.groups.values_list('name', flat=True))

    def tiene_rol(self, nombre_rol):
        return self.groups.filter(name=nombre_rol).exists()

    @property
    def puede_ver_dashboard(self):
        """El Dashboard de carrera piloto es visible solo para Administrador o DOAE."""
        return self.is_superuser or self.tiene_rol(NombreRol.DOAE)

    def agregar_rol(self, nombre_rol):
        grupo, _ = Group.objects.get_or_create(name=nombre_rol)
        self.groups.add(grupo)
        return grupo

    def quitar_rol(self, nombre_rol):
        try:
            grupo = Group.objects.get(name=nombre_rol)
            self.groups.remove(grupo)
            return True
        except Group.DoesNotExist:
            return False

class Carrera(models.Model):
    id_carrera = models.BigAutoField(primary_key=True)
    nombre_carrera = models.CharField(max_length=255)
    cuota_sala_comun = models.IntegerField()
    cuota_sala_propia = models.IntegerField(default=3)

    def __str__(self):
        return self.nombre_carrera

class Programa(models.Model):

    ESTADO_CHOICES = [
        ('VIGENTE', 'Vigente'),
        ('EN CURSO', 'En Curso'),
        ('TERMINADO', 'Terminado'),
    ]

    id_programa = models.AutoField(primary_key=True)
    carrera = models.ForeignKey(Carrera, on_delete=models.CASCADE, db_column='id_carrera')
    codigo_programa = models.CharField(max_length=50)
    nombre_programa = models.CharField(max_length=100)
    version = models.CharField(max_length=50, default='1.0.0')
    estado = models.CharField(max_length=50, choices=ESTADO_CHOICES, default='EN CURSO')

    class Meta:
        verbose_name = 'Programa'
        verbose_name_plural = 'Programas'

    def __str__(self):
        return f"{self.nombre_programa} ({self.codigo_programa})"



class Curso(models.Model):

    PERIODICIDAD_CHOICES = [
        ('0', 'ANUAL'),
        ('1', 'SEMESTRAL'),
        ('2', 'BIMESTRAL'),
    ]

    SUBPERIODO_CHOICES = [
        ('COMPLETO', 'Semestre Completo'),
        ('A', 'Primer Bimestre (A)'),
        ('B', 'Segundo Bimestre (B)'),
    ]

    TIPO_SALA_CHOICES = [
        (2, 'Sala Propia'),
        (3, 'Sala Común'),
        (5, 'Sala Online'),
    ]

    id_curso = models.AutoField(primary_key=True)
    programa = models.ForeignKey('Programa', on_delete=models.CASCADE, db_column='id_programa')
    codigo_asignatura = models.CharField(max_length=50)
    nombre_asignatura = models.CharField(max_length=150)

    semestres = ArrayField(models.IntegerField(), default=list)

    periodicidad = models.CharField(max_length=50, choices=PERIODICIDAD_CHOICES, default='1')

    subperiodo = models.CharField(max_length=15, choices=SUBPERIODO_CHOICES, default='COMPLETO')

    creditos = models.PositiveIntegerField(default=0)
    modulos_teoricos = models.PositiveIntegerField(null=True, blank=True)
    modulos_practicos = models.PositiveIntegerField(null=True, blank=True)
    modulos_ayudantia_1 = models.PositiveIntegerField(null=True, blank=True)
    modulos_ayudantia_2 = models.PositiveIntegerField(null=True, blank=True)
    cupo_max_seccion = models.PositiveIntegerField()
    es_bolsa = models.BooleanField(default=False)

    # --- Configuración de programación académica (persistente por curso) ---
    # NULL = sin configurar (permite distinguir "no respondido" de una elección explícita).
    tipo_sala = models.IntegerField(choices=TIPO_SALA_CHOICES, null=True, blank=True, default=None)
    lista_cruzada = models.CharField(max_length=50, blank=True, default='')

    def __str__(self):
        return self.nombre_asignatura

    @property
    def num_modulos(self):
        """Módulos semanales del curso = teóricos + prácticos + ayudantía tipo 1.
        La ayudantía tipo 2 se imparte dentro de un módulo teórico/práctico, por lo que no suma."""
        return (
            (self.modulos_teoricos or 0)
            + (self.modulos_practicos or 0)
            + (self.modulos_ayudantia_1 or 0)
        )

    @property
    def tipo_asignatura(self):
        """Derivado de BolsaDetalle: 'MENCION' si el curso es un curso_real de una bolsa de mención."""
        return 'MENCION' if any(
            d.tipo_curso_bolsa == 'MENCION' for d in self.detalles_como_real.all()
        ) else 'OBLIGATORIA'

    @property
    def nombre_periodo_formateado(self):
        if not self.semestres:
            return ""

        str_sem = [str(s) for s in self.semestres]
        base_str = ""

        if len(self.semestres) == 1:
            base_str = str_sem[0]
        elif self.periodicidad == '0':
            base_str = " y ".join(str_sem)
        else:
            base_str = " o ".join(str_sem)

        if self.periodicidad == '2' and self.subperiodo in ['A', 'B']:
            return f"{base_str}{self.subperiodo.lower()}"

        return base_str

class Mencion(models.Model):
    id_mencion = models.AutoField(primary_key=True)
    programa = models.ForeignKey(Programa, on_delete=models.CASCADE, db_column='id_programa')
    nombre = models.CharField(max_length=150)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Mención'
        verbose_name_plural = 'Menciones'

    def __str__(self):
        return self.nombre


class BolsaDetalle(models.Model):
    TIPO_CURSO_BOLSA_CHOICES = [
        ('MENCION', 'Mención'),
        ('ELECTIVO', 'Electivo'),
        ('ELECTIVO_MENCION', 'Electivo de Mención'),
    ]

    id_detalle = models.AutoField(primary_key=True)
    curso_bolsa = models.ForeignKey(Curso, related_name='detalles_como_bolsa', on_delete=models.CASCADE, db_column='id_curso_bolsa')
    curso_real = models.ForeignKey(Curso, related_name='detalles_como_real', on_delete=models.CASCADE, db_column='id_curso_real')
    tipo_curso_bolsa = models.CharField(max_length=20, choices=TIPO_CURSO_BOLSA_CHOICES, default='MENCION')
    mencion = models.ForeignKey(Mencion, on_delete=models.SET_NULL, null=True, blank=True, db_column='id_mencion', related_name='detalles_bolsa')

    class Meta:
        verbose_name = 'Detalle de Bolsa'
        verbose_name_plural = 'Detalles de Bolsa'
        unique_together = [('curso_bolsa', 'mencion')]

    def clean(self):
        super().clean()

        # Un mismo curso no puede ser a la vez la bolsa y el curso real.
        if self.curso_bolsa_id and self.curso_bolsa_id == self.curso_real_id:
            raise ValidationError('Un curso no puede ser a la vez la bolsa y el curso real.')

        # El curso de la bolsa DEBE estar marcado como bolsa.
        if self.curso_bolsa_id and not self.curso_bolsa.es_bolsa:
            raise ValidationError({
                'curso_bolsa': 'El curso de la bolsa debe tener "es_bolsa" = True.'
            })

        # El curso real NO puede ser una bolsa.
        if self.curso_real_id and self.curso_real.es_bolsa:
            raise ValidationError({
                'curso_real': 'El curso real no puede estar marcado como bolsa ("es_bolsa" = True).'
            })

    def save(self, *args, **kwargs):
        # Fuerza las validaciones (clean + unique_together) en cualquier punto de entrada.
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.curso_bolsa} → {self.curso_real}"

class Periodo(models.Model):
    id_periodo = models.AutoField(primary_key=True)
    nombre_periodo = models.CharField(max_length=20)

    def __str__(self):
        return self.nombre_periodo

class EstimacionDemanda(models.Model):
    id_estimacion = models.AutoField(primary_key=True)
    periodo = models.ForeignKey(Periodo, on_delete=models.CASCADE, db_column='id_periodo')
    curso = models.ForeignKey(Curso, on_delete=models.CASCADE, db_column='id_curso')
    alumnos_proyectados = models.IntegerField()
    secciones_calculadas = models.IntegerField()
    cohortes_involucradas = ArrayField(models.IntegerField(), default=list)

class Seccion(models.Model):
    DIA_SEMANA_CHOICES = [
        ('LUNES', 'Lunes'),
        ('MARTES', 'Martes'),
        ('MIERCOLES', 'Miércoles'),
        ('JUEVES', 'Jueves'),
        ('VIERNES', 'Viernes'),
        ('SABADO', 'Sábado'),
    ]

    id_seccion = models.AutoField(primary_key=True)
    periodo = models.ForeignKey(Periodo, on_delete=models.CASCADE, db_column='id_periodo')
    curso = models.ForeignKey(Curso, on_delete=models.CASCADE, db_column='id_curso')
    nrc_seccion = models.CharField(max_length=20)

    # --- Fijos de programación (Hoja 2 del AG, por sección) ---
    dia_fijo = models.CharField(max_length=15, choices=DIA_SEMANA_CHOICES, blank=True, default='')
    modulo_inicio_fijo = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = [('periodo', 'curso', 'nrc_seccion')]

    def __str__(self):
        return f"NRC: {self.nrc_seccion} - {self.curso.nombre_asignatura}"

class SeccionComponente(models.Model):
    id_componente = models.AutoField(primary_key=True)
    seccion = models.ForeignKey(Seccion, on_delete=models.CASCADE, db_column='id_seccion')
    componente_curso = models.CharField(max_length=255)

class SeccionHorario(models.Model):
    id_horario = models.AutoField(primary_key=True)
    seccion = models.ForeignKey(Seccion, on_delete=models.CASCADE, db_column='id_seccion')
    dia_semana = models.CharField(max_length=15)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    lista_cruzada = models.CharField(max_length=50, null=True, blank=True)
    cupo_maximo = models.BigIntegerField()

class CategoriaDocente(models.Model):
    id_categoria = models.AutoField(primary_key=True)
    nombre_categoria = models.CharField(max_length=50)
    tarifa_modulo = models.IntegerField()

    def __str__(self):
        return self.nombre_categoria

class Docente(models.Model):
    id_docente = models.CharField(max_length=20, primary_key=True)
    categoria = models.ForeignKey(CategoriaDocente, on_delete=models.CASCADE, db_column='id_categoria')
    nombre_completo = models.CharField(max_length=150)
    tipo_personal = models.CharField(max_length=30, default="")

    def __str__(self):
        return self.nombre_completo

class AsignacionDocente(models.Model):
    id_asignacion = models.AutoField(primary_key=True)
    docente = models.ForeignKey(Docente, on_delete=models.CASCADE, db_column='id_docente', null=True, blank=True)
    categoria_requerida = models.ForeignKey(
        CategoriaDocente, on_delete=models.CASCADE, db_column='id_categoria_requerida',
        null=True, blank=True, related_name='asignaciones_requeridas',
    )
    componente = models.ForeignKey(SeccionComponente, on_delete=models.CASCADE, db_column='id_componente', related_name='asignaciones')
    usuario_asignador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_column='id_usuario_asignador', related_name='asignaciones_realizadas')
    costo_proyectado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = [('componente', 'docente')]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(docente__isnull=False) | models.Q(categoria_requerida__isnull=False),
                name='asignacion_con_docente_o_categoria',
            ),
        ]

class Alumno(models.Model):
    id_alumno = models.CharField(primary_key=True, max_length=15)
    nombre_alumno = models.CharField(max_length=150)
    correo_alumno = models.CharField(max_length=150)

    def __str__(self):
        return self.nombre_alumno

class Matricula(models.Model):
    id_matricula = models.BigAutoField(primary_key=True)
    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE, db_column='id_alumno')
    programa = models.ForeignKey(Programa, on_delete=models.CASCADE, db_column='id_programa')
    anio_ingreso = models.IntegerField(default=0)
    estatus = models.CharField(max_length=50)
