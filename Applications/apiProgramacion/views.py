import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from Applications.apiDemanda.models import Carrera, Curso, NombreRol, Periodo, Seccion
from Applications.apiDemanda.services import _obtener_semestre_malla, _validar_formato_periodo

from .models import ParametrosAG, ProgramacionResultado, VentanaHoraria
from .services import (
    VENTANA_POR_DEFECTO,
    activar_resultado,
    calcular_bloques_validos,
    claves_ventana_requeridas,
    construir_genes_programacion,
    construir_horario,
    ejecutar_programacion as ejecutar_programacion_ag,
    eliminar_resultado,
    listar_resultados,
    obtener_o_crear_configuracion,
    obtener_resultado_vigente,
    ventanas_por_clave,
)

# Parámetros del AG expuestos en la UI administrativa.
# (nombre del campo, etiqueta, tipo, mínimo, máximo, ayuda)
CAMPOS_PARAMETROS_AG = [
    ('cant_dias', 'Días a programar', int, 1, 6,
     'Días de la semana considerados. 5 = Lunes a Viernes.'),
    ('cant_bin_per_gen', 'Bits por gen', int, 1, None,
     'Bits del cromosoma que codifican cada paquete de módulos.'),
    ('max_iteraciones', 'Iteraciones máximas', int, 1, None,
     'Cantidad máxima de generaciones del algoritmo.'),
    ('cant_poblacion', 'Tamaño de población', int, 2, None,
     'Individuos evaluados por generación.'),
    ('threshold_padres', 'Umbral de padres (%)', int, 0, 100,
     'Porcentaje de la población que se conserva como élite reproductora.'),
    ('prob_mutacion', 'Probabilidad de mutación', float, 0, 1,
     'Probabilidad de invertir cada bit del cromosoma (0 a 1).'),
    ('umbral_early_stop', 'Umbral de corte', float, None, None,
     'Si el mejor fitness alcanza este valor, el algoritmo se detiene.'),
]


def _puede_configurar_ag(user):
    """Solo Coordinador Académico y Administrador editan la configuración global del AG."""
    return user.is_authenticated and (
        user.tiene_rol(NombreRol.ADMIN) or user.tiene_rol(NombreRol.COORDINADOR)
    )


def _etiqueta_ventana(semestre, tipo_asignatura):
    etiquetas = dict(VentanaHoraria.TIPO_ASIGNATURA_CHOICES)
    nombre_semestre = 'Transversal' if semestre == 0 else f'Semestre {semestre}'
    return f'{nombre_semestre} · {etiquetas.get(tipo_asignatura, tipo_asignatura)}'


def _etiqueta_ciclicidad(curso, sem_objetivo):
    """Indica si la paridad del semestre de malla del curso coincide con el semestre del periodo.

    Reutiliza la misma regla que la proyección de demanda (`_obtener_semestre_malla`):
    semestre de malla impar -> 1er semestre Banner, par -> 2do semestre Banner.
    Devuelve 'Coincide' / 'No coincide' / None (si el curso no tiene semestre de malla válido).
    """
    sem_malla, motivo = _obtener_semestre_malla(curso, sem_objetivo)
    if sem_malla is None:
        return None
    return 'Coincide' if (sem_malla % 2) == (sem_objetivo % 2) else 'No coincide'


@login_required
def programacion_seleccion(request):
    """Landing de la barra lateral: elegir el periodo a programar."""
    periodos = (
        Periodo.objects
        .annotate(
            n_estimaciones=Count('estimaciondemanda', distinct=True),
            n_secciones=Count('seccion', distinct=True),
        )
        .order_by('-nombre_periodo')
    )
    return render(request, 'apiProgramacion/programacion_seleccion.html', {'periodos': periodos})


@login_required
def configuracion_periodo(request, id_periodo):
    """Lista los cursos con secciones creadas en el periodo y su estado de configuración."""
    periodo = get_object_or_404(Periodo, id_periodo=id_periodo)
    _, sem_objetivo = _validar_formato_periodo(periodo.nombre_periodo)

    secciones = (
        Seccion.objects
        .filter(periodo=periodo)
        .select_related('curso', 'curso__programa')
        .prefetch_related('curso__detalles_como_real')
        .order_by('curso__codigo_asignatura', 'nrc_seccion')
    )

    cursos_dict = {}
    for seccion in secciones:
        entrada = cursos_dict.get(seccion.curso_id)
        if entrada is None:
            entrada = cursos_dict[seccion.curso_id] = {'curso': seccion.curso, 'secciones': []}
        entrada['secciones'].append(seccion)

    cursos = []
    for entrada in cursos_dict.values():
        curso = entrada['curso']
        secciones_curso = entrada['secciones']
        pendientes = sum(
            1 for s in secciones_curso if not (s.dia_fijo and s.modulo_inicio_fijo)
        )
        cursos.append({
            'curso': curso,
            'num_secciones': len(secciones_curso),
            'tipo_asignatura': curso.tipo_asignatura,
            'num_modulos': curso.num_modulos,
            'ciclicidad': _etiqueta_ciclicidad(curso, sem_objetivo),
            'pendientes': pendientes,
        })
    cursos.sort(key=lambda c: c['curso'].codigo_asignatura)

    contexto = {
        'periodo': periodo,
        'cursos': cursos,
        'total_cursos': len(cursos),
        'total_secciones': len(secciones),
        'total_pendientes': sum(c['pendientes'] for c in cursos),
        'periodos_all': Periodo.objects.all(),
        'puede_configurar_ag': _puede_configurar_ag(request.user),
        'ventanas_configuradas': VentanaHoraria.objects.filter(configuracion__periodo=periodo).exists(),
        'resultado': obtener_resultado_vigente(periodo),
        'total_programaciones': periodo.programaciones.count(),
    }
    return render(request, 'apiProgramacion/configuracion_periodo.html', contexto)


@login_required
def configuracion_curso(request, id_periodo, id_curso):
    """Formulario de configuración de un curso: tipo de sala, lista cruzada y fijos por sección."""
    periodo = get_object_or_404(Periodo, id_periodo=id_periodo)
    _, sem_objetivo = _validar_formato_periodo(periodo.nombre_periodo)
    curso = get_object_or_404(
        Curso.objects.select_related('programa').prefetch_related('detalles_como_real'),
        id_curso=id_curso,
    )
    secciones = (
        Seccion.objects
        .filter(periodo=periodo, curso=curso)
        .annotate(num_componentes=Count('seccioncomponente'))
        .order_by('nrc_seccion')
    )

    contexto = {
        'periodo': periodo,
        'curso': curso,
        'secciones': secciones,
        'tipos_sala': Curso.TIPO_SALA_CHOICES,
        'dias': Seccion.DIA_SEMANA_CHOICES,
        'tipo_asignatura': curso.tipo_asignatura,
        'num_modulos': curso.num_modulos,
        'ciclicidad': _etiqueta_ciclicidad(curso, sem_objetivo),
        'periodos_all': Periodo.objects.all(),
    }
    return render(request, 'apiProgramacion/configuracion_curso.html', contexto)


@login_required
@require_http_methods(['POST'])
def guardar_configuracion_curso(request, id_periodo, id_curso):
    """Guarda (PRG) la configuración persistente del curso y los fijos de sus secciones."""
    periodo = get_object_or_404(Periodo, id_periodo=id_periodo)
    curso = get_object_or_404(Curso, id_curso=id_curso)
    url_curso = reverse('apiProgramacion:configuracion_curso', kwargs={
        'id_periodo': id_periodo, 'id_curso': id_curso,
    })

    # --- Campos persistentes del curso ---
    tipo_sala_raw = (request.POST.get('tipo_sala') or '').strip()
    valores_sala = {str(valor) for valor, _ in Curso.TIPO_SALA_CHOICES}
    if tipo_sala_raw == '':
        curso.tipo_sala = None
    elif tipo_sala_raw in valores_sala:
        curso.tipo_sala = int(tipo_sala_raw)
    else:
        messages.error(request, f"Tipo de sala inválido: '{tipo_sala_raw}'.")
        return redirect(url_curso)

    curso.lista_cruzada = (request.POST.get('lista_cruzada') or '').strip()[:50]
    curso.save(update_fields=['tipo_sala', 'lista_cruzada'])

    # --- Fijos por sección (Hoja 2) ---
    dias_validos = {valor for valor, _ in Seccion.DIA_SEMANA_CHOICES}
    actualizadas = 0
    for seccion in Seccion.objects.filter(periodo=periodo, curso=curso):
        dia = (request.POST.get(f'dia_fijo_{seccion.id_seccion}') or '').strip()
        modulo_raw = (request.POST.get(f'modulo_inicio_fijo_{seccion.id_seccion}') or '').strip()

        modulo = None
        if dia in dias_validos and modulo_raw:
            try:
                modulo = int(modulo_raw)
                if modulo < 1:
                    modulo = None
            except ValueError:
                modulo = None
        if modulo is None:
            dia = ''

        if seccion.dia_fijo != dia or seccion.modulo_inicio_fijo != modulo:
            seccion.dia_fijo = dia
            seccion.modulo_inicio_fijo = modulo
            seccion.save(update_fields=['dia_fijo', 'modulo_inicio_fijo'])
            actualizadas += 1

    messages.success(
        request,
        f"Configuración guardada para {curso.codigo_asignatura}: "
        f"{actualizadas} sección(es) actualizada(s)."
    )
    return redirect(url_curso)


@login_required
@user_passes_test(_puede_configurar_ag)
@require_http_methods(['POST'])
def ejecutar_programacion(request, id_periodo):
    """Ejecuta el Algoritmo Genético del periodo y persiste el horario resultante (PRG)."""
    periodo = get_object_or_404(Periodo, id_periodo=id_periodo)
    url_origen = reverse(
        'apiProgramacion:configuracion_periodo', kwargs={'id_periodo': id_periodo}
    )

    try:
        resultado = ejecutar_programacion_ag(periodo)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(url_origen)

    messages.success(
        request,
        f'Programación generada: {resultado.cant_genes} paquete(s) en '
        f'{resultado.bloques.count()} bloque(s), fitness {resultado.mejor_fitness:g} '
        f'en {resultado.iteraciones} iteración(es).'
    )
    return redirect(url_origen)


# Columnas del CSV de horario: (título, campo de la fila).
COLUMNAS_CSV_HORARIO = [
    ('Cohorte', 'cohorte'),
    ('Semestre', 'semestre'),
    ('Seccion', 'seccion'),
    ('NRC', 'nrc'),
    ('Codigo', 'codigo'),
    ('Asignatura', 'nombre'),
    ('Profesor', 'profesor'),
    ('Carrera', 'carrera'),
    ('Tipo_Sala', 'tipo_sala'),
    ('Dia', 'dia'),
    ('Modulo', 'modulo'),
    ('Fijo', 'es_fijo'),
    ('Tipo_Asignatura', 'tipo_asignatura'),
]


def _entero_o_none(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _leer_filtros(get):
    """Lee los filtros del horario; campo vacío = sin filtro."""
    return {
        'carrera': _entero_o_none(get.get('carrera')),
        'cohorte': get.get('cohorte', '').strip(),
        'profesor': get.get('profesor', '').strip(),
        'tipo_sala': _entero_o_none(get.get('tipo_sala')),
        'seccion': _entero_o_none(get.get('seccion')),
    }


def _resultado_o_redirigir(request, periodo, id_resultado=None):
    """Devuelve la corrida a mostrar o redirige si el periodo aún no tiene programación.

    Sin `id_resultado` se usa la corrida vigente; con él, la corrida indicada del
    historial (solo si pertenece al periodo).
    """
    resultado = None
    if id_resultado:
        resultado = periodo.programaciones.filter(pk=id_resultado).first()
    if resultado is None:
        resultado = obtener_resultado_vigente(periodo)
    if resultado is None:
        messages.info(request, 'El periodo aún no tiene una programación generada.')
    return resultado


@login_required
def horario_programado(request, id_periodo):
    """Grilla semanal del horario generado por el AG (con filtros)."""
    periodo = get_object_or_404(Periodo, id_periodo=id_periodo)
    resultado = _resultado_o_redirigir(request, periodo, _entero_o_none(request.GET.get('resultado')))
    if resultado is None:
        return redirect('apiProgramacion:configuracion_periodo', id_periodo=id_periodo)

    contexto = {
        'periodo': periodo,
        'horario': construir_horario(resultado, _leer_filtros(request.GET)),
        'filtros': _leer_filtros(request.GET),
        'querystring': request.GET.urlencode(),
        'periodos_all': Periodo.objects.all(),
        'puede_configurar_ag': _puede_configurar_ag(request.user),
        'resultado': resultado,
        'total_programaciones': periodo.programaciones.count(),
    }
    return render(request, 'apiProgramacion/horario_programado.html', contexto)


@login_required
def exportar_horario_csv(request, id_periodo):
    """Descarga el horario del periodo en CSV aplicando los mismos filtros."""
    periodo = get_object_or_404(Periodo, id_periodo=id_periodo)
    resultado = _resultado_o_redirigir(request, periodo, _entero_o_none(request.GET.get('resultado')))
    if resultado is None:
        return redirect('apiProgramacion:configuracion_periodo', id_periodo=id_periodo)

    horario = construir_horario(resultado, _leer_filtros(request.GET))

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = (
        f'attachment; filename="horario_{periodo.nombre_periodo}_{resultado.id_resultado}.csv"'
    )
    response.write('\ufeff')  # BOM para que Excel reconozca UTF-8
    writer = csv.writer(response, delimiter=';')
    writer.writerow([titulo for titulo, _ in COLUMNAS_CSV_HORARIO])
    for fila in horario['filas']:
        writer.writerow([
            ('Sí' if fila[campo] else 'No') if campo == 'es_fijo' else fila[campo]
            for _, campo in COLUMNAS_CSV_HORARIO
        ])
    return response


@login_required
def historial_programacion(request, id_periodo):
    """Historial de corridas del AG del periodo, para compararlas."""
    periodo = get_object_or_404(Periodo, id_periodo=id_periodo)
    contexto = {
        'periodo': periodo,
        'programaciones': listar_resultados(periodo),
        'periodos_all': Periodo.objects.all(),
        'puede_configurar_ag': _puede_configurar_ag(request.user),
        'codigo_confirmacion': f'SI {periodo.nombre_periodo}',
    }
    return render(request, 'apiProgramacion/historial_programacion.html', contexto)


@login_required
@user_passes_test(_puede_configurar_ag)
@require_http_methods(['POST'])
def activar_programacion(request, id_resultado):
    """Marca una corrida del historial como la vigente del periodo (PRG)."""
    resultado = get_object_or_404(
        ProgramacionResultado.objects.select_related('periodo'), pk=id_resultado
    )
    activar_resultado(resultado)
    messages.success(
        request,
        f'Corrida del {resultado.fecha_generacion:%d/%m/%Y %H:%M} marcada como vigente '
        f'(fitness {resultado.mejor_fitness:g}).'
    )
    return redirect('apiProgramacion:historial_programacion', id_periodo=resultado.periodo_id)


@login_required
@user_passes_test(_puede_configurar_ag)
@require_http_methods(['POST'])
def eliminar_programacion(request, id_resultado):
    """Elimina una corrida del historial, previa confirmación escrita (PRG)."""
    resultado = get_object_or_404(
        ProgramacionResultado.objects.select_related('periodo'), pk=id_resultado
    )
    periodo = resultado.periodo
    url_historial = reverse(
        'apiProgramacion:historial_programacion', kwargs={'id_periodo': periodo.id_periodo}
    )

    esperado = f'SI {periodo.nombre_periodo}'
    confirmar = (request.POST.get('confirmar') or '').strip()
    if confirmar != esperado:
        messages.error(
            request,
            f'Eliminación CANCELADA: el texto de confirmación no coincide. '
            f"Esperaba '{esperado}', recibiste '{confirmar or '(vacío)'}'."
        )
        return redirect(url_historial)

    descripcion = (
        f'{resultado.fecha_generacion:%d/%m/%Y %H:%M} '
        f'(fitness {resultado.mejor_fitness:g}, {resultado.bloques.count()} bloque(s))'
    )
    era_vigente = resultado.es_vigente
    eliminar_resultado(resultado)
    extra = ' Se promovió la corrida más reciente como vigente.' if era_vigente else ''
    messages.success(request, f'Corrida eliminada: {descripcion}.{extra}')
    return redirect(url_historial)


@login_required
def parametros_periodo(request, id_periodo):
    """Ventanas horarias del periodo: qué módulos puede usar cada semestre y tipo de asignatura."""
    periodo = get_object_or_404(Periodo, id_periodo=id_periodo)
    configuracion = obtener_o_crear_configuracion(periodo)

    info_genes, _cant_genes = construir_genes_programacion(periodo.id_periodo)
    guardadas = ventanas_por_clave(configuracion)

    filas = []
    for clave in sorted(claves_ventana_requeridas(info_genes), key=lambda c: (c[0] == 0, c[0], c[1])):
        semestre, tipo = clave
        inicio, fin = guardadas.get(clave, VENTANA_POR_DEFECTO[tipo])
        filas.append({
            'semestre': semestre,
            'tipo': tipo,
            'nombre_tipo': dict(VentanaHoraria.TIPO_ASIGNATURA_CHOICES)[tipo],
            'modulo_inicio': inicio,
            'modulo_fin': fin,
            'configurada': clave in guardadas,
        })

    # Vista previa de la geometría resultante (no persiste nada).
    max_horas_edificio = None
    error_ventanas = None
    if guardadas:
        try:
            max_horas_edificio = calcular_bloques_validos(
                info_genes, guardadas, ParametrosAG.obtener().cant_dias
            )
        except ValueError as exc:
            error_ventanas = str(exc)

    contexto = {
        'periodo': periodo,
        'filas': filas,
        'total_genes': len(info_genes),
        'total_ventanas': len(guardadas),
        'max_horas_edificio': max_horas_edificio,
        'error_ventanas': error_ventanas,
        'periodos_all': Periodo.objects.all(),
        'puede_configurar_ag': _puede_configurar_ag(request.user),
    }
    return render(request, 'apiProgramacion/parametros_periodo.html', contexto)


@login_required
@require_http_methods(['POST'])
@transaction.atomic
def guardar_parametros(request, id_periodo):
    """Guarda (PRG) las ventanas horarias del periodo."""
    periodo = get_object_or_404(Periodo, id_periodo=id_periodo)
    url_parametros = reverse(
        'apiProgramacion:parametros_periodo', kwargs={'id_periodo': id_periodo}
    )

    info_genes, _cant_genes = construir_genes_programacion(periodo.id_periodo)
    claves = sorted(claves_ventana_requeridas(info_genes), key=lambda c: (c[0] == 0, c[0], c[1]))

    ventanas = []
    errores = []
    for semestre, tipo in claves:
        etiqueta = _etiqueta_ventana(semestre, tipo)
        inicio_raw = (request.POST.get(f'inicio__{semestre}__{tipo}') or '').strip()
        fin_raw = (request.POST.get(f'fin__{semestre}__{tipo}') or '').strip()
        try:
            inicio, fin = int(inicio_raw), int(fin_raw)
        except ValueError:
            errores.append(f'{etiqueta}: ingresa números enteros.')
            continue
        if inicio < 1 or inicio > fin:
            errores.append(f'{etiqueta}: el rango debe cumplir 1 ≤ inicio ≤ fin.')
            continue
        ventanas.append({
            'semestre': semestre,
            'tipo_asignatura': tipo,
            'modulo_inicio': inicio,
            'modulo_fin': fin,
        })

    if errores:
        for error in errores:
            messages.error(request, error)
        return redirect(url_parametros)

    if not ventanas:
        messages.warning(request, 'Este periodo no tiene cursos proyectados: no hay ventanas que configurar.')
        return redirect(url_parametros)

    configuracion = obtener_o_crear_configuracion(periodo)
    configuracion.ventanas.all().delete()
    VentanaHoraria.objects.bulk_create([
        VentanaHoraria(configuracion=configuracion, **ventana) for ventana in ventanas
    ])

    messages.success(request, f'Se guardaron {len(ventanas)} ventana(s) horaria(s).')
    return redirect(url_parametros)


@login_required
@user_passes_test(_puede_configurar_ag)
def parametros_ag(request):
    """Configuración global del Algoritmo Genético y cuotas de sala por carrera."""
    parametros = ParametrosAG.obtener()
    campos = [
        {
            'nombre': nombre,
            'etiqueta': etiqueta,
            'ayuda': ayuda,
            'valor': getattr(parametros, nombre),
            'paso': '0.01' if tipo is float else '1',
        }
        for nombre, etiqueta, tipo, _minimo, _maximo, ayuda in CAMPOS_PARAMETROS_AG
    ]

    contexto = {
        'campos': campos,
        'carreras': Carrera.objects.order_by('nombre_carrera'),
    }
    return render(request, 'apiProgramacion/parametros_ag.html', contexto)


@login_required
@user_passes_test(_puede_configurar_ag)
@require_http_methods(['POST'])
@transaction.atomic
def guardar_parametros_ag(request):
    """Guarda (PRG) los parámetros globales del AG y las cuotas de sala por carrera."""
    url_parametros = reverse('apiProgramacion:parametros_ag')
    errores = []

    cambios = {}
    for nombre, etiqueta, tipo, minimo, maximo, _ayuda in CAMPOS_PARAMETROS_AG:
        raw = (request.POST.get(nombre) or '').strip()
        try:
            valor = tipo(raw)
        except ValueError:
            errores.append(f'{etiqueta}: valor inválido.')
            continue
        if (minimo is not None and valor < minimo) or (maximo is not None and valor > maximo):
            errores.append(f'{etiqueta}: debe estar entre {minimo} y {maximo}.')
            continue
        cambios[nombre] = valor

    carreras = list(Carrera.objects.order_by('nombre_carrera'))
    cuotas = {}
    for carrera in carreras:
        for sufijo, campo in (('comun', 'cuota_sala_comun'), ('propia', 'cuota_sala_propia')):
            raw = (request.POST.get(f'cuota_{sufijo}_{carrera.id_carrera}') or '').strip()
            try:
                valor = int(raw)
            except ValueError:
                errores.append(f'{carrera.nombre_carrera} · cuota {sufijo}: entero inválido.')
                continue
            if valor < 0:
                errores.append(f'{carrera.nombre_carrera} · cuota {sufijo}: no puede ser negativa.')
                continue
            cuotas[(carrera.id_carrera, campo)] = valor

    if errores:
        for error in errores:
            messages.error(request, error)
        return redirect(url_parametros)

    parametros = ParametrosAG.obtener()
    for nombre, valor in cambios.items():
        setattr(parametros, nombre, valor)
    parametros.save()

    for carrera in carreras:
        carrera.cuota_sala_comun = cuotas[(carrera.id_carrera, 'cuota_sala_comun')]
        carrera.cuota_sala_propia = cuotas[(carrera.id_carrera, 'cuota_sala_propia')]
    Carrera.objects.bulk_update(carreras, ['cuota_sala_comun', 'cuota_sala_propia'])

    messages.success(request, 'Parámetros del AG y cuotas de sala actualizados.')
    return redirect(url_parametros)
