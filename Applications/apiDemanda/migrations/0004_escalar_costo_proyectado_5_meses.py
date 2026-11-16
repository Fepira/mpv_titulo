from django.db import migrations
from django.db.models import F

MESES_SEMESTRE = 5


def escalar_costo_proyectado(apps, schema_editor):
    """Multiplica x5 los costo_proyectado existentes (antes representaban 1 mes)."""
    AsignacionDocente = apps.get_model('apiDemanda', 'AsignacionDocente')
    AsignacionDocente.objects.filter(costo_proyectado__isnull=False).update(
        costo_proyectado=F('costo_proyectado') * MESES_SEMESTRE
    )


def revertir_costo_proyectado(apps, schema_editor):
    AsignacionDocente = apps.get_model('apiDemanda', 'AsignacionDocente')
    AsignacionDocente.objects.filter(costo_proyectado__isnull=False).update(
        costo_proyectado=F('costo_proyectado') / MESES_SEMESTRE
    )


class Migration(migrations.Migration):

    dependencies = [
        ('apiDemanda', '0003_alter_programa_options_programa_estado_and_more'),
    ]

    operations = [
        migrations.RunPython(escalar_costo_proyectado, revertir_costo_proyectado),
    ]
