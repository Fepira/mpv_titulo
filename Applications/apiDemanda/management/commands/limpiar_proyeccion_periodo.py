from django.core.management.base import BaseCommand, CommandError
import sys
import codecs
from Applications.apiDemanda.models import Periodo
from Applications.apiDemanda.services import limpiar_proyeccion_periodo


class Command(BaseCommand):
    help = (
        "Elimina TODOS los registros derivados de una proyección de demanda para un PERIODO, "
        "en orden correcto para no romper FK: "
        "AsignacionDocente → SeccionHorario → SeccionComponente → Seccion → EstimacionDemanda."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--periodo",
            type=int,
            required=True,
            help="ID del Periodo a limpiar (ej: 2 para 202725).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="No borra nada: solo muestra CUÁNTOS registros se eliminarían por entidad.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Saltea la confirmación interactiva (útil para scripts). IMPLÍCITO si --dry-run.",
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
        dry_run = bool(options["dry_run"])
        auto_yes = bool(options["yes"]) or dry_run

        try:
            periodo = Periodo.objects.get(id_periodo=id_periodo)
        except Periodo.DoesNotExist:
            raise CommandError(f"No existe Periodo con id_periodo={id_periodo}.")

        # 1) Dry-run primero: mostramos números para que el usuario vea QUÉ se borraría
        resumen_preview = limpiar_proyeccion_periodo(
            id_periodo=id_periodo,
            confirmar_identidad=False,
        )

        self._print("=" * 70)
        etiqueta = "PREVISUALIZACIÓN (NO SE BORRA NADA)" if dry_run else "⚠️  BORRADO CONFIRMADO"
        self._print(
            f" LIMPIEZA DE PROYECCION DE PERIODO"
            f"\n Periodo      : #{periodo.id_periodo} - '{periodo.nombre_periodo}'"
            f"\n Modo         : {etiqueta}"
        )
        self._print("=" * 70)
        self._print("")
        self._print(" Resumen de registros:")
        max_len = max(len(etq) for (etq, _) in resumen_preview.detalles())
        for (etq, val) in resumen_preview.detalles():
            if etq.startswith("TOTAL"):
                estilo = self.style.SUCCESS if val == 0 else self.style.WARNING
                self._print("")
                self._print(f"   {etq:<{max_len}} : {val:>8d}", estilo)
            else:
                self._print(f"   · {etq:<{max_len}} : {val:>8d}")
        self._print("")

        if dry_run:
            self._print(" ✅ Modo --dry-run : NO SE MODIFICÓ NINGUNA TABLA.", self.style.SUCCESS)
            self._print("    Para ejecutar el borrado real, volver a correr SIN --dry-run.")
            return

        # Si queda NADA para borrar, terminamos temprano
        if resumen_preview.total_eliminados == 0:
            self._print(
                " ℹ️  No hay proyecciones ni secciones ni asignaciones para este periodo. "
                "Nada que borrar.",
                self.style.WARNING,
            )
            return

        # 2) Confirmación interactiva (salteable con --yes)
        if not auto_yes:
            self._print(
                "⚠️  ESTA ACCIÓN ES IRREVERSIBLE (no hay rollback más allá del punto de guardado actual).",
                self.style.WARNING,
            )
            self._print(
                f"   → Se borrarán {resumen_preview.total_eliminados} registros de 5 tablas "
                "(AsignacionDocente, SeccionHorario, SeccionComponente, Seccion, EstimacionDemanda)."
            )
            self._print(f"   → Periodo objetivo: #{periodo.id_periodo} '{periodo.nombre_periodo}'")
            try:
                confirm = input(
                    f"\n Escribí 'SI {periodo.nombre_periodo}' para confirmar, o cualquier otra cosa para cancelar: "
                ).strip()
            except (EOFError, OSError):
                confirm = ""
            esperado = f"SI {periodo.nombre_periodo}"
            if confirm != esperado:
                self._print(
                    f" ✖️  Cancelado (esperaba '{esperado}', recibí '{confirm}').",
                    self.style.ERROR,
                )
                return

        # 3) Ejecución real del borrado (dentro de @transaction.atomic)
        resumen_real = limpiar_proyeccion_periodo(
            id_periodo=id_periodo,
            confirmar_identidad=True,
        )

        self._print("")
        self._print(" === LIMPIEZA EXITOSA ===", self.style.SUCCESS)
        self._print("")
        for (etq, val) in resumen_real.detalles():
            if etq.startswith("TOTAL"):
                self._print(f"   {etq:<{max_len}} : {val:>8d}", self.style.SUCCESS)
            else:
                self._print(f"   · {etq:<{max_len}} : {val:>8d} eliminados")
        self._print("")
        self._print(
            f" ℹ️  El Periodo #{periodo.id_periodo} '{periodo.nombre_periodo}' sigue existiendo en la tabla Periodo "
            "(solo se limpiaron sus tablas hijas de proyección)."
        )
