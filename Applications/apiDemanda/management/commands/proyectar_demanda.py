from django.core.management.base import BaseCommand, CommandError
import sys
import codecs
import re
from Applications.apiDemanda.models import Periodo
from Applications.apiDemanda.services import ejecutar_proyeccion_demanda


_PARSE_IN = re.compile(r"^\s*(\d+)\s*=\s*(\d+)\s*$")


def _parsear_ingresos_nuevos(valor: str) -> dict[int, int]:
    """
    Parsea el string del flag --ingresos-nuevos con formato:
      "PROG_ID1=120,PROG_ID2=80, PROG_ID9=200"
    Devuelve dict[int, int] {programa_id: n_alumnos}
    """
    if not valor:
        return {}
    result = {}
    for parte in str(valor).split(","):
        parte = parte.strip()
        if not parte:
            continue
        m = _PARSE_IN.match(parte)
        if not m:
            continue
        try:
            pid = int(m.group(1))
            n = int(m.group(2))
            if n > 0:
                result[pid] = n
        except (TypeError, ValueError):
            continue
    return result


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
            help="ID del Periodo a proyectar (ej: 2). El nombre_periodo debe tener formato Banner YYYY25 o YYYY75.",
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
        parser.add_argument(
            "--ingresos-nuevos",
            type=str,
            default=None,
            required=False,
            help=(
                "Proyección de alumnos nuevos para programas VIGENTES (solo se usa si la cohorte real tiene 0). "
                'Formato: "PROG_ID1=120,PROG_ID2=80,PROG_ID9=200". '
                'Ejemplo: --ingresos-nuevos "1=150,5=90,9=200".'
            ),
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
        ingresos_raw = options.get("ingresos_nuevos")
        dict_ingresos_nuevos = _parsear_ingresos_nuevos(ingresos_raw)

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
        if dict_ingresos_nuevos:
            total_ingresos_proy = sum(dict_ingresos_nuevos.values())
            self._print(
                f" Ingresos nuevos proyectados : {len(dict_ingresos_nuevos)} programas, "
                f"{total_ingresos_proy} alumnos (override solo si cohorte real tiene 0).",
                self.style.MIGRATE_LABEL,
            )
        else:
            self._print(
                " Ingresos nuevos proyectados : NINGUNO (solo se usan matrículas REALES existentes en la BD).",
                self.style.WARNING,
            )
        self._print("=" * 70)

        try:
            resumen = ejecutar_proyeccion_demanda(
                id_periodo_objetivo=id_periodo,
                sobrescribir=sobrescribir,
                proyeccion_ingresos_nuevos=dict_ingresos_nuevos,
            )
        except ValueError as e:
            raise CommandError(f"[ERROR VALIDACION] {e}")
        except RuntimeError as e:
            raise CommandError(f"[ERROR EJECUCION] {e}")
        except Exception as e:
            raise CommandError(f"[ERROR INESPERADO] {type(e).__name__}: {e}")

        datos = resumen.to_dict()
        ingresos_input = getattr(resumen, "ingresos_proyectados_para_futuro", 0)
        self._print("")
        self._print(" === PROYECCION FINALIZADA EXITOSAMENTE ===", self.style.SUCCESS)
        self._print("")
        self._print(f" [>] Cursos evaluados        : {datos['total_cursos_evaluados']}")
        self._print(f" [>] Cursos procesados OK    : {datos['total_cursos_procesados']}", self.style.SUCCESS)
        self._print(f" [>] Cursos omitidos         : {datos['total_cursos_omitidos']}", self.style.WARNING)
        self._print(f" [>] Alumnos proyectados TOT : {datos['alumnos_proyectados_total']}")
        if ingresos_input > 0:
            self._print(
                f" [>]   · (de los cuales)     : {ingresos_input} provienen de proyección usuario (no matrícula real)",
                self.style.MIGRATE_LABEL,
            )
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
            header = f" {'CODIGO':<12} {'CURSO':<40} {'COHORTE':>7} {'ALUMNOS':>8} {'SEC':>4} {'ORIGEN':<18}"
            self._print(header)
            self._print("-" * len(header))
            for c in datos["cursos_procesados"]:
                origen = c.get("origen_alumnos", "matricula_real")
                origen_display = "PROYECCION USUARIO" if origen != "matricula_real" else "MATRICULA REAL"
                self._print(
                    f" {c['codigo']:<12} {c['nombre'][:40]:<40} {c['cohorte']:>7} "
                    f"{c['alumnos_proyectados']:>8} {c['secciones_calculadas']:>4} {origen_display:<18}"
                )

        self._print("")
