from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, View
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.http import JsonResponse
from django.db import models as djmodels
from django.db.models import Sum, Count, F, Prefetch, Max, Value, CharField, Case, When
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.core.paginator import Paginator
from decimal import Decimal
from .models import (
    Carrera, Periodo, EstimacionDemanda, Seccion, SeccionComponente,
    Docente, AsignacionDocente, Curso, CategoriaDocente,
)
from .services import ejecutar_proyeccion_demanda


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
    return (Decimal(modulos) * Decimal(tarifa)), modulos


COMPONENTES_BASE = [
    ('modulos_teoricos', 'Teórica'),
    ('modulos_practicos', 'Práctica'),
    ('modulos_ayudantia_1', 'Ayudantía tipo 1'),
    ('modulos_ayudantia_2', 'Ayudantía tipo 2'),
]


@login_required
def gestionar_programacion(request, id_periodo, id_curso=None):
    """
    Vista unificada (master view) para programación académica.

    - Si id_curso == None  -> MUESTRA TODOS LOS CURSOS del periodo (agrupados por curso).
    - Si id_curso != None  -> MUESTRA SOLO ESE CURSO (detalle).
    - Ambas vistas aceptan POST con las 4 acciones (agregar/eliminar seccion, asignar/desasignar docente).
    """
    periodo = get_object_or_404(Periodo, id_periodo=id_periodo)
    curso_actual = get_object_or_404(
        Curso.objects.select_related('programa'), id_curso=id_curso
    ) if id_curso else None

    redirect_url = (
        reverse('apiDemanda:gestionar_programacion_curso', kwargs={
            'id_periodo': id_periodo, 'id_curso': id_curso,
        }) if id_curso
        else reverse('apiDemanda:gestionar_programacion_periodo', kwargs={
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
                f"{modulos} mod × ${docente.categoria.tarifa_modulo:,} = ${costo:,.0f}"
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
        template_name = 'apiDemanda/gestionar_programacion.html'
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
    return render(request, 'apiDemanda/programacion_periodo.html', context)



class HomeListView(ListView):
    model = Carrera
    template_name = 'home.html'
    context_object_name = 'carreras'


@method_decorator(login_required, name='dispatch')
class ProyeccionDemandaView(View):
    template_name = 'apiDemanda/proyeccion_form.html'

    def get(self, request):
        periodos = Periodo.objects.all().annotate(
            total_estimaciones=Count('estimaciondemanda'),
            total_secciones=Count('seccion'),
        )
        context = {
            'periodos': periodos,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        try:
            id_periodo = int(request.POST.get('id_periodo') or request.GET.get('id_periodo'))
        except (TypeError, ValueError):
            error = "Debes seleccionar un periodo valido (id_periodo entero)."
            if request.headers.get('accept') == 'application/json' or request.GET.get('format') == 'json':
                return JsonResponse({'ok': False, 'error': error}, status=400)
            messages.error(request, error)
            return redirect(reverse('apiDemanda:proyeccion_demanda_form'))

        sobrescribir = request.POST.get('sobrescribir', 'si') == 'si'

        try:
            resumen = ejecutar_proyeccion_demanda(
                id_periodo_objetivo=id_periodo,
                sobrescribir=sobrescribir,
            )
        except Periodo.DoesNotExist:
            error = f"No existe el periodo con id={id_periodo}."
            if request.headers.get('accept') == 'application/json' or request.GET.get('format') == 'json':
                return JsonResponse({'ok': False, 'error': error}, status=404)
            messages.error(request, error)
            return redirect(reverse('apiDemanda:proyeccion_demanda_form'))
        except ValueError as e:
            error = f"Error de validacion: {e}"
            if request.headers.get('accept') == 'application/json' or request.GET.get('format') == 'json':
                return JsonResponse({'ok': False, 'error': error}, status=400)
            messages.error(request, error)
            return redirect(reverse('apiDemanda:proyeccion_demanda_form'))
        except RuntimeError as e:
            error = str(e)
            if request.headers.get('accept') == 'application/json' or request.GET.get('format') == 'json':
                return JsonResponse({'ok': False, 'error': error}, status=409)
            messages.error(request, error)
            return redirect(reverse('apiDemanda:proyeccion_demanda_form'))

        data = resumen.to_dict()

        if request.headers.get('accept') == 'application/json' or request.GET.get('format') == 'json':
            return JsonResponse({'ok': True, 'resumen': data}, safe=False)

        messages.success(
            request,
            f"Proyeccion exitosa: {data['total_cursos_procesados']} cursos, "
            f"{data['secciones_generadas_total']} secciones generadas."
        )
        return redirect(reverse('apiDemanda:proyeccion_resultados', kwargs={'id_periodo': id_periodo}))


@login_required
def proyeccion_resultados_view(request, id_periodo):
    periodo = get_object_or_404(Periodo, id_periodo=id_periodo)

    estimaciones = (
        EstimacionDemanda.objects
        .filter(periodo=periodo)
        .select_related('curso', 'curso__programa')
        .order_by('-alumnos_proyectados')
    )

    totales = estimaciones.aggregate(
        alumnos_total=Sum('alumnos_proyectados'),
        secciones_total=Sum('secciones_calculadas'),
    )
    total_secciones = Seccion.objects.filter(periodo=periodo).count()
    total_componentes = SeccionComponente.objects.filter(seccion__periodo=periodo).count()

    resumen = {
        'periodo': periodo,
        'cursos_con_estimacion': estimaciones.count(),
        'alumnos_total': totales['alumnos_total'] or 0,
        'secciones_total_est': totales['secciones_total'] or 0,
        'secciones_creadas': total_secciones,
        'componentes_creados': total_componentes,
    }

    if request.headers.get('accept') == 'application/json' or request.GET.get('format') == 'json':
        data = {
            'resumen': resumen,
            'estimaciones': list(estimaciones.values(
                'id_estimacion',
                'alumnos_proyectados',
                'secciones_calculadas',
                curso_id=F('curso__id_curso'),
                codigo=F('curso__codigo_asignatura'),
                nombre=F('curso__nombre_asignatura'),
                programa=F('curso__programa__nombre_programa'),
            )),
        }
        return JsonResponse(data, safe=False, json_dumps_params={'ensure_ascii': False})

    context = {
        'periodo': periodo,
        'resumen': resumen,
        'estimaciones': estimaciones,
    }
    return render(request, 'apiDemanda/proyeccion_resultados.html', context)


@login_required
@require_http_methods(["GET"])
def proyeccion_listar_periodos_api(request):
    periodos = (
        Periodo.objects.all()
        .annotate(
            n_estimaciones=Count('estimaciondemanda'),
            n_secciones=Count('seccion'),
        )
        .values('id_periodo', 'nombre_periodo', 'n_estimaciones', 'n_secciones')
    )
    return JsonResponse({'periodos': list(periodos)}, safe=False, json_dumps_params={'ensure_ascii': False})
