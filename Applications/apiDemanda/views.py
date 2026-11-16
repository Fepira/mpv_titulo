from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, View
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.http import JsonResponse
from django.db.models import Sum, Count, F, Value, CharField, Case, When
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.contrib import messages
from datetime import date
import re
from .models import (
    Carrera, Periodo, EstimacionDemanda, Seccion, SeccionComponente,
    Programa, Matricula, BolsaDetalle,
)
from .services import ejecutar_proyeccion_demanda, _validar_formato_periodo, limpiar_proyeccion_periodo


class HomeListView(ListView):
    model = Carrera
    template_name = 'home.html'
    context_object_name = 'carreras'


_PATRON_NUEVO_INGRESO = re.compile(r"^proyeccion_nuevo_ingreso_(\d+)$")


def _construir_dict_ingresos_nuevos(post) -> dict[int, int]:
    """Desde request.POST busca las keys proyeccion_nuevo_ingreso_<PROG_ID> y devuelve dict[int,int]"""
    result: dict[int, int] = {}
    if not post:
        return result
    for key, val in post.items():
        m = _PATRON_NUEVO_INGRESO.match(str(key))
        if not m:
            continue
        try:
            pid = int(m.group(1))
            n = int(str(val or "0").strip() or 0)
            if n > 0:
                result[pid] = n
        except (TypeError, ValueError):
            continue
    return result


def _obtener_programas_vigentes_con_sugerencia(anio_periodo: int, sem_periodo_tipo: int):
    """Devuelve lista programas VIGENTES con valor sugerido (coherte anterior del año pasado n° cohorte entrante)."""
    qs = (
        Programa.objects
        .filter(estado='VIGENTE')
        .select_related('carrera')
        .order_by('carrera__nombre_carrera', 'codigo_programa', 'nombre_programa')
    )
    resultados = []
    # cohorte entrante del periodo = anio_periodo (para el curso sem 1 del tipo del periodo)
    cohorte_entrante = anio_periodo
    cohorte_anterior = cohorte_entrante - 1  # la cohorte que entró el año pasado
    for prog in qs:
        # sugerencia = alumnos de la cohorte anterior que entraron a este programa en 1er sem del tipo
        sugerencia = (
            Matricula.objects
            .filter(programa_id=prog.id_programa, anio_ingreso=cohorte_anterior)
            .count()
        )
        resultados.append({
            'id_programa': prog.id_programa,
            'nombre_programa': prog.nombre_programa,
            'codigo_programa': prog.codigo_programa,
            'version_programa': getattr(prog, 'version', None),
            'carrera_id': prog.carrera_id,
            'carrera_nombre': prog.carrera.nombre_carrera if prog.carrera else '',
            'cohorte_entrante': cohorte_entrante,
            'cohorte_anterior': cohorte_anterior,
            'valor_sugerido': sugerencia,
        })
    return resultados


@method_decorator(login_required, name='dispatch')
class ProyeccionDemandaView(View):
    """
    Vista SUPER SIMPLE (sin trucos raros):
      GET  → 1 formulario, 3 secciones: (1) Select periodo, (2) Checkbox sobrescribir,
             (3) SI anio_periodo > anio_hoy → tabla inputs alumnos nuevos x programa VIGENTE.
      POST → parsear y ejecutar proyeccion. Redirigir a resultados.
    """
    template_name = 'apiDemanda/proyeccion_form.html'

    def get(self, request):
        periodos = Periodo.objects.all().annotate(
            total_estimaciones=Count('estimaciondemanda'),
            total_secciones=Count('seccion'),
        ).order_by('-nombre_periodo')

        periodo_seleccionado = None
        programas_vigentes = []
        mostrar_tabla_ingresos = False
        anio_actual = date.today().year

        pid = request.GET.get('periodo')
        if pid and str(pid).isdigit():
            try:
                periodo_seleccionado = Periodo.objects.get(pk=int(pid))
                anio_p, sem_tipo_p = _validar_formato_periodo(periodo_seleccionado.nombre_periodo)
                # Solo mostramos tabla de ingresos nuevos si año estrictamente > actual
                # (periodo FUTURO puro: 202725 > hoy 2026, etc.)
                mostrar_tabla_ingresos = anio_p > anio_actual
                if mostrar_tabla_ingresos:
                    programas_vigentes = _obtener_programas_vigentes_con_sugerencia(anio_p, sem_tipo_p)
            except (Periodo.DoesNotExist, ValueError):
                periodo_seleccionado = None

        return render(request, self.template_name, {
            'periodos': periodos,
            'periodo_seleccionado': periodo_seleccionado,
            'mostrar_tabla_ingresos': mostrar_tabla_ingresos,
            'programas_vigentes_con_sugerencia': programas_vigentes,
            'anio_actual': anio_actual,
        })

    def post(self, request):
        pid = request.POST.get('periodo') or request.POST.get('id_periodo')
        try:
            id_periodo = int(pid)
        except (TypeError, ValueError):
            messages.error(request, "Seleccioná un período válido.")
            return redirect(reverse('apiDemanda:proyeccion_demanda_form'))

        sobrescribir = request.POST.get('sobrescribir') == 'si'
        dict_ingresos_nuevos = _construir_dict_ingresos_nuevos(request.POST)

        try:
            resumen = ejecutar_proyeccion_demanda(
                id_periodo_objetivo=id_periodo,
                sobrescribir=sobrescribir,
                proyeccion_ingresos_nuevos=dict_ingresos_nuevos,
            )
        except (Periodo.DoesNotExist, ValueError, RuntimeError) as e:
            messages.error(request, f"Error: {e}")
            return redirect(f"{reverse('apiDemanda:proyeccion_demanda_form')}?periodo={id_periodo}")

        msg = (
            f"Proyección OK: {resumen.total_cursos_procesados} cursos, "
            f"{resumen.secciones_generadas_total} secciones, "
            f"{resumen.alumnos_proyectados_total} alumnos."
        )
        if dict_ingresos_nuevos:
            n_al = sum(dict_ingresos_nuevos.values())
            msg += f" Se usaron ingresos nuevos ({n_al} alumnos)."
        messages.success(request, msg)
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

    # Origen (bolsa/mención) derivado de BolsaDetalle para los cursos estimados.
    ids_curso = [e.curso_id for e in estimaciones]
    origen_bolsa = {
        d.curso_real_id: d
        for d in (
            BolsaDetalle.objects
            .filter(curso_real_id__in=ids_curso)
            .select_related('mencion', 'curso_bolsa')
        )
    }
    for e in estimaciones:
        detalle = origen_bolsa.get(e.curso_id)
        e.es_bolsa = detalle is not None
        e.mencion_nombre = detalle.mencion.nombre if detalle and detalle.mencion else None
        e.bolsa_codigo = detalle.curso_bolsa.codigo_asignatura if detalle else None

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
def proyeccion_resultados_seleccion_view(request):
    """Landing de la barra lateral: elegir el periodo para ver sus resultados de estimación."""
    periodos = (
        Periodo.objects
        .annotate(
            n_estimaciones=Count('estimaciondemanda', distinct=True),
            n_secciones=Count('seccion', distinct=True),
        )
        .order_by('-nombre_periodo')
    )
    return render(request, 'apiDemanda/proyeccion_resultados_seleccion.html', {'periodos': periodos})


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


@login_required
@require_http_methods(["POST"])
def proyeccion_limpiar_view(request, id_periodo):
    """
    Elimina TODOS los registros de proyección para un periodo:
    AsignacionDocente → SeccionHorario → SeccionComponente → Seccion → EstimacionDemanda.

    Requiere que el POST tenga confirmación escrita:
        confirmar = "SI {nombre_periodo}
    (ej: confirmar = "SI 202725")
    """
    periodo = get_object_or_404(Periodo, id_periodo=id_periodo)
    confirmar = (request.POST.get('confirmar') or '').strip()
    esperado = f"SI {periodo.nombre_periodo}"
    redirect_url = reverse('apiDemanda:proyeccion_resultados', kwargs={'id_periodo': id_periodo})

    if confirmar != esperado:
        messages.error(
            request,
            f"⚠️  Limpieza CANCELADA: el texto de confirmación no coincide. "
            f"Esperaba '{esperado}', recibiste '{confirmar or '(vacío)'}.'"
        )
        return redirect(redirect_url)

    try:
        resumen = limpiar_proyeccion_periodo(
            id_periodo=periodo.id_periodo,
            confirmar_identidad=True,
        )
    except Exception as e:
        messages.error(
            request,
            f"[ERROR al limpiar periodo #{periodo.id_periodo}: {type(e).__name__}: {e}"
        )
        return redirect(redirect_url)

    msg_parts = [f"✅ Limpieza exitosa del periodo '{periodo.nombre_periodo}':"]
    for (etq, val) in resumen.detalles():
        msg_parts.append(f"{etq} = {val}")
    messages.success(request, " ".join(msg_parts))
    url_form = reverse('apiDemanda:proyeccion_demanda_form')
    return redirect(f"{url_form}?periodo={id_periodo}")

