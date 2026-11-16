from django.core.management.base import BaseCommand, CommandError

from Applications.apiDemanda.models import Periodo
from Applications.apiProgramacion.services import ejecutar_programacion


class Command(BaseCommand):
    help = (
        "Ejecuta el Algoritmo Genético de programación para un periodo y persiste "
        "el horario resultante (ProgramacionResultado + BloqueProgramado)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--periodo",
            type=int,
            required=True,
            help="ID del Periodo a programar (ej: 2).",
        )
        parser.add_argument(
            "--cada",
            type=int,
            default=0,
            help="Reportar avance cada N iteraciones (0 = sin reporte de avance).",
        )

    def handle(self, *args, **options):
        id_periodo = options["periodo"]
        cada = options["cada"]

        try:
            periodo = Periodo.objects.get(id_periodo=id_periodo)
        except Periodo.DoesNotExist:
            raise CommandError(f"No existe el Periodo con id_periodo={id_periodo}.")

        def progreso(iteracion, mejor_fitness):
            if cada and iteracion % cada == 0:
                self.stdout.write(f"  iteración {iteracion}: mejor fitness {mejor_fitness:g}")

        self.stdout.write("=" * 70)
        self.stdout.write(
            f" PROGRAMACION ACADEMICA (ALGORITMO GENETICO)"
            f"\n Periodo: #{periodo.id_periodo} - '{periodo.nombre_periodo}'"
        )
        self.stdout.write("=" * 70)

        try:
            resultado = ejecutar_programacion(periodo, progreso=progreso)
        except ValueError as exc:
            raise CommandError(f"[ERROR VALIDACION] {exc}")

        self.stdout.write("")
        self.stdout.write(" === PROGRAMACION FINALIZADA === ", self.style.SUCCESS)
        self.stdout.write(f" [>] Paquetes programados (genes) : {resultado.cant_genes}")
        self.stdout.write(f" [>] Jornada del edificio         : {resultado.max_horas_edificio} módulos/día")
        self.stdout.write(f" [>] Días programados             : {resultado.cant_dias}")
        self.stdout.write(f" [>] Iteraciones ejecutadas       : {resultado.iteraciones}")
        self.stdout.write(f" [>] Mejor fitness                : {resultado.mejor_fitness:g}")
        self.stdout.write(f" [>] Bloques persistidos          : {resultado.bloques.count()}")
        self.stdout.write(
            f" [>] Corrida (vigente)            : #{resultado.id_resultado} "
            f"({resultado.fecha_generacion:%d/%m/%Y %H:%M})"
        )
        self.stdout.write("")
