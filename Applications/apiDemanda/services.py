import math
import logging
from dataclasses import dataclass, field
from django.db import transaction
from django.db.models import Count
from .models import (
    Curso, Periodo, EstimacionDemanda, Seccion, SeccionComponente,
    SeccionHorario, AsignacionDocente, Matricula, Mencion, BolsaDetalle,
)

logger = logging.getLogger(__name__)


@dataclass
class ResumenLimpieza:
    """Cantidades totales eliminadas por entidad al limpiar un periodo."""
    periodo_id: int
    periodo_nombre: str
    asignaciones_docente: int = 0
    secciones_horario: int = 0
    secciones_componente: int = 0
    secciones: int = 0
    estimaciones_demanda: int = 0

    @property
    def total_eliminados(self) -> int:
        return (
            self.asignaciones_docente
            + self.secciones_horario
            + self.secciones_componente
            + self.secciones
            + self.estimaciones_demanda
        )

    def detalles(self) -> list[tuple[str, int]]:
        return [
            ("Asignaciones docentes",         self.asignaciones_docente),
            ("Horarios / SeccionHorario",      self.secciones_horario),
            ("Componentes / SeccionComponente", self.secciones_componente),
            ("Secciones",                      self.secciones),
            ("Estimaciones / Demanda",         self.estimaciones_demanda),
            ("TOTAL ELIMINADO",                self.total_eliminados),
        ]


@transaction.atomic
def limpiar_proyeccion_periodo(
    id_periodo: int,
    confirmar_identidad: bool = False,
) -> ResumenLimpieza:
    """
    Borra TODOS los registros derivados de una proyección de demanda para un periodo,
    en ORDEN CORRECTO para NO violar FK constraints (de más hojas a la raíz):

      1) AsignacionDocente        (FK → SeccionComponente)
      2) SeccionHorario           (FK → Seccion)
      3) SeccionComponente        (FK → Seccion)
      4) Seccion                  (FK → Periodo)
      5) EstimacionDemanda        (FK → Periodo)

    Retorna un `ResumenLimpieza` con la cuenta de filas borradas por entidad.

    Si `confirmar_identidad=False` solo valida que el periodo exista y devuelve
    las CANTIDADES QUE SE BORRARÍAN, PERO NO BORRA NADA (modo dry-run).
    """
    periodo = Periodo.objects.get(id_periodo=id_periodo)
    resumen = ResumenLimpieza(periodo_id=periodo.id_periodo, periodo_nombre=periodo.nombre_periodo)

    # 0) Determinar los IDs de Seccion y SeccionComponente que cuelgan de este periodo
    secciones_qs = Seccion.objects.filter(periodo=periodo)
    componentes_qs = SeccionComponente.objects.filter(seccion__in=secciones_qs)

    if confirmar_identidad:
        # 1) AsignacionesDocente (FK a SeccionComponente)
        cnt = AsignacionDocente.objects.filter(componente__in=componentes_qs).delete()[0]
        resumen.asignaciones_docente = cnt

        # 2) SeccionHorario (FK a Seccion)
        cnt = SeccionHorario.objects.filter(seccion__in=secciones_qs).delete()[0]
        resumen.secciones_horario = cnt

        # 3) SeccionComponente (FK a Seccion) — [ATENCION: el Django CASCADE delete()
        #    sobre Seccion borraria tambien sus componentes y horarios. Pero borramos
        #    explícitamente para tener contadores exactos.]
        cnt = componentes_qs.delete()[0]
        resumen.secciones_componente = cnt

        # 4) Secciones del periodo (FK → Periodo)
        cnt = secciones_qs.delete()[0]
        resumen.secciones = cnt

        # 5) EstimacionesDemanda del periodo
        cnt = EstimacionDemanda.objects.filter(periodo=periodo).delete()[0]
        resumen.estimaciones_demanda = cnt

        logger.info(
            "LimpiezaPeriodo id=%d (%s) OK: %s",
            periodo.id_periodo, periodo.nombre_periodo,
            ", ".join(f"{n}={v}" for (n, v) in resumen.detalles()),
        )
    else:
        # Dry-run: contamos sin borrar nada
        resumen.asignaciones_docente   = AsignacionDocente.objects.filter(componente__in=componentes_qs).count()
        resumen.secciones_horario      = SeccionHorario.objects.filter(seccion__in=secciones_qs).count()
        resumen.secciones_componente   = componentes_qs.count()
        resumen.secciones              = secciones_qs.count()
        resumen.estimaciones_demanda   = EstimacionDemanda.objects.filter(periodo=periodo).count()

    return resumen



@dataclass
class ResumenProyeccion:
    periodo: Periodo = None
    total_cursos_evaluados: int = 0
    total_cursos_procesados: int = 0
    total_cursos_omitidos: int = 0
    alumnos_proyectados_total: int = 0
    ingresos_proyectados_para_futuro: int = 0  # alumnos que vienen via input override (no BD)
    secciones_generadas_total: int = 0
    componentes_generados_total: int = 0
    omitidos_sin_semestres: int = 0
    omitidos_semestre_99: int = 0
    omitidos_semestre_no_coincide: int = 0
    omitidos_sin_alumnos: int = 0
    omitidos_periodicidad_invalida: int = 0
    # --- Bolsas (Mención) ---
    bolsas_procesadas: int = 0
    menciones_generadas: int = 0
    omitidos_bolsa_sin_demanda: int = 0
    omitidos_bolsa_sin_menciones: int = 0
    omitidos_bolsa_sin_detalle: int = 0
    omitidos_bolsa_tipo_no_soportado: int = 0
    cursos: list[dict] = field(default_factory=list)

    def to_dict(self):
        return {
            "periodo": str(self.periodo),
            "total_cursos_evaluados": self.total_cursos_evaluados,
            "total_cursos_procesados": self.total_cursos_procesados,
            "total_cursos_omitidos": self.total_cursos_omitidos,
            "alumnos_proyectados_total": self.alumnos_proyectados_total,
            "ingresos_proyectados_para_futuro": self.ingresos_proyectados_para_futuro,
            "secciones_generadas_total": self.secciones_generadas_total,
            "componentes_generados_total": self.componentes_generados_total,
            "bolsas_procesadas": self.bolsas_procesadas,
            "menciones_generadas": self.menciones_generadas,
            "detalle_omitidos": {
                "sin_semestres_declarados": self.omitidos_sin_semestres,
                "semestre_99_ignorado": self.omitidos_semestre_99,
                "semestre_no_coincide_periodo": self.omitidos_semestre_no_coincide,
                "cohorte_sin_alumnos": self.omitidos_sin_alumnos,
                "periodicidad_invalida": self.omitidos_periodicidad_invalida,
                "bolsa_sin_demanda": self.omitidos_bolsa_sin_demanda,
                "bolsa_sin_menciones": self.omitidos_bolsa_sin_menciones,
                "bolsa_sin_detalle": self.omitidos_bolsa_sin_detalle,
                "bolsa_tipo_no_soportado": self.omitidos_bolsa_tipo_no_soportado,
            },
            "cursos_procesados": self.cursos,
        }


def _validar_formato_periodo(nombre_periodo: str):
    nombre = str(nombre_periodo).strip()
    if len(nombre) != 6:
        raise ValueError(
            f"Formato de periodo '{nombre}' inválido. Debe ser YYYY25/YYYY10 (1er sem) o YYYY75/YYYY20 (2do sem), ej: '202625' o '202675'."
        )
    if not nombre.isdigit():
        raise ValueError(f"Periodo '{nombre}' no es numérico.")
    sufijo = nombre[4:]
    sufijos_validos = {
        # Banner (nuevo):
        "25": 1,   # 1er semestre
        "75": 2,   # 2do semestre
        # Compatibilidad hacia atras (antiguos):
        "10": 1,   # 1er semestre
        "20": 2,   # 2do semestre
    }
    if sufijo not in sufijos_validos:
        raise ValueError(
            f"Sufijo del periodo '{sufijo}' inválido. Usa Banner: '25'=1er sem/'75'=2do sem (o compatibles '10'/'20')."
        )
    anio = int(nombre[:4])
    sem = sufijos_validos[sufijo]
    return anio, sem


def _obtener_semestre_malla(curso: Curso, sem_objetivo: int):
    """
    Determina el semestre de la MALLA CURRICULAR (1..10) de un curso para el
    periodo objetivo (sem_objetivo: 1 = Banner 25 1er sem, 2 = Banner 75 2do sem).

    REGLAS CLAVE (fix junio 2026):
      * Periodicidad '0' = ANUAL. Curso que dura TODO el año (semestres=[1,2]).
          → PERTENECE A LA PRIMERA MITAD DEL AÑO (1er semestre de malla).
          → NUNCA se duplica; SIEMPRE se usa semestres[0] = el IMPAR del array.
          → Luego, sem_calc = 1 (impar) == sem_objetivo ?  → se crea SOLO si 1er sem.

      * Periodicidad '1'/'2' = SEMESTRAL.
          (a) len(semestres)==1 → semestre malla = ese único valor.
          (b) len(semestres)>1 (ej: semestres=[3,4] o minor [5,6], [7,8])
              → Elegimos el elemento del array que CORRESPONDE a sem_objetivo:
                   sem_objetivo=1 (Banner 25) → semestres[0] (3, 5, 7 impar)
                   sem_objetivo=2 (Banner 75) → semestres[1] (4, 6, 8 par)
    """
    if not curso.semestres:
        return None, "sin_semestres"

    if 99 in curso.semestres:
        return None, "semestre_99"

    per_val = getattr(curso, 'periodicidad', None)
    period_choices = getattr(Curso, 'PERIODICIDAD_CHOICES', [])
    try:
        per_anual   = period_choices[0][0]
        per_sem_1   = period_choices[1][0]
        per_sem_2   = period_choices[2][0]
    except (IndexError, TypeError):
        per_anual, per_sem_1, per_sem_2 = '0', '1', '2'

    semestres = curso.semestres
    sem_malla = None

    # 1) ANUAL (0) = SIEMPRE PRIMER ELEMENTO IMPAR. No duplicar ambos semestres Banner.
    if per_val == per_anual:
        sem_malla = semestres[0]  # (1 en [1,2])

    # 2) SEMESTRAL (1 o 2)
    elif per_val in (per_sem_1, per_sem_2):
        if len(semestres) == 1:
            sem_malla = semestres[0]
        else:
            # len>1: elegir [0] para sem_obj=1, [1] para sem_obj=2
            idx = sem_objetivo - 1
            if 0 <= idx < len(semestres):
                sem_malla = semestres[idx]
            else:
                sem_malla = semestres[0]
    else:
        return None, "periodicidad_invalida"

    return sem_malla, None


def _cupo_seccion(curso: Curso) -> int:
    return curso.cupo_max_seccion if curso.cupo_max_seccion and curso.cupo_max_seccion > 0 else 40


def _crear_secciones_y_componentes(curso, periodo_proyeccion, secciones_calculadas, resumen):
    """Crea las Seccion + SeccionComponente de un curso y actualiza los contadores del resumen."""
    componentes_a_crear = []
    for num_sec in range(1, secciones_calculadas + 1):
        nrc = f"{curso.codigo_asignatura}-{num_sec}"
        nueva_seccion = Seccion.objects.create(
            periodo=periodo_proyeccion,
            curso=curso,
            nrc_seccion=nrc,
        )
        resumen.secciones_generadas_total += 1

        if curso.modulos_teoricos and curso.modulos_teoricos > 0:
            componentes_a_crear.append(SeccionComponente(seccion=nueva_seccion, componente_curso='Teórica'))
        if curso.modulos_practicos and curso.modulos_practicos > 0:
            componentes_a_crear.append(SeccionComponente(seccion=nueva_seccion, componente_curso='Práctica'))
        if curso.modulos_ayudantia_1 and curso.modulos_ayudantia_1 > 0:
            componentes_a_crear.append(SeccionComponente(seccion=nueva_seccion, componente_curso='Ayudantía tipo 1'))
        if curso.modulos_ayudantia_2 and curso.modulos_ayudantia_2 > 0:
            componentes_a_crear.append(SeccionComponente(seccion=nueva_seccion, componente_curso='Ayudantía tipo 2'))

    if componentes_a_crear:
        SeccionComponente.objects.bulk_create(componentes_a_crear)
        resumen.componentes_generados_total += len(componentes_a_crear)


def _procesar_bolsa_mencion(
    bolsa, alumnos_bolsa, cohortes_involucradas, cohorte_buscada,
    uso_override, menciones_por_programa, periodo_proyeccion, resumen,
):
    """
    Procesa un curso bolsa de tipo MENCIÓN.

    La demanda de la bolsa se reparte entre las N menciones activas del programa
    (NO entre los cursos que componen la bolsa). Se crea una EstimacionDemanda +
    Seccion(es) por cada curso real (mención) de la bolsa.
    """
    if alumnos_bolsa <= 0:
        resumen.omitidos_bolsa_sin_demanda += 1
        resumen.total_cursos_omitidos += 1
        return

    n_menciones = menciones_por_programa.get(bolsa.programa_id, 0)
    if n_menciones <= 0:
        resumen.omitidos_bolsa_sin_menciones += 1
        resumen.total_cursos_omitidos += 1
        return

    detalles = list(
        BolsaDetalle.objects
        .filter(curso_bolsa=bolsa, tipo_curso_bolsa='MENCION')
        .select_related('curso_real', 'mencion')
    )
    if not detalles:
        # Distinguir "bolsa vacía" de "bolsa con cursos pero de otro tipo (electivo, fuera de alcance)".
        if BolsaDetalle.objects.filter(curso_bolsa=bolsa).exists():
            resumen.omitidos_bolsa_tipo_no_soportado += 1
        else:
            resumen.omitidos_bolsa_sin_detalle += 1
        resumen.total_cursos_omitidos += 1
        return

    if len(detalles) != n_menciones:
        logger.warning(
            "ProyeccionDemanda: La bolsa '%s' declara %d menciones pero tiene %d cursos reales de mención.",
            bolsa.codigo_asignatura, n_menciones, len(detalles),
        )

    cupo = _cupo_seccion(bolsa)
    demanda_mencion = alumnos_bolsa / n_menciones
    secciones_por_mencion = max(1, math.ceil(demanda_mencion / cupo))
    alumnos_mencion = round(demanda_mencion)

    resumen.bolsas_procesadas += 1
    for detalle in detalles:
        curso_real = detalle.curso_real

        estimacion = EstimacionDemanda.objects.create(
            periodo=periodo_proyeccion,
            curso=curso_real,
            alumnos_proyectados=alumnos_mencion,
            secciones_calculadas=secciones_por_mencion,
            cohortes_involucradas=cohortes_involucradas,
        )
        _crear_secciones_y_componentes(curso_real, periodo_proyeccion, secciones_por_mencion, resumen)

        resumen.menciones_generadas += 1
        resumen.total_cursos_procesados += 1
        resumen.alumnos_proyectados_total += alumnos_mencion
        resumen.cursos.append({
            "curso_id": curso_real.id_curso,
            "codigo": curso_real.codigo_asignatura,
            "nombre": curso_real.nombre_asignatura,
            "cohorte": cohorte_buscada,
            "alumnos_proyectados": alumnos_mencion,
            "cupo_seccion": cupo,
            "secciones_calculadas": secciones_por_mencion,
            "estimacion_id": estimacion.id_estimacion,
            "origen_alumnos": "proyeccion_usuario" if uso_override else "matricula_real",
            "es_bolsa": True,
            "bolsa_id": bolsa.id_curso,
            "mencion_id": detalle.mencion_id,
        })


@transaction.atomic
def ejecutar_proyeccion_demanda(
    id_periodo_objetivo: int,
    sobrescribir: bool = True,
    proyeccion_ingresos_nuevos: dict | None = None,
) -> ResumenProyeccion:
    resumen = ResumenProyeccion()

    # Normalizar parámetro: dict[int, int] (programa_id -> n alumnos proyectados)
    ingresos_dict: dict[int, int] = {}
    if proyeccion_ingresos_nuevos:
        for k, v in proyeccion_ingresos_nuevos.items():
            try:
                pid = int(k)
                n = int(v or 0)
                if n > 0:
                    ingresos_dict[pid] = n
            except (TypeError, ValueError):
                continue

    periodo_proyeccion = Periodo.objects.get(id_periodo=id_periodo_objetivo)
    resumen.periodo = periodo_proyeccion

    anio_objetivo, sem_objetivo = _validar_formato_periodo(periodo_proyeccion.nombre_periodo)

    if sobrescribir:
        # Limpiar TODO el periodo (Asignaciones, Horarios, Componentes, Secciones, Estimaciones)
        resumen_limpieza = limpiar_proyeccion_periodo(
            id_periodo=periodo_proyeccion.id_periodo,
            confirmar_identidad=True,
        )
        logger.info(
            "ProyeccionDemanda: Sobrescribiendo periodo %s - Resumen limpieza: %s",
            periodo_proyeccion.nombre_periodo,
            ", ".join(f"{etq}={val}" for (etq, val) in resumen_limpieza.detalles()),
        )
    else:
        if EstimacionDemanda.objects.filter(periodo=periodo_proyeccion).exists() \
                or Seccion.objects.filter(periodo=periodo_proyeccion).exists():
            raise RuntimeError(
                f"Ya existen estimaciones/secciones para el periodo '{periodo_proyeccion.nombre_periodo}'. "
                "Usa sobrescribir=True para volver a calcular (limpia todo el periodo)."
            )

    cursos = Curso.objects.select_related("programa").all()
    resumen.total_cursos_evaluados = cursos.count()

    # Los cursos que son "curso_real" de una bolsa se manejan vía su bolsa (no de forma independiente).
    ids_curso_real = set(BolsaDetalle.objects.values_list('curso_real_id', flat=True))

    # Cantidad de menciones activas por programa (denominador de la demanda de una bolsa Mención).
    menciones_por_programa = {
        row["programa_id"]: row["n"]
        for row in (
            Mencion.objects.filter(activo=True)
            .values("programa_id")
            .annotate(n=Count("id_mencion"))
        )
    }

    for curso in cursos:
        if curso.id_curso in ids_curso_real:
            continue

        sem_malla, motivo_omitido = _obtener_semestre_malla(curso, sem_objetivo)
        if motivo_omitido == "sin_semestres":
            resumen.omitidos_sin_semestres += 1
            resumen.total_cursos_omitidos += 1
            continue
        if motivo_omitido == "semestre_99":
            resumen.omitidos_semestre_99 += 1
            resumen.total_cursos_omitidos += 1
            continue
        if motivo_omitido == "periodicidad_invalida":
            resumen.omitidos_periodicidad_invalida += 1
            resumen.total_cursos_omitidos += 1
            continue

        anios_extra = (sem_malla - 1) // 2
        sem_calc = 1 if (sem_malla % 2 != 0) else 2

        if sem_calc != sem_objetivo:
            resumen.omitidos_semestre_no_coincide += 1
            resumen.total_cursos_omitidos += 1
            continue

        cohorte_buscada = anio_objetivo - anios_extra
        cohortes_involucradas = [cohorte_buscada]

        alumnos_proyectados = Matricula.objects.filter(
            programa=curso.programa,
            anio_ingreso=cohorte_buscada,
        ).count()

        # OVERRIDE: INGRESO NUEVOS PROYECTADO SOLO PARA COHORTE NUEVA (cohorte_buscada == anio_objetivo)
        # IMPORTANTE: Nunca aplica para cohortes antiguas (ej: cohorte_buscada=2025 en periodo 202725)
        #   → si esos alumnos no tienen Matricula real, no significa que debamos "inventarlos".
        uso_override = False
        if alumnos_proyectados <= 0 and ingresos_dict and cohorte_buscada == anio_objetivo:
            pid = curso.programa_id
            if pid in ingresos_dict:
                n = int(ingresos_dict[pid])
                if n > 0:
                    alumnos_proyectados = n
                    resumen.ingresos_proyectados_para_futuro += n
                    uso_override = True

        # --- BOLSA (Mención): la demanda se reparte entre menciones, no entre cursos ---
        if curso.es_bolsa:
            _procesar_bolsa_mencion(
                bolsa=curso,
                alumnos_bolsa=alumnos_proyectados,
                cohortes_involucradas=cohortes_involucradas,
                cohorte_buscada=cohorte_buscada,
                uso_override=uso_override,
                menciones_por_programa=menciones_por_programa,
                periodo_proyeccion=periodo_proyeccion,
                resumen=resumen,
            )
            continue

        # --- Curso normal (Obligatoria) ---
        if alumnos_proyectados <= 0:
            resumen.omitidos_sin_alumnos += 1
            resumen.total_cursos_omitidos += 1
            continue

        cupo = _cupo_seccion(curso)
        secciones_calculadas = math.ceil(alumnos_proyectados / cupo)

        estimacion = EstimacionDemanda.objects.create(
            periodo=periodo_proyeccion,
            curso=curso,
            alumnos_proyectados=alumnos_proyectados,
            secciones_calculadas=secciones_calculadas,
            cohortes_involucradas=cohortes_involucradas,
        )
        _crear_secciones_y_componentes(curso, periodo_proyeccion, secciones_calculadas, resumen)

        resumen.total_cursos_procesados += 1
        resumen.alumnos_proyectados_total += alumnos_proyectados

        resumen.cursos.append({
            "curso_id": curso.id_curso,
            "codigo": curso.codigo_asignatura,
            "nombre": curso.nombre_asignatura,
            "cohorte": cohorte_buscada,
            "alumnos_proyectados": alumnos_proyectados,
            "cupo_seccion": cupo,
            "secciones_calculadas": secciones_calculadas,
            "estimacion_id": estimacion.id_estimacion,
            "origen_alumnos": "proyeccion_usuario" if uso_override else "matricula_real",
        })

    logger.info(
        "ProyeccionDemanda: Periodo %s finalizado - Procesados %d, Omitidos %d, "
        "Alumnos (reales): %d, Alumnos (proyectados input): %d, Secciones %d, Componentes %d, "
        "Bolsas %d, Menciones %d.",
        periodo_proyeccion.nombre_periodo, resumen.total_cursos_procesados,
        resumen.total_cursos_omitidos,
        resumen.alumnos_proyectados_total - resumen.ingresos_proyectados_para_futuro,
        resumen.ingresos_proyectados_para_futuro,
        resumen.secciones_generadas_total, resumen.componentes_generados_total,
        resumen.bolsas_procesadas, resumen.menciones_generadas,
    )

    return resumen
