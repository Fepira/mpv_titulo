"""Puente de datos: proyección de demanda (BD) -> genes del Algoritmo Genético.

Equivale a `cargar_datos_excel()` del prototipo, pero leído desde la BD.
La construcción de genes y el cálculo de `bloques_validos` son de solo lectura;
la ejecución del AG (`ejecutar_programacion`) sí persiste el resultado.

Un "gen" = un paquete de módulos consecutivos a programar. Si un curso tiene
3 módulos semanales y no está fijo, el prototipo lo divide en 2 paquetes: [2, 1].
"""
import logging
import math
import unicodedata

from django.db import transaction
from django.db.models import Count

from Applications.apiDemanda.models import (
    AsignacionDocente,
    BolsaDetalle,
    Carrera,
    Curso,
    EstimacionDemanda,
    Periodo,
    Seccion,
)
from Applications.apiDemanda.services import _obtener_semestre_malla, _validar_formato_periodo

from . import algoritmo
from .models import (
    BloqueProgramado,
    ConfiguracionProgramacion,
    ParametrosAG,
    ProgramacionResultado,
)

logger = logging.getLogger(__name__)

# Tipo de sala por defecto si el curso no fue configurado (3 = Sala Común).
TIPO_SALA_POR_DEFECTO = 3

# Orden de días del prototipo: es la base de `bloque = dia * max_horas_edificio + modulo_0`.
DIAS_SEMANA = ['LUNES', 'MARTES', 'MIERCOLES', 'JUEVES', 'VIERNES', 'SABADO']

# Nombres de día para mostrar en la grilla.
DIAS_DISPLAY = {
    'LUNES': 'Lunes', 'MARTES': 'Martes', 'MIERCOLES': 'Miércoles',
    'JUEVES': 'Jueves', 'VIERNES': 'Viernes', 'SABADO': 'Sábado',
}

# Etiquetas de tipo de sala para el horario y el CSV.
TIPO_SALA_LABELS = dict(Curso.TIPO_SALA_CHOICES)

# Módulo máximo permitido el sábado (índice 5) cuando se programan 6 días.
MODULO_MAX_SABADO = 4

# Ventanas sugeridas cuando aún no hay configuración guardada.
VENTANA_POR_DEFECTO = {
    'OBLIGATORIA': (1, 4),
    'MENCION': (5, 8),
    'TRANSVERSAL': (1, 8),
}


def _num_seccion_desde_nrc(nrc_seccion, fallback=1):
    """Extrae el número de sección desde el NRC ('PER2351-2' -> 2)."""
    try:
        return int(str(nrc_seccion).rsplit('-', 1)[-1])
    except (TypeError, ValueError):
        return fallback


# Componentes cuyos docentes SÍ restringen el choque de profesor del AG.
# Los ayudantes (Ayudantía tipo 1/2) se ajustan al horario ya definido, por lo
# que NO participan de la verificación de choque.
COMPONENTES_CHOQUE_PROFESOR = ('teorica', 'practica')


def _normalizar_componente(nombre):
    """'Teórica' -> 'teorica' (minúsculas y sin acentos)."""
    sin_acentos = ''.join(
        c for c in unicodedata.normalize('NFKD', str(nombre or ''))
        if not unicodedata.combining(c)
    )
    return sin_acentos.lower().strip()


def _docentes_por_seccion(secciones):
    """Devuelve {id_seccion: [nombres de docente únicos y ordenados]}."""
    acumulado = {}
    filas = (
        AsignacionDocente.objects
        .filter(componente__seccion__in=secciones)
        .values_list('componente__seccion_id', 'docente__nombre_completo')
    )
    for id_seccion, nombre in filas:
        if nombre:
            acumulado.setdefault(id_seccion, set()).add(nombre)
    return {id_seccion: sorted(nombres) for id_seccion, nombres in acumulado.items()}


def _docentes_choque_por_seccion(secciones):
    """{id_seccion: [docentes de componentes teóricos/prácticos]}.

    Solo estos docentes restringen el choque de profesor; se excluyen los
    ayudantes (Ayudantía tipo 1/2).
    """
    acumulado = {}
    filas = (
        AsignacionDocente.objects
        .filter(componente__seccion__in=secciones)
        .values_list(
            'componente__seccion_id',
            'componente__componente_curso',
            'docente__nombre_completo',
        )
    )
    for id_seccion, componente, nombre in filas:
        if not nombre:
            continue
        if _normalizar_componente(componente) not in COMPONENTES_CHOQUE_PROFESOR:
            continue
        acumulado.setdefault(id_seccion, set()).add(nombre)
    return {id_seccion: sorted(nombres) for id_seccion, nombres in acumulado.items()}


def _mencion_por_curso_real():
    """{id_curso_real: id_mencion} según BolsaDetalle (solo bolsas de mención)."""
    return dict(
        BolsaDetalle.objects
        .filter(tipo_curso_bolsa='MENCION', mencion__isnull=False)
        .values_list('curso_real_id', 'mencion_id')
    )


def construir_genes_programacion(id_periodo, cant_dias=5):
    """Construye `(info_genes, cant_genes)` desde la proyección de demanda del periodo.

    Cada gen replica la estructura de la Hoja 1 del prototipo. `bloques_validos`
    queda en None: lo completa el Bloque 4 (configuración de ventanas horarias).
    """
    periodo = Periodo.objects.get(id_periodo=id_periodo)
    _, sem_objetivo = _validar_formato_periodo(periodo.nombre_periodo)

    estimaciones = {e.curso_id: e for e in EstimacionDemanda.objects.filter(periodo=periodo)}
    menciones = _mencion_por_curso_real()

    secciones = list(
        Seccion.objects
        .filter(periodo=periodo)
        .select_related('curso', 'curso__programa')
        .prefetch_related('curso__detalles_como_real')
        .order_by('curso__codigo_asignatura', 'nrc_seccion')
    )
    docentes = _docentes_por_seccion(secciones)
    docentes_choque = _docentes_choque_por_seccion(secciones)

    info_genes = []
    id_gen = 0

    for seccion_obj in secciones:
        curso = seccion_obj.curso
        estimacion = estimaciones.get(curso.id_curso)

        num_modulos = curso.num_modulos  # teóricos + prácticos + ayudantía 1
        if num_modulos <= 0:
            logger.warning(
                'Curso %s sin módulos semanales; se omite del AG.', curso.codigo_asignatura
            )
            continue

        es_fijo = bool(seccion_obj.dia_fijo) and bool(seccion_obj.modulo_inicio_fijo)

        # División 3 módulos -> [2, 1] (solo si no está fijo, igual que el prototipo).
        paquetes = [2, 1] if (num_modulos == 3 and not es_fijo) else [num_modulos]

        cohortes = list(estimacion.cohortes_involucradas) if estimacion else []
        es_transversal = not cohortes
        cohorte = 'TRANSVERSAL' if es_transversal else '|'.join(str(c) for c in cohortes)

        sem_malla, _motivo = _obtener_semestre_malla(curso, sem_objetivo)
        semestre = 0 if (es_transversal or sem_malla is None) else sem_malla

        demanda = estimacion.alumnos_proyectados if estimacion else 0
        secciones_por_curso = max(1, (estimacion.secciones_calculadas if estimacion else 1) or 1)
        alumnos_por_seccion = math.ceil(demanda / secciones_por_curso) if demanda else 0

        profesores = docentes.get(seccion_obj.id_seccion, [])
        profesor = profesores[0] if len(profesores) == 1 else ' | '.join(profesores)
        profesores_choque = docentes_choque.get(seccion_obj.id_seccion, [])

        if sem_malla is None:
            tipo_ciclicidad = 'N/A'
        elif (sem_malla % 2) == (sem_objetivo % 2):
            tipo_ciclicidad = 'COINCIDE'
        else:
            tipo_ciclicidad = 'NO_COINCIDE'

        comunes = {
            'codigo_asignatura': curso.codigo_asignatura,
            'nombre_asignatura': curso.nombre_asignatura,
            'seccion': _num_seccion_desde_nrc(seccion_obj.nrc_seccion),
            'id_seccion': seccion_obj.id_seccion,
            'cohorte': cohorte,
            'semestre': semestre,
            'tipo_sala': curso.tipo_sala or TIPO_SALA_POR_DEFECTO,
            'tipo_asignatura': curso.tipo_asignatura,
            'id_mencion': menciones.get(curso.id_curso, 0) if not es_transversal else 0,
            'id_carrera': curso.programa.carrera_id,
            'profesor': profesor,
            'profesores': profesores,
            # Solo T/P: restringen el choque de profesor del AG (excluye ayudantes).
            'profesores_choque': profesores_choque,
            'es_fijo': es_fijo,
            'dia_fijo': seccion_obj.dia_fijo,
            'modulo_inicio_fijo': seccion_obj.modulo_inicio_fijo,
            'demanda_proyectada': demanda,
            'demanda_real': 0,  # no existe fuente en BD (auditoría, se define en Bloque 5)
            'alumnos_por_seccion': alumnos_por_seccion,
            'secciones_por_curso': secciones_por_curso,
            'tipo_ciclicidad': tipo_ciclicidad,
            'lista_cruzada': curso.lista_cruzada or 'N/A',
            'bloques_validos': None,  # lo completa el Bloque 4
        }

        for tamano_paquete in paquetes:
            gen = dict(comunes, id_gen=id_gen, num_modulos=tamano_paquete)
            info_genes.append(gen)
            id_gen += 1

    return info_genes, len(info_genes)


def obtener_o_crear_configuracion(periodo):
    """Devuelve la `ConfiguracionProgramacion` del periodo, creándola si no existe."""
    configuracion, _ = ConfiguracionProgramacion.objects.get_or_create(periodo=periodo)
    return configuracion


def ventanas_por_clave(configuracion):
    """Devuelve {(semestre, tipo_asignatura): (modulo_inicio, modulo_fin)} de la configuración."""
    return {
        (ventana.semestre, ventana.tipo_asignatura): (ventana.modulo_inicio, ventana.modulo_fin)
        for ventana in configuracion.ventanas.all()
    }


def clave_ventana(gen):
    """Clave de ventana horaria de un gen.

    Un gen sin cohorte (TRANSVERSAL) o sin semestre de malla válido (semestre 0) usa
    la ventana transversal, que es la única que no depende de la malla.
    """
    if gen['cohorte'] == 'TRANSVERSAL' or gen['semestre'] == 0:
        return (0, 'TRANSVERSAL')
    return (gen['semestre'], gen['tipo_asignatura'])


def claves_ventana_requeridas(info_genes):
    """Conjunto de (semestre, tipo_asignatura) que el AG necesita para construir las jaulas."""
    return {clave_ventana(gen) for gen in info_genes}


def calcular_bloques_validos(info_genes, ventanas, cant_dias=5):
    """Completa `bloques_validos` de cada gen (in place) y devuelve `max_horas_edificio`.

    `ventanas` son intervalos de módulos en 1-based. La geometría replica al prototipo:
    `bloque = dia * max_horas_edificio + (modulo - 1)`. Una sección con fijo queda con
    una jaula de un solo casillero.
    """
    if not ventanas:
        raise ValueError('No hay ventanas horarias configuradas para este periodo.')

    max_horas_edificio = max(modulo_fin for _, modulo_fin in ventanas.values())

    faltantes = claves_ventana_requeridas(info_genes) - set(ventanas)
    if faltantes:
        detalle = ', '.join(
            f'semestre {semestre} · {tipo}' for semestre, tipo in sorted(faltantes)
        )
        raise ValueError(f'Faltan ventanas horarias para: {detalle}.')

    for gen in info_genes:
        if gen['es_fijo']:
            dia_idx = DIAS_SEMANA.index(gen['dia_fijo'])
            gen['bloques_validos'] = [
                dia_idx * max_horas_edificio + (gen['modulo_inicio_fijo'] - 1)
            ]
            continue

        modulo_inicio, modulo_fin = ventanas[clave_ventana(gen)]
        modulo_inicio_0 = modulo_inicio - 1
        modulo_fin_0 = modulo_fin - 1
        tamano_paquete = gen['num_modulos']

        bloques = []
        for dia in range(cant_dias):
            fin_dia_0 = min(modulo_fin_0, MODULO_MAX_SABADO - 1) if dia == 5 else modulo_fin_0
            if fin_dia_0 - modulo_inicio_0 + 1 < tamano_paquete:
                continue
            for slot in range(modulo_inicio_0, fin_dia_0 - tamano_paquete + 2):
                bloques.append(dia * max_horas_edificio + slot)

        gen['bloques_validos'] = bloques or [0]

    return max_horas_edificio


def cuotas_por_carrera():
    """Devuelve {id_carrera: (cuota_sala_comun, cuota_sala_propia)} para el fitness."""
    return {
        carrera.id_carrera: (carrera.cuota_sala_comun, carrera.cuota_sala_propia)
        for carrera in Carrera.objects.all()
    }


def ejecutar_programacion(periodo, progreso=None):
    """Ejecuta el AG para el periodo y persiste el resultado vigente.

    Reúne los genes, calcula la geometría de bloques con las ventanas del periodo,
    corre el motor (`algoritmo.ejecutar`) y guarda el mejor horario en
    `ProgramacionResultado` + `BloqueProgramado` (reemplaza cualquier corrida previa).

    `progreso` es un callback opcional `progreso(iteracion, mejor_fitness)`.
    Devuelve la instancia `ProgramacionResultado`.
    """
    parametros = ParametrosAG.obtener()
    info_genes, cant_genes = construir_genes_programacion(periodo.id_periodo)
    if cant_genes == 0:
        raise ValueError('El periodo no tiene secciones proyectadas: no hay nada que programar.')

    ventanas = ventanas_por_clave(obtener_o_crear_configuracion(periodo))
    max_horas_edificio = calcular_bloques_validos(info_genes, ventanas, parametros.cant_dias)

    cromosoma, mejor_fitness, iteraciones = algoritmo.ejecutar(
        info_genes,
        parametros,
        cuotas_por_carrera(),
        max_horas_edificio,
        progreso=progreso,
    )
    horario = algoritmo.decodificar_individuo(cromosoma, info_genes, parametros.cant_bin_per_gen)

    return _persistir_resultado(
        periodo, info_genes, horario, mejor_fitness, iteraciones,
        max_horas_edificio, parametros.cant_dias,
        parametros=parametros, ventanas=ventanas,
    )


def _snapshot_parametros(parametros):
    """Copia serializable de los parámetros del AG usados en una corrida."""
    return {
        'cant_dias': parametros.cant_dias,
        'cant_bin_per_gen': parametros.cant_bin_per_gen,
        'max_iteraciones': parametros.max_iteraciones,
        'cant_poblacion': parametros.cant_poblacion,
        'threshold_padres': parametros.threshold_padres,
        'prob_mutacion': parametros.prob_mutacion,
        'umbral_early_stop': parametros.umbral_early_stop,
    }


def _snapshot_ventanas(ventanas):
    """Copia serializable de las ventanas horarias vigentes al ejecutar el AG."""
    return [
        {
            'semestre': semestre,
            'tipo_asignatura': tipo,
            'modulo_inicio': inicio,
            'modulo_fin': fin,
        }
        for (semestre, tipo), (inicio, fin) in sorted(ventanas.items())
    ]


def _persistir_resultado(periodo, info_genes, horario, mejor_fitness, iteraciones,
                         max_horas_edificio, cant_dias, parametros=None, ventanas=None):
    """Guarda (atómicamente) una corrida nueva y la marca como vigente del periodo.

    La corrida anterior no se borra: queda en el historial con `es_vigente=False`.
    """
    with transaction.atomic():
        ProgramacionResultado.objects.filter(
            periodo=periodo, es_vigente=True
        ).update(es_vigente=False)
        resultado = ProgramacionResultado.objects.create(
            periodo=periodo,
            es_vigente=True,
            mejor_fitness=mejor_fitness,
            iteraciones=iteraciones,
            cant_genes=len(info_genes),
            max_horas_edificio=max_horas_edificio,
            cant_dias=cant_dias,
            parametros_snapshot=_snapshot_parametros(parametros) if parametros else {},
            ventanas_snapshot=_snapshot_ventanas(ventanas) if ventanas else [],
        )

        bloques = []
        for id_gen, casilleros in enumerate(horario):
            gen = info_genes[id_gen]
            bloque_inicio = casilleros[0]
            dia_idx, modulo_0 = divmod(bloque_inicio, max_horas_edificio)
            bloques.append(BloqueProgramado(
                resultado=resultado,
                seccion_id=gen['id_seccion'],
                id_gen=id_gen,
                dia_semana=DIAS_SEMANA[dia_idx],
                modulo_inicio=modulo_0 + 1,
                num_modulos=gen['num_modulos'],
                es_fijo=gen['es_fijo'],
            ))
        BloqueProgramado.objects.bulk_create(bloques)

    return resultado


def obtener_resultado_vigente(periodo):
    """Corrida vigente del periodo (la que muestra el horario), o None."""
    return periodo.programaciones.filter(es_vigente=True).first()


# Etiquetas legibles de los parámetros del AG guardados en cada corrida.
ETIQUETAS_PARAMETROS = [
    ('cant_dias', 'Días'),
    ('cant_bin_per_gen', 'Bits por gen'),
    ('max_iteraciones', 'Iteraciones máx.'),
    ('cant_poblacion', 'Población'),
    ('threshold_padres', 'Umbral de padres (%)'),
    ('prob_mutacion', 'Prob. de mutación'),
    ('umbral_early_stop', 'Umbral de corte'),
]


def listar_resultados(periodo):
    """Historial de corridas del periodo, con métricas y snapshots legibles."""
    corridas = list(periodo.programaciones.annotate(n_bloques=Count('bloques')))
    for corrida in corridas:
        corrida.parametros_legibles = [
            (etiqueta, corrida.parametros_snapshot.get(clave))
            for clave, etiqueta in ETIQUETAS_PARAMETROS
        ]
        corrida.ventanas_legibles = [
            (
                'Transversal' if ventana['semestre'] == 0 else f"Semestre {ventana['semestre']}",
                ventana['tipo_asignatura'],
                f"{ventana['modulo_inicio']}–{ventana['modulo_fin']}",
            )
            for ventana in corrida.ventanas_snapshot
        ]
    return corridas


def activar_resultado(resultado):
    """Marca una corrida del historial como vigente, degradando la anterior."""
    with transaction.atomic():
        ProgramacionResultado.objects.filter(
            periodo=resultado.periodo, es_vigente=True
        ).exclude(pk=resultado.pk).update(es_vigente=False)
        resultado.es_vigente = True
        resultado.save(update_fields=['es_vigente'])
    return resultado


def eliminar_resultado(resultado):
    """Elimina una corrida del historial (y sus bloques en cascada).

    Si era la vigente, promueve la corrida más reciente que quede.
    """
    periodo = resultado.periodo
    era_vigente = resultado.es_vigente
    with transaction.atomic():
        resultado.delete()
        if era_vigente:
            siguiente = periodo.programaciones.first()  # Meta.ordering = -fecha_generacion
            if siguiente is not None:
                siguiente.es_vigente = True
                siguiente.save(update_fields=['es_vigente'])


# ---------------------------------------------------------------------------
# Lectura del horario generado (visualización y exportación)
# ---------------------------------------------------------------------------

def _metadatos_secciones(periodo):
    """{id_seccion: metadatos} de las secciones programables, reutilizando los genes."""
    genes, _ = construir_genes_programacion(periodo.id_periodo)
    nrc = dict(Seccion.objects.filter(periodo=periodo).values_list('id_seccion', 'nrc_seccion'))

    metadatos = {}
    for gen in genes:
        if gen['id_seccion'] in metadatos:
            continue
        metadatos[gen['id_seccion']] = {
            'id_seccion': gen['id_seccion'],
            'nrc': nrc.get(gen['id_seccion'], ''),
            'seccion': gen['seccion'],
            'codigo': gen['codigo_asignatura'],
            'nombre': gen['nombre_asignatura'],
            'cohorte': gen['cohorte'],
            'semestre': gen['semestre'],
            'tipo_asignatura': gen['tipo_asignatura'],
            'tipo_sala': gen['tipo_sala'],
            'id_carrera': gen['id_carrera'],
            'profesores': gen['profesores'],
            'es_fijo': gen['es_fijo'],
        }
    return metadatos


def _titulo_grupo(cohorte, semestre):
    if cohorte == 'TRANSVERSAL':
        return 'Cursos transversales'
    nombre = f'Cohorte {cohorte}'
    if semestre:
        nombre += f' · Semestre {semestre}'
    return nombre


def _pasa_filtros(meta, filtros):
    if filtros.get('carrera') and meta['id_carrera'] != filtros['carrera']:
        return False
    if filtros.get('cohorte') and meta['cohorte'] != filtros['cohorte']:
        return False
    if filtros.get('profesor') and filtros['profesor'] not in meta['profesores']:
        return False
    if filtros.get('tipo_sala') and meta['tipo_sala'] != filtros['tipo_sala']:
        return False
    if filtros.get('seccion') and meta['id_seccion'] != filtros['seccion']:
        return False
    return True


def _orden_fila(fila):
    """Orden del listado plano: cohorte, semestre, asignatura, sección, día y módulo."""
    return (
        fila['cohorte'] == 'TRANSVERSAL',
        fila['cohorte'],
        fila['semestre'],
        fila['codigo'],
        fila['seccion'],
        fila['dia_idx'],
        fila['modulo'],
    )


def construir_horario(resultado, filtros=None):
    """Arma la vista del horario de un resultado del AG.

    Devuelve un dict con:
    - `dias`: nombres de día a mostrar (columnas de la grilla).
    - `max_horas`: cantidad de módulos por día (filas de la grilla).
    - `grupos`: grillas semanales agrupadas por (cohorte, semestre).
    - `filas`: listado plano (una fila por módulo) para la exportación CSV.
    - `opciones`: valores disponibles para cada filtro (según el resultado).
    - `resumen`: tarjeta resumen de la corrida.
    """
    filtros = filtros or {}
    periodo = resultado.periodo
    metadatos = _metadatos_secciones(periodo)
    carreras = dict(Carrera.objects.values_list('id_carrera', 'nombre_carrera'))

    dias = DIAS_SEMANA[:resultado.cant_dias]
    max_horas = resultado.max_horas_edificio
    secciones_resultado = set(resultado.bloques.values_list('seccion_id', flat=True))

    grupos = {}
    filas = []
    for bloque in resultado.bloques.order_by('id_gen'):
        meta = metadatos.get(bloque.seccion_id)
        if meta is None or not _pasa_filtros(meta, filtros):
            continue

        dia_idx = DIAS_SEMANA.index(bloque.dia_semana)
        clave = (meta['cohorte'], meta['semestre'])
        grupo = grupos.get(clave)
        if grupo is None:
            grupo = {
                'titulo': _titulo_grupo(meta['cohorte'], meta['semestre']),
                'cohorte': meta['cohorte'],
                'semestre': meta['semestre'],
                'secciones': {},
                'matriz': [[[] for _ in dias] for _ in range(max_horas)],
            }
            grupos[clave] = grupo
        grupo['secciones'][meta['id_seccion']] = meta

        profesor = ' | '.join(meta['profesores'])
        for k in range(bloque.num_modulos):
            modulo = bloque.modulo_inicio + k
            if modulo > max_horas:
                continue
            grupo['matriz'][modulo - 1][dia_idx].append({
                'codigo': meta['codigo'],
                'nombre': meta['nombre'],
                'seccion': meta['seccion'],
                'profesor': profesor,
                'es_fijo': meta['es_fijo'],
                'tipo_asignatura': meta['tipo_asignatura'],
                'continuacion': k > 0,
            })

            filas.append({
                'cohorte': meta['cohorte'],
                'semestre': meta['semestre'],
                'seccion': meta['seccion'],
                'nrc': meta['nrc'],
                'codigo': meta['codigo'],
                'nombre': meta['nombre'],
                'profesor': profesor,
                'tipo_sala': TIPO_SALA_LABELS.get(meta['tipo_sala'], meta['tipo_sala']),
                'carrera': carreras.get(meta['id_carrera'], ''),
                'dia': DIAS_DISPLAY.get(bloque.dia_semana, bloque.dia_semana),
                'dia_idx': dia_idx,
                'modulo': modulo,
                'es_fijo': meta['es_fijo'],
                'tipo_asignatura': meta['tipo_asignatura'],
            })

    grupos_ordenados = sorted(
        grupos.values(),
        key=lambda g: (g['cohorte'] == 'TRANSVERSAL', g['cohorte'], g['semestre']),
    )
    for grupo in grupos_ordenados:
        grupo['secciones'] = sorted(
            grupo['secciones'].values(), key=lambda m: (m['codigo'], m['seccion'])
        )

    filas.sort(key=_orden_fila)

    metas_presentes = [metadatos[s] for s in secciones_resultado if s in metadatos]
    return {
        'dias': [DIAS_DISPLAY.get(d, d) for d in dias],
        'max_horas': max_horas,
        'grupos': grupos_ordenados,
        'filas': filas,
        'opciones': _opciones_filtros(metas_presentes, carreras),
        'resumen': {
            'mejor_fitness': resultado.mejor_fitness,
            'iteraciones': resultado.iteraciones,
            'cant_genes': resultado.cant_genes,
            'total_bloques': resultado.bloques.count(),
            'max_horas_edificio': max_horas,
            'cant_dias': resultado.cant_dias,
            'fecha_generacion': resultado.fecha_generacion,
            'limpio': resultado.mejor_fitness >= 0,
            'total_secciones': len(metas_presentes),
            'total_cohortes': len({m['cohorte'] for m in metas_presentes}),
        },
    }


def _opciones_filtros(metas, carreras):
    """Valores de filtro disponibles según las secciones presentes en el resultado."""
    tipos = sorted({m['tipo_sala'] for m in metas})
    return {
        'carreras': sorted(
            {(m['id_carrera'], carreras.get(m['id_carrera'], '')) for m in metas},
            key=lambda t: t[1],
        ),
        'cohortes': sorted(
            {m['cohorte'] for m in metas}, key=lambda c: (c == 'TRANSVERSAL', c)
        ),
        'profesores': sorted({p for m in metas for p in m['profesores']}),
        'tipos_sala': [(t, TIPO_SALA_LABELS.get(t, t)) for t in tipos],
        'secciones': sorted(
            {(m['id_seccion'], f"{m['codigo']} · secc. {m['seccion']}") for m in metas},
            key=lambda t: t[1],
        ),
    }
