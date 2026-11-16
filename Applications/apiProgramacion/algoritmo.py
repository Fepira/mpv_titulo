"""Núcleo del Algoritmo Genético de programación académica.

Porte del prototipo `ALGORITMO_GENETICO_COHORTES_CUOTA_PROFESORES_MOD_FIJOS.PY`.
Es un motor puro (sin acceso a BD): recibe los genes ya construidos y con
`bloques_validos` calculados, y devuelve la mejor asignación de bloques por gen.

Un "gen" = un paquete de módulos consecutivos de una sección. Las reglas de
agrupación se resuelven al construir los genes (services.construir_genes_programacion):
- 2 módulos -> un paquete de 2 (siempre juntos).
- 3 módulos -> paquetes [2, 1] (dos juntos y el tercero separado).
- Sección fija -> no se divide: un paquete de `num_modulos` que arranca en el
  módulo fijado y continúa en los módulos consecutivos siguientes.
"""
import random

import numpy as np

# Penalizaciones del fitness (idénticas al prototipo).
PENALIZACION_CUOTA = 5000
PENALIZACION_CHOQUE_PROFESOR = 10000
PENALIZACION_CHOQUE_MALLA = 10000
PENALIZACION_DISPERSION = 50

# Cuota de sala usada si una carrera no tiene cuota configurada.
CUOTA_POR_DEFECTO = (3, 3)  # (sala común, sala propia)


def crear_poblacion(cant_poblacion, cant_genes, cant_bin_per_gen):
    """Matriz binaria aleatoria de `cant_poblacion` individuos."""
    return np.random.randint(low=0, high=2, size=(cant_poblacion, cant_genes * cant_bin_per_gen))


def decodificar_individuo(cromosoma_binario, info_genes, cant_bin_per_gen):
    """Traduce un cromosoma a la lista de bloques ocupados por cada gen.

    Devuelve `horario[gen] = [bloque_inicio, bloque_inicio + 1, ...]` con tantos
    casilleros como `num_modulos` tenga el paquete (módulos consecutivos).
    """
    horario_deco = []
    for i, gen in enumerate(info_genes):
        bits = cromosoma_binario[i * cant_bin_per_gen:(i + 1) * cant_bin_per_gen]
        val = int(bits.dot(1 << np.arange(bits.size)[::-1]))

        bloques_posibles = gen['bloques_validos']
        bloque_inicio = int(bloques_posibles[val % len(bloques_posibles)])

        horario_deco.append([bloque_inicio + k for k in range(gen['num_modulos'])])
    return horario_deco


def evaluar_poblacion(poblacion, info_genes, cant_bin_per_gen, cant_dias,
                      max_horas_edificio, cuotas_por_carrera):
    """Fitness de cada individuo: 0 es ideal; cada regla violada resta puntaje.

    `cuotas_por_carrera` = {id_carrera: (cuota_sala_comun, cuota_sala_propia)}.
    """
    num_individuos = poblacion.shape[0]
    cant_sessiones_unicas = cant_dias * max_horas_edificio
    fitness = np.zeros(num_individuos)

    for ind in range(num_individuos):
        horario = decodificar_individuo(poblacion[ind], info_genes, cant_bin_per_gen)
        castigo = 0

        casilleros = {}
        for id_gen, bloques in enumerate(horario):
            for bloque in bloques:
                if bloque < cant_sessiones_unicas:
                    casilleros.setdefault(bloque, []).append(id_gen)

        for lista_genes in casilleros.values():
            castigo += _castigo_cuotas_sala(lista_genes, info_genes, cuotas_por_carrera)
            castigo += _castigo_parejas(lista_genes, info_genes)

        fitness[ind] = castigo

    return fitness, float(fitness.max())


def _castigo_cuotas_sala(lista_genes, info_genes, cuotas_por_carrera):
    """Regla 1: no exceder la cuota de salas (comunes y propias) POR CARRERA en un bloque."""
    conteo = {}
    for id_gen in lista_genes:
        gen = info_genes[id_gen]
        tipo_sala = gen['tipo_sala']
        if tipo_sala in (2, 3):
            clave = (gen['id_carrera'], tipo_sala)
            conteo[clave] = conteo.get(clave, 0) + 1

    castigo = 0
    for (id_carrera, tipo_sala), cantidad in conteo.items():
        cuota_comun, cuota_propia = cuotas_por_carrera.get(id_carrera, CUOTA_POR_DEFECTO)
        cuota = cuota_comun if tipo_sala == 3 else cuota_propia
        if cantidad > cuota:
            castigo -= (cantidad - cuota) * PENALIZACION_CUOTA
    return castigo


def _castigo_parejas(lista_genes, info_genes):
    """Reglas 2 y 3: choque de profesor y choque de malla entre pares del mismo bloque."""
    if len(lista_genes) < 2:
        return 0

    castigo = 0
    for i in range(len(lista_genes)):
        for j in range(i + 1, len(lista_genes)):
            gen_a = info_genes[lista_genes[i]]
            gen_b = info_genes[lista_genes[j]]

            # --- Choque de profesor: intersección de las listas de docentes ---
            # Solo docentes de componentes teóricos/prácticos; los ayudantes
            # (Ayudantía tipo 1/2) se ajustan al horario y no restringen.
            if set(gen_a['profesores_choque']) & set(gen_b['profesores_choque']):
                castigo -= PENALIZACION_CHOQUE_PROFESOR

            # --- Choque de malla: mismo cohorte + semestre + sección ---
            if gen_a['cohorte'] == 'TRANSVERSAL' or gen_b['cohorte'] == 'TRANSVERSAL':
                continue
            if (gen_a['cohorte'] == gen_b['cohorte']
                    and gen_a['semestre'] == gen_b['semestre']
                    and gen_a['seccion'] == gen_b['seccion']):
                # Excepción: menciones distintas del mismo slot no chocan entre sí.
                if (gen_a['tipo_asignatura'] == 'MENCION'
                        and gen_b['tipo_asignatura'] == 'MENCION'
                        and gen_a['id_mencion'] != gen_b['id_mencion']):
                    continue
                castigo -= PENALIZACION_CHOQUE_MALLA
            elif gen_a['codigo_asignatura'] == gen_b['codigo_asignatura']:
                # Fomento de dispersión: el mismo curso en días/módulos distintos.
                castigo -= PENALIZACION_DISPERSION

    return castigo


def seleccion(poblacion, fitness, threshold_padres):
    """Selección por élite: la peor copia del mejor y el resto se replica desde los mejores."""
    padres = poblacion.copy()
    fitness_eval = fitness.copy()
    num_individuos = poblacion.shape[0]

    mejor_idx = int(np.argmax(fitness))
    peor_idx = int(np.argmin(fitness))
    padres[peor_idx] = poblacion[mejor_idx]
    fitness_eval[peor_idx] = fitness[mejor_idx]

    n_primeros = max(1, round(num_individuos * (100 - threshold_padres) / 100))
    mejores_indices = np.argsort(fitness_eval)[::-1][:n_primeros]
    for ind in range(num_individuos):
        if ind not in mejores_indices:
            padres[ind] = poblacion[random.choice(mejores_indices)]
    return padres


def crossover(padres, cant_bin_per_gen, cant_genes):
    """Cruce de dos puntos binarios (los cortes caen en bordes de gen)."""
    num_individuos, num_bits = padres.shape
    auxiliar = np.zeros((num_individuos, num_bits), dtype=int)
    puntos_crossover = [cant_bin_per_gen * 2 * i for i in range(1, cant_genes // 2)]

    for i in range(0, num_individuos - 1, 2):
        if puntos_crossover:
            corte = random.choice(puntos_crossover)
            auxiliar[i] = np.concatenate((padres[i][:corte], padres[i + 1][corte:]))
            auxiliar[i + 1] = np.concatenate((padres[i + 1][:corte], padres[i][corte:]))
        else:
            auxiliar[i], auxiliar[i + 1] = padres[i], padres[i + 1]

    if num_individuos % 2 != 0:
        auxiliar[-1] = padres[-1]
    return auxiliar


def mutacion(poblacion, probabilidad_mutacion):
    """Invierte cada bit con probabilidad `probabilidad_mutacion`."""
    mutado = poblacion.copy()
    mascara = np.random.rand(*mutado.shape) < probabilidad_mutacion
    mutado[mascara] = 1 - mutado[mascara]
    return mutado


def ejecutar(info_genes, parametros, cuotas_por_carrera, max_horas_edificio, progreso=None):
    """Bucle principal del AG.

    `parametros` es una instancia de `ParametrosAG`. `progreso` es un callback
    opcional `progreso(iteracion, mejor_fitness)` para reportar avance.

    Devuelve `(mejor_cromosoma, mejor_fitness, iteraciones_reales)`.
    """
    cant_genes = len(info_genes)
    if cant_genes == 0:
        raise ValueError('No hay genes que programar: el periodo no tiene secciones proyectadas.')

    poblacion = crear_poblacion(parametros.cant_poblacion, cant_genes, parametros.cant_bin_per_gen)
    mejor_fitness_historico = -float('inf')
    mejor_cromosoma = None
    iteraciones_reales = 0

    for iteracion in range(parametros.max_iteraciones):
        iteraciones_reales = iteracion + 1
        fitness, mejor_actual = evaluar_poblacion(
            poblacion, info_genes, parametros.cant_bin_per_gen,
            parametros.cant_dias, max_horas_edificio, cuotas_por_carrera,
        )
        idx_mejor = int(np.argmax(fitness))
        if mejor_actual > mejor_fitness_historico:
            mejor_fitness_historico = mejor_actual
            mejor_cromosoma = poblacion[idx_mejor].copy()

        if progreso is not None:
            progreso(iteraciones_reales, mejor_fitness_historico)

        if mejor_actual >= parametros.umbral_early_stop:
            break

        padres = seleccion(poblacion, fitness, parametros.threshold_padres)
        hijos = crossover(padres, parametros.cant_bin_per_gen, cant_genes)
        poblacion = mutacion(hijos, parametros.prob_mutacion)

    return mejor_cromosoma, mejor_fitness_historico, iteraciones_reales
