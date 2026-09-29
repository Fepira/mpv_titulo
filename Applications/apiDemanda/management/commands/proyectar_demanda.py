from django.core.management.base import BaseCommand, CommandError
import sys
import codecs
from Applications.apiDemanda.models import Periodo
from Applications.apiDemanda.services import ejecutar_proyeccion_demanda


class Command(BaseCommand):
    help = (
        "Ejecuta la proyección de demanda académica para un periodo dado. "
        "Calcula alumnos por cohorte, genera EstimacionDemanda y crea Secciones + SeccionComponente."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--periodo",
            type=int,
            required=True,
            help="ID del Periodo a proyectar (ej: 2). El nombre_periodo debe tener formato YYYY10 o YYYY20.",
        )
        parser.add_argument(
            "--no-sobrescribir",
            action="store_true",
            help="Si se usa, NO sobrescribe estimaciones existentes (error si ya hay datos).",
        )
        parser.add_argument(
            "--detalle",
            action="store_true",
            help="Muestra el detalle de cada curso procesado.",
        )

    def _print(self, msg="", style=None):
        try:
            if style:
                self.stdout.write(style(str(msg)))
            else:
                self.stdout.write(str(msg))
        except UnicodeEncodeError:
            sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, errors="replace")
            if style:
                self.stdout.write(style(str(msg)))
            else:
                self.stdout.write(str(msg))

    def handle(self, *args, **options):
        id_periodo = options["periodo"]
        sobrescribir = not options["no_sobrescribir"]
        detalle = options["detalle"]

        try:
            periodo = Periodo.objects.get(id_periodo=id_periodo)
        except Periodo.DoesNotExist:
            raise CommandError(f"No existe el Periodo con id_periodo={id_periodo}.")

        self._print("=" * 70)
        self._print(
            f" INICIANDO PROYECCION DE DEMANDA"
            f"\n Periodo: #{periodo.id_periodo} - '{periodo.nombre_periodo}'"
            f"\n Sobrescribir datos existentes: {'SI' if sobrescribir else 'NO'}"
        )
        self._print("=" * 70)

        try:
            resumen = ejecutar_proyeccion_demanda(
                id_periodo_objetivo=id_periodo,
                sobrescribir=sobrescribir,
            )
        except ValueError as e:
            raise CommandError(f"[ERROR VALIDACION] {e}")
        except RuntimeError as e:
            raise CommandError(f"[ERROR EJECUCION] {e}")
        except Exception as e:
            raise CommandError(f"[ERROR INESPERADO] {type(e).__name__}: {e}")

        datos = resumen.to_dict()
        self._print("")
        self._print(" === PROYECCION FINALIZADA EXITOSAMENTE ===", self.style.SUCCESS)
        self._print("")
        self._print(f" [>] Cursos evaluados        : {datos['total_cursos_evaluados']}")
        self._print(f" [>] Cursos procesados OK    : {datos['total_cursos_procesados']}", self.style.SUCCESS)
        self._print(f" [>] Cursos omitidos         : {datos['total_cursos_omitidos']}", self.style.WARNING)
        self._print(f" [>] Alumnos proyectados TOT : {datos['alumnos_proyectados_total']}")
        self._print(f" [>] Secciones generadas     : {datos['secciones_generadas_total']}")
        self._print(f" [>] Componentes generados   : {datos['componentes_generados_total']}")
        self._print("")
        self._print("Detalle de cursos omitidos:", self.style.WARNING)
        det = datos["detalle_omitidos"]
        for motivo, valor in det.items():
            self._print(f"   - {motivo}: {valor}")

        if detalle and datos["cursos_procesados"]:
            self._print("")
            self._print("Detalle de cursos procesados:", self.style.MIGRATE_LABEL)
            header = f" {'CODIGO':<12} {'CURSO':<40} {'COHORTE':>7} {'ALUMNOS':>8} {'SECCIONES':>9}"
            self._print(header)
            self._print("-" * len(header))
            for c in datos["cursos_procesados"]:
                self._print(
                    f" {c['codigo']:<12} {c['nombre'][:40]:<40} {c['cohorte']:>7} "
                    f"{c['alumnos_proyectados']:>8} {c['secciones_calculadas']:>9}"
                )

        self._print("")
