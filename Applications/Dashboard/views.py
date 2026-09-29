from django.shortcuts import render
from django.views import View
from django.views.generic import ListView
from .models import *
# Create your views here

from django.views.generic import TemplateView
from django.db.models import Count, Sum
from .models import Curso, Programa

class DashboardAcademicoView(TemplateView):
    template_name = 'dashboard/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['total_programas'] = Programa.objects.count()
        context['total_cursos'] = Curso.objects.count()

        context['cursos_por_periodicidad'] = Curso.objects.values('periodicidad').annotate(
            total=Count('id_curso')
        )

        modulos = Curso.objects.aggregate(
            total_teoricos=Sum('modulos_teoricos'),
            total_practicos=Sum('modulos_practicos')
        )
        context['volumen_modulos'] = modulos

        context['cursos_masivos'] = Curso.objects.order_by('-cupo_max_seccion')[:5]

        return context