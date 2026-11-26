from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import F, Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from Applications.apiDemanda.models import (
    AsignacionDocente,
    Carrera,
    EstimacionDemanda,
    Periodo,
    Seccion,
    SeccionComponente,
)
from Applications.apiProgramacion.models import (
    BloqueProgramado,
    EstadoProgramacionPeriodo,
    ProgramacionResultado,
)

# Tipo de sala considerado para la métrica de ocupación de salas comunes.
TIPO_SALA_COMUN = 3

# Etiqueta + clases Tailwind del badge según el estado de cada etapa.
ESTADOS = {
    'completo': ('Completo', 'bg-facultad-green/20 text-green-800 border-facultad-green'),
    'listo': ('Listo', 'bg-facultad-green/20 text-green-800 border-facultad-green'),
    'parcial': ('Parcial', 'bg-amber-100 text-amber-800 border-amber-300'),
    'pendiente': ('Pendiente', 'bg-uft-light text-uft-gray border-uft-light'),
    'riesgo': ('Sobrepaso', 'bg-red-100 text-red-700 border-red-300'),
}


def _puede_ver_dashboard(user):
    """El Dashboard solo es visible para el Administrador (superuser) o la DOAE."""
    return user.is_authenticated and user.puede_ver_dashboard


def _clasificar(cobertura, total):
    """Clasifica un avance en completo/parcial/pendiente."""
    if total <= 0 or cobertura <= 0:
        return 'pendiente'
    if cobertura >= total:
        return 'completo'
    return 'parcial'


def _badge(clave):
    etiqueta, clases = ESTADOS.get(clave, ESTADOS['pendiente'])
    return {'clave': clave, 'etiqueta': etiqueta, 'clases': clases}


def _etapa_demanda(periodo, carrera):
    """Cursos y secciones proyectadas para el periodo."""
    estimaciones = EstimacionDemanda.objects.filter(
        periodo=periodo, curso__programa__carrera=carrera,
    )
    cursos_proyectados = estimaciones.values('curso_id').distinct().count()
    secciones_proyectadas = estimaciones.aggregate(s=Sum('secciones_calculadas'))['s'] or 0
    secciones_creadas = Seccion.objects.filter(
        periodo=periodo, curso__programa__carrera=carrera,
    ).count()

    return {
        'cursos_proyectados': cursos_proyectados,
        'secciones_proyectadas': secciones_proyectadas,
        'secciones_creadas': secciones_creadas,
        'estado': _badge('completo' if cursos_proyectados > 0 else 'pendiente'),
    }


def _etapa_presupuesto(periodo, carrera):
    """Costo total por código de programa y cobertura de componentes asignados."""
    secciones = Seccion.objects.filter(periodo=periodo, curso__programa__carrera=carrera)
    componentes = SeccionComponente.objects.filter(seccion__in=secciones)
    componentes_total = componentes.count()
    componentes_asignados = componentes.filter(asignaciones__isnull=False).distinct().count()

    por_programa = list(
        AsignacionDocente.objects
        .filter(
            componente__seccion__periodo=periodo,
            componente__seccion__curso__programa__carrera=carrera,
        )
        .values(codigo=F('componente__seccion__curso__programa__codigo_programa'))
        .annotate(total=Sum('costo_proyectado'))
        .order_by('codigo')
    )
    total_presupuesto = sum((fila['total'] or 0) for fila in por_programa)

    return {
        'total': total_presupuesto,
        'por_programa': por_programa,
        'componentes_total': componentes_total,
        'componentes_asignados': componentes_asignados,
        'estado': _badge(_clasificar(componentes_asignados, componentes_total)),
    }


def _ocupacion_sala_comun(resultado, secciones):
    """Ocupación media por casillero (día × módulo) de las secciones de Sala Común.

    Recorre los bloques del AG de los cursos tipo_sala=3 y cuenta cuántas secciones
    ocupan cada casillero; el promedio se compara luego con la cuota de la carrera.
    """
    if resultado is None:
        return {'media': 0, 'casilleros': 0}

    bloques = BloqueProgramado.objects.filter(
        resultado=resultado,
        seccion__in=secciones,
        seccion__curso__tipo_sala=TIPO_SALA_COMUN,
    ).values_list('dia_semana', 'modulo_inicio', 'num_modulos')

    ocupacion = {}
    for dia, modulo_inicio, num_modulos in bloques:
        for modulo in range(modulo_inicio, modulo_inicio + num_modulos):
            ocupacion[(dia, modulo)] = ocupacion.get((dia, modulo), 0) + 1

    total_ocupaciones = sum(ocupacion.values())
    casilleros = max(resultado.cant_dias, 1) * max(resultado.max_horas_edificio, 1)
    media = total_ocupaciones / casilleros if casilleros else 0
    return {'media': media, 'casilleros': casilleros}


def _etapa_programacion(periodo, carrera):
    """Cobertura de programación, ocupación de salas comunes y estado de 'listo'."""
    resultado = ProgramacionResultado.objects.filter(
        periodo=periodo, es_vigente=True,
    ).first()

    secciones = Seccion.objects.filter(periodo=periodo, curso__programa__carrera=carrera)
    secciones_total = secciones.count()
    cursos_total = secciones.values('curso_id').distinct().count()

    if resultado is not None:
        bloques = BloqueProgramado.objects.filter(resultado=resultado, seccion__in=secciones)
        secciones_programadas = bloques.values('seccion_id').distinct().count()
        cursos_programados = bloques.values('seccion__curso_id').distinct().count()
    else:
        secciones_programadas = 0
        cursos_programados = 0

    # Ocupación de salas comunes vs cuota de la carrera.
    cuota = carrera.cuota_sala_comun or 0
    ocupacion = _ocupacion_sala_comun(resultado, secciones)
    media = ocupacion['media']
    ratio_pct = int(round((media / cuota) * 100)) if cuota else 0
    sobrepaso = cuota > 0 and media > cuota

    simulaciones = ProgramacionResultado.objects.filter(periodo=periodo).count()

    estado_prog = EstadoProgramacionPeriodo.objects.filter(periodo=periodo).first()
    marcado_listo = bool(estado_prog and estado_prog.esta_lista)
    listo = marcado_listo or (resultado is not None)

    return {
        'cursos_total': cursos_total,
        'cursos_programados': cursos_programados,
        'secciones_total': secciones_total,
        'secciones_programadas': secciones_programadas,
        'simulaciones': simulaciones,
        'hay_corrida': resultado is not None,
        'resultado': resultado,
        'media_uso': round(media, 2),
        'cuota': cuota,
        'ratio_pct': ratio_pct,
        'sobrepaso': sobrepaso,
        'marcado_listo': marcado_listo,
        'marcado_por': estado_prog.marcado_por if estado_prog else None,
        'fecha_marcado': estado_prog.fecha_marcado if estado_prog else None,
        'listo': listo,
        'estado': _badge('listo' if listo else _clasificar(secciones_programadas, secciones_total)),
        'estado_ocupacion': _badge('riesgo' if sobrepaso else 'completo'),
    }


@login_required
def dashboard(request):
    """Checklist de la carrera piloto: demanda, presupuesto y programación.

    Visible solo para Administrador (superuser) o DOAE. Permite elegir el
    periodo y marcar/quitar el estado 'listo' de la programación.
    """
    if not _puede_ver_dashboard(request.user):
        raise PermissionDenied

    periodos = list(Periodo.objects.order_by('-nombre_periodo'))

    id_periodo = request.GET.get('periodo') or request.POST.get('periodo')
    periodo = None
    if id_periodo and str(id_periodo).isdigit():
        periodo = Periodo.objects.filter(pk=id_periodo).first()
    if periodo is None:
        periodo = periodos[0] if periodos else None

    carrera = Carrera.objects.first()

    if request.method == 'POST' and periodo is not None:
        accion = request.POST.get('accion', '')
        if accion in ('marcar_listo', 'desmarcar_listo'):
            estado, _ = EstadoProgramacionPeriodo.objects.get_or_create(periodo=periodo)
            if accion == 'marcar_listo':
                estado.esta_lista = True
                estado.marcado_por = request.user
                estado.fecha_marcado = timezone.now()
                estado.save()
                messages.success(
                    request,
                    f"Programación {periodo.nombre_periodo} marcada como LISTA.",
                )
            else:
                estado.esta_lista = False
                estado.marcado_por = None
                estado.fecha_marcado = None
                estado.save()
                messages.info(
                    request,
                    f"Se quitó el estado 'listo' de la programación {periodo.nombre_periodo}.",
                )
            return redirect(f"{reverse('dashboard')}?periodo={periodo.id_periodo}")
        messages.error(request, f"Acción desconocida: '{accion}'.")
        return redirect(f"{reverse('dashboard')}?periodo={periodo.id_periodo}")

    context = {
        'periodos': periodos,
        'periodo': periodo,
        'carrera': carrera,
    }

    if periodo is not None and carrera is not None:
        context['demanda'] = _etapa_demanda(periodo, carrera)
        context['presupuesto'] = _etapa_presupuesto(periodo, carrera)
        context['programacion'] = _etapa_programacion(periodo, carrera)

    return render(request, 'dashboard/dashboard.html', context)
