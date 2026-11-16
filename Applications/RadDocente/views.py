from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Prefetch, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from Applications.apiDemanda.models import (
    AsignacionDocente, Curso, Docente, Periodo, Seccion, SeccionComponente,
)


MODULOS_COMPONENTE_MAP = {
    'Teórica': 'modulos_teoricos',
    'Teorica': 'modulos_teoricos',
    'Práctica': 'modulos_practicos',
    'Practica': 'modulos_practicos',
    'Ayudantía tipo 1': 'modulos_ayudantia_1',
    'Ayudantia tipo 1': 'modulos_ayudantia_1',
    'Ayudantía tipo 2': 'modulos_ayudantia_2',
    'Ayudantia tipo 2': 'modulos_ayudantia_2',
}

ETIQUETA_MODULO = {
    'modulos_teoricos': ('TEO', 'Teórica'),
    'modulos_practicos': ('PRAC', 'Práctica'),
    'modulos_ayudantia_1': ('AYU1', 'Ayudantía tipo 1'),
    'modulos_ayudantia_2': ('AYU2', 'Ayudantía tipo 2'),
}

MESES_SEMESTRE = 5


def _determinar_modulos(curso: Curso, nombre_componente: str) -> int:
    key = None
    for n, k in MODULOS_COMPONENTE_MAP.items():
        if n.lower() in nombre_componente.lower():
            key = k
            break
    if not key:
        return 0
    return getattr(curso, key, 0) or 0


def _calcular_costo(docente: Docente, curso: Curso, nombre_componente: str):
    modulos = _determinar_modulos(curso, nombre_componente)
    tarifa = docente.categoria.tarifa_modulo if (docente.categoria and docente.categoria.tarifa_modulo) else 0
    return (Decimal(modulos) * Decimal(tarifa) * MESES_SEMESTRE), modulos


COMPONENTES_BASE = [
    ('modulos_teoricos', 'Teórica'),
    ('modulos_practicos', 'Práctica'),
    ('modulos_ayudantia_1', 'Ayudantía tipo 1'),
    ('modulos_ayudantia_2', 'Ayudantía tipo 2'),
]


@login_required
def gestionar_presupuesto(request, id_periodo, id_curso=None):
    """
    Vista unificada (master view) para el presupuesto docente del periodo.

    - Si id_curso == None  -> MUESTRA TODOS LOS CURSOS del periodo (agrupados por curso).
    - Si id_curso != None  -> MUESTRA SOLO ESE CURSO (detalle).
    - Ambas vistas aceptan POST con las 4 acciones (agregar/eliminar seccion, asignar/desasignar docente).
    """
    periodo = get_object_or_404(Periodo, id_periodo=id_periodo)
    curso_actual = get_object_or_404(
        Curso.objects.select_related('programa'), id_curso=id_curso
    ) if id_curso else None

    redirect_url = (
        reverse('RadDocente:presupuesto_curso', kwargs={
            'id_periodo': id_periodo, 'id_curso': id_curso,
        }) if id_curso
        else reverse('RadDocente:presupuesto_periodo', kwargs={
            'id_periodo': id_periodo,
        })
    )

    if request.method == 'POST':
        accion = request.POST.get('accion', '').strip()

        if accion == 'agregar_seccion':
            id_curso_target = request.POST.get('id_curso')
            if id_curso_target:
                curso_target = get_object_or_404(
                    Curso.objects.select_related('programa'), id_curso=id_curso_target
                )
            elif curso_actual:
                curso_target = curso_actual
            else:
                messages.error(request, "Curso no especificado para crear sección.")
                return redirect(redirect_url)

            with transaction.atomic():
                max_num = (
                    Seccion.objects
                    .filter(periodo=periodo, curso=curso_target)
                    .aggregate(n=Max('nrc_seccion'))['n']
                )
                sig_num = 1
                if max_num and '-' in str(max_num):
                    try:
                        sig_num = int(str(max_num).split('-')[-1]) + 1
                    except ValueError:
                        sig_num = Seccion.objects.filter(periodo=periodo, curso=curso_target).count() + 1
                else:
                    sig_num = Seccion.objects.filter(periodo=periodo, curso=curso_target).count() + 1

                nrc = f"{curso_target.codigo_asignatura}-{sig_num}"
                for intento in range(5):
                    try:
                        seccion = Seccion.objects.create(
                            periodo=periodo, curso=curso_target, nrc_seccion=nrc,
                        )
                        break
                    except IntegrityError:
                        sig_num += 1
                        nrc = f"{curso_target.codigo_asignatura}-{sig_num}"
                else:
                    messages.error(request, "No se pudo crear la sección (conflicto de NRC).")
                    return redirect(redirect_url)

                creados = 0
                for campo, nombre in COMPONENTES_BASE:
                    valor = getattr(curso_target, campo, None)
                    if valor and valor > 0:
                        SeccionComponente.objects.create(
                            seccion=seccion, componente_curso=nombre,
                        )
                        creados += 1

            messages.success(
                request,
                f"[{curso_target.codigo_asignatura}] Sección '{nrc}' creada. {creados} componentes generados."
            )
            return redirect(redirect_url)

        if accion == 'eliminar_seccion':
            id_seccion = request.POST.get('id_seccion')
            seccion = get_object_or_404(
                Seccion, pk=id_seccion, periodo=periodo,
            )
            nrc_name = seccion.nrc_seccion
            cod = seccion.curso.codigo_asignatura
            cnt_comp = seccion.seccioncomponente_set.count()
            cnt_asig = AsignacionDocente.objects.filter(componente__seccion=seccion).count()
            seccion.delete()
            messages.warning(
                request,
                f"[{cod}] Sección '{nrc_name}' eliminada. "
                f"({cnt_comp} componentes y {cnt_asig} asignaciones borradas)."
            )
            return redirect(redirect_url)

        if accion == 'asignar_docente':
            id_componente = request.POST.get('id_componente')
            id_docente = request.POST.get('rut_docente', '').strip()
            if not id_componente or not id_docente:
                messages.error(request, "Faltan datos: componente y/o docente (ID).")
                return redirect(redirect_url)
            componente = get_object_or_404(
                SeccionComponente, pk=id_componente,
                seccion__periodo=periodo,
            )
            docente = get_object_or_404(Docente, pk=id_docente)
            cur = componente.seccion.curso
            costo, modulos = _calcular_costo(docente, cur, componente.componente_curso)
            obj, created = AsignacionDocente.objects.update_or_create(
                componente=componente, docente=docente,
                defaults={
                    'usuario_asignador': request.user,
                    'costo_proyectado': costo,
                }
            )
            verb = "actualizada" if not created else "creada"
            messages.success(
                request,
                f"[{cur.codigo_asignatura} - {componente.seccion.nrc_seccion}] "
                f"Asignación {verb}: {docente.nombre_completo} → {componente.componente_curso}. "
                f"{modulos} mod × ${docente.categoria.tarifa_modulo:,} × {MESES_SEMESTRE} meses = ${costo:,.0f}"
            )
            return redirect(redirect_url)

        if accion == 'desasignar_docente':
            id_asignacion = request.POST.get('id_asignacion')
            asignacion = get_object_or_404(
                AsignacionDocente, pk=id_asignacion,
                componente__seccion__periodo=periodo,
            )
            cod = asignacion.componente.seccion.curso.codigo_asignatura
            nrc = asignacion.componente.seccion.nrc_seccion
            nombre = f"{asignacion.docente.nombre_completo} ({asignacion.componente.componente_curso})"
            asignacion.delete()
            messages.info(request, f"[{cod} - {nrc}] Docente desasignado: {nombre}.")
            return redirect(redirect_url)

        messages.error(request, f"Acción desconocida: '{accion}'.")
        return redirect(redirect_url)

    # --- GET ---
    qs_asigs = AsignacionDocente.objects.select_related('docente', 'docente__categoria', 'usuario_asignador')

    secciones_qs = (
        Seccion.objects
        .filter(periodo=periodo)
    )
    if curso_actual:
        secciones_qs = secciones_qs.filter(curso=curso_actual)

    secciones_qs = secciones_qs.select_related('curso', 'curso__programa').prefetch_related(
        Prefetch(
            'seccioncomponente_set',
            queryset=(
                SeccionComponente.objects
                .annotate(costo_total=Sum('asignaciones__costo_proyectado'))
                .prefetch_related(
                    Prefetch('asignaciones', queryset=qs_asigs)
                )
            ),
            to_attr='componentes',
        ),
    ).order_by('curso__codigo_asignatura', 'nrc_seccion')

    secciones_raw = list(secciones_qs)
    for s in secciones_raw:
        s.total_costo = Decimal('0')
        s.total_asignaciones = 0
        for comp in s.componentes:
            s.total_costo += comp.costo_total or Decimal('0')
            s.total_asignaciones += len(comp.asignaciones.all())

    # Agrupar por curso
    cursos_dict = {}
    for s in secciones_raw:
        cid = s.curso_id
        if cid not in cursos_dict:
            cursos_dict[cid] = {
                'curso': s.curso,
                'secciones': [],
                'total_costo': Decimal('0'),
                'total_asignaciones': 0,
            }
        cursos_dict[cid]['secciones'].append(s)
        cursos_dict[cid]['total_costo'] += s.total_costo
        cursos_dict[cid]['total_asignaciones'] += s.total_asignaciones

    cursos_agrupados = sorted(cursos_dict.values(), key=lambda x: x['curso'].codigo_asignatura)
    total_presupuesto = sum((c['total_costo'] for c in cursos_agrupados), Decimal('0'))
    total_secciones = len(secciones_raw)
    total_asignaciones = sum((c['total_asignaciones'] for c in cursos_agrupados), 0)

    periodos_all = list(Periodo.objects.all())

    docentes_options = list(
        Docente.objects
        .select_related('categoria')
        .order_by('nombre_completo')
        .values_list('id_docente', 'nombre_completo', 'categoria__nombre_categoria')
    )

    if curso_actual:
        context = {
            'periodo': periodo,
            'periodos_all': periodos_all,
            'curso': curso_actual,
            'cursos_agrupados': [cursos_dict.get(curso_actual.id_curso, {'curso': curso_actual, 'secciones': [], 'total_costo': Decimal('0'), 'total_asignaciones': 0})],
            'total_presupuesto': total_presupuesto,
            'total_cursos': 1,
            'total_secciones': total_secciones,
            'total_asignaciones': total_asignaciones,
            'docentes_options': docentes_options,
            'es_detalle_curso': True,
            'is_paginated': False,
        }
        template_name = 'RadDocente/presupuesto_curso.html'
        return render(request, template_name, context)

    # Master: todos los cursos - PAGINADO 10x10
    paginator = Paginator(cursos_agrupados, 10)
    page_num = request.GET.get('page', '1')
    try:
        page_obj = paginator.page(int(page_num) if str(page_num).isdigit() else 1)
    except Exception:
        page_obj = paginator.page(1)

    context = {
        'periodo': periodo,
        'periodos_all': periodos_all,
        'cursos_agrupados': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'is_paginated': page_obj.has_other_pages(),
        'total_presupuesto': total_presupuesto,
        'total_cursos': len(cursos_agrupados),
        'total_secciones': total_secciones,
        'total_asignaciones': total_asignaciones,
        'docentes_options': docentes_options,
        'es_detalle_curso': False,
    }
    return render(request, 'RadDocente/presupuesto_periodo.html', context)


@login_required
def seleccion_periodo_presupuesto(request):
    """Landing de la barra lateral: elegir el periodo para configurar el presupuesto RAD."""
    periodos = (
        Periodo.objects
        .annotate(
            n_estimaciones=Count('estimaciondemanda', distinct=True),
            n_secciones=Count('seccion', distinct=True),
        )
        .order_by('-nombre_periodo')
    )
    return render(request, 'RadDocente/presupuesto_seleccion.html', {'periodos': periodos})
