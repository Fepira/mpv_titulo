import math
import logging
from dataclasses import dataclass, field
from django.db import transaction
from .models import Curso, Periodo, EstimacionDemanda, Seccion, SeccionComponente, Matricula

logger = logging.getLogger(__name__)


@dataclass
class ResumenProyeccion:
    periodo: Periodo = None
    total_cursos_evaluados: int = 0
    total_cursos_procesados: int = 0
    total_cursos_omitidos: int = 0
    alumnos_proyectados_total: int = 0
    secciones_generadas_total: int = 0
    componentes_generados_total: int = 0
    omitidos_sin_semestres: int = 0
    omitidos_semestre_99: int = 0
    omitidos_semestre_no_coincide: int = 0
    omitidos_sin_alumnos: int = 0
    omitidos_periodicidad_invalida: int = 0
    cursos: list[dict] = field(default_factory=list)

    def to_dict(self):
        return {
            "periodo": str(self.periodo),
            "total_cursos_evaluados": self.total_cursos_evaluados,
            "total_cursos_procesados": self.total_cursos_procesados,
            "total_cursos_omitidos": self.total_cursos_omitidos,
            "alumnos_proyectados_total": self.alumnos_proyectados_total,
            "secciones_generadas_total": self.secciones_generadas_total,
            "componentes_generados_total": self.componentes_generados_total,
            "detalle_omitidos": {
                "sin_semestres_declarados": self.omitidos_sin_semestres,
                "semestre_99_ignorado": self.omitidos_semestre_99,
                "semestre_no_coincide_periodo": self.omitidos_semestre_no_coincide,
                "cohorte_sin_alumnos": self.omitidos_sin_alumnos,
                "periodicidad_invalida": self.omitidos_periodicidad_invalida,
            },
            "cursos_procesados": self.cursos,
        }


def _validar_formato_periodo(nombre_periodo: str):
    nombre = str(nombre_periodo).strip()
    if len(nombre) != 6:
        raise ValueError(
            f"Formato de periodo '{nombre}' inválido. Debe ser YYYY10 (1er sem) o YYYY20 (2do sem), ej: '202710'."
        )
    if not nombre.isdigit():
        raise ValueError(f"Periodo '{nombre}' no es numérico.")
    sufijo = nombre[4:]
    if sufijo not in ("10", "20"):
        raise ValueError(
            f"Sufijo del periodo '{sufijo}' inválido. Debe ser '10' (1er sem) o '20' (2do sem)."
        )
    anio = int(nombre[:4])
    sem = 1 if sufijo == "10" else 2
    return anio, sem


def _obtener_semestre_malla(curso: Curso, sem_objetivo: int):
    if not curso.semestres:
        return None, "sin_semestres"

    if 99 in curso.semestres:
        return None, "semestre_99"

    sem_malla = None
    if curso.periodicidad == Curso.PERIODICIDAD_CHOICES[0][0]:  # '0' = ANUAL
        if len(curso.semestres) >= 2:
            sem_malla = curso.semestres[0] if sem_objetivo == 1 else curso.semestres[1]
        else:
            sem_malla = curso.semestres[0]
    elif curso.periodicidad in (Curso.PERIODICIDAD_CHOICES[1][0], Curso.PERIODICIDAD_CHOICES[2][0]):
        sem_malla = curso.semestres[0]
    else:
        return None, "periodicidad_invalida"

    return sem_malla, None


@transaction.atomic
def ejecutar_proyeccion_demanda(id_periodo_objetivo: int, sobrescribir: bool = True) -> ResumenProyeccion:
    resumen = ResumenProyeccion()

    periodo_proyeccion = Periodo.objects.get(id_periodo=id_periodo_objetivo)
    resumen.periodo = periodo_proyeccion

    anio_objetivo, sem_objetivo = _validar_formato_periodo(periodo_proyeccion.nombre_periodo)

    if sobrescribir:
        eliminadas_estimacion = EstimacionDemanda.objects.filter(periodo=periodo_proyeccion).delete()[0]
        eliminadas_seccion = Seccion.objects.filter(periodo=periodo_proyeccion).delete()[0]
        logger.info(
            "ProyeccionDemanda: Sobrescribiendo periodo %s - Eliminadas %d estimaciones y %d secciones.",
            periodo_proyeccion.nombre_periodo, eliminadas_estimacion, eliminadas_seccion,
        )
    else:
        if EstimacionDemanda.objects.filter(periodo=periodo_proyeccion).exists():
            raise RuntimeError(
                f"Ya existen estimaciones para el periodo '{periodo_proyeccion.nombre_periodo}'. "
                "Usa sobrescribir=True para volver a calcular."
            )

    cursos = Curso.objects.select_related("programa").all()
    resumen.total_cursos_evaluados = cursos.count()

    for curso in cursos:
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

        alumnos_proyectados = Matricula.objects.filter(
            programa=curso.programa,
            anio_ingreso=cohorte_buscada,
        ).count()

        if alumnos_proyectados <= 0:
            resumen.omitidos_sin_alumnos += 1
            resumen.total_cursos_omitidos += 1
            continue

        cupo = curso.cupo_max_seccion if curso.cupo_max_seccion and curso.cupo_max_seccion > 0 else 40
        secciones_calculadas = math.ceil(alumnos_proyectados / cupo)

        estimacion = EstimacionDemanda.objects.create(
            periodo=periodo_proyeccion,
            curso=curso,
            alumnos_proyectados=alumnos_proyectados,
            secciones_calculadas=secciones_calculadas,
        )

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
        })

    logger.info(
        "ProyeccionDemanda: Periodo %s finalizado - Procesados %d, Omitidos %d, "
        "Alumnos %d, Secciones %d, Componentes %d.",
        periodo_proyeccion.nombre_periodo, resumen.total_cursos_procesados,
        resumen.total_cursos_omitidos, resumen.alumnos_proyectados_total,
        resumen.secciones_generadas_total, resumen.componentes_generados_total,
    )

    return resumen
