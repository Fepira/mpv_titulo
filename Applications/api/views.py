from django.shortcuts import render
# Create your views here.
from django.views.generic import ListView
from .models import Carrera

class HomeListView(ListView):
    model = Carrera
    template_name = 'home.html'
    context_object_name = 'carreras'


