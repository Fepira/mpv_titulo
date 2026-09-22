from django.shortcuts import render
from django.views import View
from django.views.generic import ListView
from .models import *
# Create your views here

from django.views.generic import TemplateView
from django.db.models import Count, Sum
from .models import Curso, Programa

class DashboardAcademicoView(TemplateView):
    template_name = 'dashboard/dashboard.html'  # Apunta al HTML que crearás

    def get_context_data(self, **kwargs):
        # Llama al contexto base
        context = super().get_context_data(**kwargs)
        
        # 1. KPIs Generales
        context['total_programas'] = Programa.objects.count()
        context['total_cursos'] = Curso.objects.count()
        
        # 2. Distribución de carga académica (Útil para programar salas)
        # Agrupa los cursos por su periodicidad (Anual, Semestral, Bimestral)
        context['cursos_por_periodicidad'] = Curso.objects.values('Periodicidad').annotate(
            total=Count('id_curso')
        )
        
        # 3. Estimación de volumen de horas
        # Suma todos los módulos teóricos y prácticos activos
        modulos = Curso.objects.aggregate(
            total_teoricos=Sum('modulos_teoricos'),
            total_practicos=Sum('modulos_practicos')
        )
        context['volumen_modulos'] = modulos
        
        # 4. Top 5 Cursos Críticos (Los que exigen mayor capacidad de infraestructura)
        context['cursos_masivos'] = Curso.objects.order_by('-cupo_max_seccion')[:5]
        
        return context