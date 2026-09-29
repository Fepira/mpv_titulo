from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.contrib.auth.models import AbstractUser, Group
from django.conf import settings


class NombreRol:
    ADMIN = "Administrador"
    COORDINADOR = "Coordinador Académico"
    JEFE_CARRERA = "Jefe de Carrera"
    DOCENTE = "Docente"
    ASISTENTE = "Asistente de Gestión"

    CHOICES = [
        (ADMIN, ADMIN),
        (COORDINADOR, COORDINADOR),
        (JEFE_CARRERA, JEFE_CARRERA),
        (DOCENTE, DOCENTE),
        (ASISTENTE, ASISTENTE),
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

    def __str__(self):
        return self.nombre_carrera

class Programa(models.Model):
    id_programa = models.AutoField(primary_key=True)
    carrera = models.ForeignKey(Carrera, on_delete=models.CASCADE, db_column='id_carrera')
    codigo_programa = models.CharField(max_length=50)
    nombre_programa = models.CharField(max_length=100)

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

    def __str__(self):
        return self.nombre_asignatura

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

class BolsaDetalle(models.Model):
    id_detalle = models.AutoField(primary_key=True)
    curso_bolsa = models.ForeignKey(Curso, related_name='detalles_como_bolsa', on_delete=models.CASCADE, db_column='id_curso_bolsa')
    curso_real = models.ForeignKey(Curso, related_name='detalles_como_real', on_delete=models.CASCADE, db_column='id_curso_real')

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

class Seccion(models.Model):
    id_seccion = models.AutoField(primary_key=True)
    periodo = models.ForeignKey(Periodo, on_delete=models.CASCADE, db_column='id_periodo')
    curso = models.ForeignKey(Curso, on_delete=models.CASCADE, db_column='id_curso')
    nrc_seccion = models.CharField(max_length=20)

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
    docente = models.ForeignKey(Docente, on_delete=models.CASCADE, db_column='id_docente')
    componente = models.ForeignKey(SeccionComponente, on_delete=models.CASCADE, db_column='id_componente', related_name='asignaciones')
    usuario_asignador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_column='id_usuario_asignador', related_name='asignaciones_realizadas')
    costo_proyectado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = [('componente', 'docente')]

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
