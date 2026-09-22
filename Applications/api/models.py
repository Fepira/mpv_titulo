from django.db import models
from django.contrib.postgres.fields import ArrayField

class Rol(models.Model):
    id_rol = models.AutoField(primary_key=True)
    nombre_rol = models.CharField(max_length=50)
    descripcion = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return self.nombre_rol

class Usuario(models.Model):
    id_usuario = models.BigAutoField(primary_key=True)
    rol = models.ForeignKey(Rol, on_delete=models.CASCADE, db_column='id_rol')
    nombre_completo = models.CharField(max_length=150)
    correo_usuario = models.CharField(max_length=150)
    hash_password = models.CharField(max_length=255)
    estado_activo = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre_completo

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
    
    # Nivel cronológico en la malla (SIEMPRE enteros puros)
    semestres = ArrayField(models.IntegerField(), default=list)
    
    Periodicidad = models.CharField(max_length=50, choices=PERIODICIDAD_CHOICES, default='1')
    
    # Fracción del periodo en la que se dicta
    subperiodo = models.CharField(max_length=15, choices=SUBPERIODO_CHOICES, default='COMPLETO')
    
    Creditos = models.IntegerField(default=0)
    modulos_teoricos = models.IntegerField(null=True, blank=True)
    modulos_practicos = models.IntegerField(null=True, blank=True)
    modulos_ayudantia_1 = models.IntegerField(null=True, blank=True)
    modulos_ayudantia_2 = models.IntegerField(null=True, blank=True)
    cupo_max_seccion = models.IntegerField()
    es_bolsa = models.BooleanField()

    def __str__(self):
        return self.nombre_asignatura

    @property
    def nombre_periodo_formateado(self):
        """
        Se encarga exclusivamente de la capa de presentación.
        Traduce la estructura pura de la base de datos a lenguaje humano.
        """
        if not self.semestres:
            return ""
            
        str_sem = [str(s) for s in self.semestres]
        base_str = ""

        # 1. Resolver el nivel cronológico (conservando la disyunción 'o' para renovaciones de malla complejas)
        if len(self.semestres) == 1:
            base_str = str_sem[0]
        elif self.Periodicidad == '0': 
            base_str = " y ".join(str_sem)
        else: 
            base_str = " o ".join(str_sem)
            
        # 2. Agregar el sufijo bimestral si corresponde
        if self.Periodicidad == '2' and self.subperiodo in ['A', 'B']:
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

    def __str__(self):
        return self.nombre_completo

class AsignacionDocente(models.Model):
    id_asignacion = models.AutoField(primary_key=True)
    docente = models.ForeignKey(Docente, on_delete=models.CASCADE, db_column='id_docente')
    componente = models.ForeignKey(SeccionComponente, on_delete=models.CASCADE, db_column='id_componente')
    usuario_asignador = models.ForeignKey(Usuario, on_delete=models.CASCADE, db_column='id_usuario_asignador')
    costo_proyectado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

class Alumno(models.Model):
    id_alumno = models.BigAutoField(primary_key=True)
    nombre_alumno = models.CharField(max_length=150)
    correo_alumno = models.CharField(max_length=150)

    def __str__(self):
        return self.nombre_alumno

class Matricula(models.Model):
    id_matricula = models.BigAutoField(primary_key=True)
    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE, db_column='id_alumno')
    programa = models.ForeignKey(Programa, on_delete=models.CASCADE, db_column='id_programa')
    estatus = models.CharField(max_length=50)
