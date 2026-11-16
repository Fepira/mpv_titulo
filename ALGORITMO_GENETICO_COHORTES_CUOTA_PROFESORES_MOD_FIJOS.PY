import pandas as pd
import numpy as np
import random
import math
from tqdm import tqdm

# ==========================================
# 1. CARGA DE DATOS Y MAPEO INTELIGENTE (2 HOJAS)
# ==========================================
def cargar_datos_excel(ruta_archivo, cant_dias):
    try:
        # Leemos la Hoja 1 (Volumetría)
        df = pd.read_excel(ruta_archivo, sheet_name=0)
    except FileNotFoundError:
        print(f"No se encontró el archivo '{ruta_archivo}'. Verifica el nombre.")
        return [], 0, 0
        
    try:
        # Leemos la Hoja 2 (Asignaciones y Fijaciones)
        df_asig = pd.read_excel(ruta_archivo, sheet_name=1)
        df_asig.columns = df_asig.columns.str.strip().str.upper().str.replace(' ', '_')
    except Exception:
        # Si no hay hoja 2, creamos un DataFrame vacío para no romper el código
        print("⚠️ No se detectó una segunda hoja de asignaciones. Corriendo en modo libre.")
        df_asig = pd.DataFrame(columns=['CODIGO_ASIGNATURA', 'SECCION', 'PROFESOR', 'DIA_FIJO', 'MODULO_INICIO_FIJO'])

    # --- DICCIONARIO DE ASIGNACIONES (Match Rápido) ---
    asignaciones_dict = {}
    for _, row_a in df_asig.iterrows():
        cod = str(row_a.get('CODIGO_ASIGNATURA', '')).strip()
        try: sec = int(float(row_a.get('SECCION', 1)))
        except ValueError: sec = 1
        
        asignaciones_dict[(cod, sec)] = {
            'profesor': str(row_a.get('PROFESOR', '')).strip() if pd.notna(row_a.get('PROFESOR')) else '',
            'dia_fijo': str(row_a.get('DIA_FIJO', '')).strip().upper() if pd.notna(row_a.get('DIA_FIJO')) else '',
            'mod_fijo': row_a.get('MODULO_INICIO_FIJO', '')
        }
        
    df.columns = df.columns.str.strip().str.upper().str.replace(' ', '_')
    df = df.dropna(subset=['SECCIONES_POR_CURSO', 'MODULOS_SEMANALES'])
    
    if 'TIPO_ASIGNATURA' not in df.columns: df['TIPO_ASIGNATURA'] = 'OBLIGATORIA'
    if 'ID_MENCION' not in df.columns: df['ID_MENCION'] = 0
        
    semestres_unicos = sorted([s for s in df['SEMESTRE'].unique() if pd.notna(s)])
    ventanas_horarias = {}
    max_horas_edificio = 0
    dias_map = {'LUNES': 0, 'MARTES': 1, 'MIERCOLES': 2, 'JUEVES': 3, 'VIERNES': 4, 'SABADO': 5}
    
    print("\n" + "="*70)
    print("CONFIGURACIÓN DE FRANJAS HORARIAS (JAULAS MATEMÁTICAS)")
    print("="*70)
    
    for sem in semestres_unicos:
        df_sem = df[df['SEMESTRE'] == sem]
        tiene_obligatorias = any(df_sem['TIPO_ASIGNATURA'].astype(str).str.upper().str.contains('OBLIG'))
        tiene_menciones = any(df_sem['TIPO_ASIGNATURA'].astype(str).str.upper().str.contains('MENC'))
        
        ventanas_horarias[sem] = {}
        print(f"--- SEMESTRE {int(sem)} ---")
        
        if tiene_obligatorias:
            while True:
                try:
                    ini = int(input(f"OBLIGATORIOS - Módulo de INICIO (Ej. 1): "))
                    fin = int(input(f"OBLIGATORIOS - Módulo de FIN    (Ej. 4): "))
                    if ini > fin or ini < 1: print("Rango inválido.")
                    else:
                        ventanas_horarias[sem]['OBLIGATORIA'] = (ini, fin)
                        max_horas_edificio = max(max_horas_edificio, fin)
                        break
                except ValueError: print("Ingresa números enteros.")
                    
        if tiene_menciones:
            while True:
                try:
                    ini = int(input(f"MENCIONES    - Módulo de INICIO (Ej. 5): "))
                    fin = int(input(f"MENCIONES    - Módulo de FIN    (Ej. 8): "))
                    if ini > fin or ini < 1: print("Rango inválido.")
                    else:
                        ventanas_horarias[sem]['MENCION'] = (ini, fin)
                        max_horas_edificio = max(max_horas_edificio, fin)
                        break
                except ValueError: print("Ingresa números enteros.")
        print("")
        
    hay_transversales = df['COHORTES_INVOLUCRADAS'].isna().any() or (df['COHORTES_INVOLUCRADAS'].astype(str).str.strip() == '').any()
    if hay_transversales:
        print(f"--- CURSOS TRANSVERSALES (Sin Cohorte) ---")
        while True:
            try:
                ini_trans = int(input(f"TRANSVERSALES - Módulo INICIO (Ej. 1): "))
                fin_trans = int(input(f"TRANSVERSALES - Módulo FIN    (Ej. 8): "))
                if ini_trans > fin_trans or ini_trans < 1: print("Rango inválido.")
                else:
                    max_horas_edificio = max(max_horas_edificio, fin_trans)
                    break
            except ValueError: print("Ingresa números enteros.")
    else:
        ini_trans, fin_trans = 1, max(max_horas_edificio, 1) 
        
    print("="*70 + "\n")

    info_genes = []
    id_gen = 0
    
    for index, row in df.iterrows():
        secciones_str = str(row['SECCIONES_POR_CURSO']).replace(',', '.')
        try:
            valor_secciones = float(secciones_str)
            parte_decimal = valor_secciones - math.floor(valor_secciones)
            
            if parte_decimal <= 0.4: num_secciones_reales = math.floor(valor_secciones)
            else: num_secciones_reales = math.ceil(valor_secciones)
                
            if num_secciones_reales < 1: num_secciones_reales = 1 
            num_modulos = int(row['MODULOS_SEMANALES'])
        except ValueError:
            continue
            
        tipo_sala = int(float(row.get('TIPO_DE_SALA', 3))) if not pd.isna(row.get('TIPO_DE_SALA', 3)) else 3
        tipo_asig = str(row.get('TIPO_ASIGNATURA', 'OBLIGATORIA')).upper().strip()
        tipo_asig = 'MENCION' if 'MENC' in tipo_asig else 'OBLIGATORIA'
        
        id_mencion_raw = row.get('ID_MENCION', 0)
        id_mencion = 0 if pd.isna(id_mencion_raw) else int(float(id_mencion_raw))
        
        cohorte_raw = row.get('COHORTES_INVOLUCRADAS', '')
        es_transversal = pd.isna(cohorte_raw) or str(cohorte_raw).strip() == ''
        
        if es_transversal:
            cohorte = 'TRANSVERSAL'
            semestre_actual = 0
            mod_inicio, mod_fin = ini_trans, fin_trans
        else:
            cohorte = str(cohorte_raw)
            semestre_actual = row['SEMESTRE']
            mod_inicio, mod_fin = ventanas_horarias[semestre_actual][tipo_asig]
            
        cod_asignatura = row['CODIGO_DE_ASIGNATURA']
        
        for seccion in range(1, num_secciones_reales + 1):
            
            # Buscamos si esta sección tiene reglas en la Hoja 2
            datos_profe = asignaciones_dict.get((str(cod_asignatura).strip(), seccion), {})
            profesor = datos_profe.get('profesor', '')
            dia_fijo_str = datos_profe.get('dia_fijo', '')
            mod_fijo_val = datos_profe.get('mod_fijo', '')
            
            es_fijo = False
            if dia_fijo_str in dias_map and pd.notna(mod_fijo_val) and str(mod_fijo_val).strip() != '':
                es_fijo = True
                dia_idx = dias_map[dia_fijo_str]
                mod_inicio_0 = int(float(mod_fijo_val)) - 1
                bloque_mapeado = (dia_idx * max_horas_edificio) + mod_inicio_0
            
            # Lógica de división 3 módulos -> 2 y 1 (Solo si NO está fijo para evitar conflictos de anclaje)
            if num_modulos == 3 and not es_fijo:
                paquetes_a_crear = [2, 1]
            else:
                paquetes_a_crear = [num_modulos]
                
            for tamano_paquete in paquetes_a_crear:
                bloques_validos = []
                
                if es_fijo:
                    # Jaula matemática de 1 solo casillero
                    bloques_validos.append(bloque_mapeado)
                else:
                    # Jaula matemática normal
                    for dia in range(cant_dias): 
                        m_ini_0 = mod_inicio - 1
                        m_fin_0 = mod_fin - 1
                        
                        if dia == 5: m_fin_0 = min(m_fin_0, 3) 
                            
                        if m_fin_0 - m_ini_0 + 1 >= tamano_paquete:
                            for slot in range(m_ini_0, m_fin_0 - tamano_paquete + 2):
                                bloques_validos.append(dia * max_horas_edificio + slot)
                
                if not bloques_validos: bloques_validos = [0]
                    
                info_genes.append({
                    'id_gen': id_gen,
                    'codigo_asignatura': cod_asignatura,
                    'nombre_asignatura': row['NOMBRE_ASIGNATURA'],
                    'seccion': seccion,
                    'num_modulos': tamano_paquete,
                    'cohorte': cohorte, 
                    'semestre': semestre_actual,
                    'tipo_sala': tipo_sala,
                    'tipo_asignatura': tipo_asig,
                    'id_mencion': id_mencion,
                    'bloques_validos': bloques_validos, 
                    'profesor': profesor, # <--- SE GUARDA EL PROFE
                    'demanda_proyectada': row.get('DEMANDA_PROYECTADA', 0),
                    'demanda_real': row.get('DEMANDA_REAL', 0),
                    'alumnos_por_seccion': row.get('ALUMN_POR_SECCION', 0),
                    'secciones_por_curso': row.get('SECCIONES_POR_CURSO', 0),
                    'tipo_ciclicidad': row.get('TIPO_CICLICIDAD', 'N/A'),
                    'lista_cruzada' : row.get('LISTA_CRUZADA', "N/A")
                })
                id_gen += 1
                
    return info_genes, len(info_genes), max_horas_edificio

# ==========================================
# 2. FUNCIONES NÚCLEO DEL ALGORITMO GENÉTICO
# ==========================================
def crear_poblacion(cant_poblacion, cant_genes, cant_bin_per_gen):
    return np.random.randint(low=0, high=2, size=(cant_poblacion, cant_genes * cant_bin_per_gen))

def decodificar_individuo(cromosoma_binario, cant_genes, cant_bin_per_gen, max_horas_edificio, info_genes):
    horario_deco = []
    for i in range(cant_genes):
        bits = cromosoma_binario[i*cant_bin_per_gen : (i+1)*cant_bin_per_gen]
        val = bits.dot(1 << np.arange(bits.size)[::-1])
        
        bloques_posibles = info_genes[i]['bloques_validos']
        num_modulos = info_genes[i]['num_modulos']
        
        val_mapeado = val % len(bloques_posibles)
        bloque_inicio = bloques_posibles[val_mapeado]
        
        bloques_ocupados = [bloque_inicio + k for k in range(num_modulos)]
        horario_deco.append(bloques_ocupados)
        
    return horario_deco

def eval_poblac_fitness(poblacion, info_genes, cant_genes, cant_bin_per_gen, cant_dias, max_horas_edificio):
    num_individuos = poblacion.shape[0]
    fitness_eval_result = np.zeros(num_individuos)
    
    CUOTA_SALA_COMUN = 3
    CUOTA_SALA_PROPIA = 3 # <--- NUEVA CONFIGURACIÓN DE CUOTA SALAS PROPIAS
    cant_sessiones_unicas = cant_dias * max_horas_edificio
    
    for ind in range(num_individuos):
        horario_completo = decodificar_individuo(poblacion[ind], cant_genes, cant_bin_per_gen, max_horas_edificio, info_genes)
        castigo_total = 0
        
        casilleros = {c: [] for c in range(cant_sessiones_unicas)}
        for id_gen, bloques in enumerate(horario_completo):
            for b in bloques:
                if b < cant_sessiones_unicas:
                    casilleros[b].append(id_gen)
            
        for casillero, lista_genes in casilleros.items():
            
            # --- REGLA 1A: CUOTA DE SALAS COMUNES (3) ---
            comunes_en_bloque = [g for g in lista_genes if info_genes[g]['tipo_sala'] == 3]
            if len(comunes_en_bloque) > CUOTA_SALA_COMUN:
                exceso = len(comunes_en_bloque) - CUOTA_SALA_COMUN
                castigo_total -= (exceso * 5000)
                
            # --- REGLA 1B: CUOTA DE SALAS PROPIAS (3) [NUEVA REGLA AGREGADA] ---
            propias_en_bloque = [g for g in lista_genes if info_genes[g]['tipo_sala'] == 2]
            if len(propias_en_bloque) > CUOTA_SALA_PROPIA:
                exceso_propia = len(propias_en_bloque) - CUOTA_SALA_PROPIA
                castigo_total -= (exceso_propia * 5000)
            
            if len(lista_genes) > 1:
                for i in range(len(lista_genes)):
                    for j in range(i + 1, len(lista_genes)):
                        gen_A = info_genes[lista_genes[i]]
                        gen_B = info_genes[lista_genes[j]]
                        
                        # --- REGLA 2: CHOQUE DE PROFESOR ---
                        if gen_A['profesor'] != '' and (gen_A['profesor'].upper() == gen_B['profesor'].upper()):
                            castigo_total -= 10000
                            
                        # --- REGLA 3: CHOQUE DE MALLA (ALUMNOS) ---
                        if gen_A['cohorte'] == 'TRANSVERSAL' or gen_B['cohorte'] == 'TRANSVERSAL':
                            pass 
                        elif (gen_A['cohorte'] == gen_B['cohorte'] and 
                              gen_A['semestre'] == gen_B['semestre'] and 
                              gen_A['seccion'] == gen_B['seccion']):
                            
                            # Excepción Menciones
                            if (gen_A['tipo_asignatura'] == 'MENCION' and 
                                gen_B['tipo_asignatura'] == 'MENCION' and 
                                gen_A['id_mencion'] != gen_B['id_mencion']):
                                pass 
                            else:
                                castigo_total -= 10000 
                            
                        # Fomento de dispersión
                        elif gen_A['codigo_asignatura'] == gen_B['codigo_asignatura']:
                            castigo_total -= 50
                            
        fitness_eval_result[ind] = castigo_total
        
    return fitness_eval_result, np.max(fitness_eval_result)

def seleccion(poblacion, fitness_eval_result, threshold_padres):
    padres = poblacion.copy()
    fitness_eval = fitness_eval_result.copy()
    num_individuos = poblacion.shape[0]
    mejor_idx = np.argmax(fitness_eval_result)
    peor_idx = np.argmin(fitness_eval_result)
    padres[peor_idx] = poblacion[mejor_idx]
    fitness_eval[peor_idx] = fitness_eval[mejor_idx]
    n_primeros = max(1, round(num_individuos * (100 - threshold_padres) / 100))
    mejores_indices = np.argsort(fitness_eval)[::-1][:n_primeros]
    for ind in range(num_individuos):
        if ind not in mejores_indices:
            padres[ind] = poblacion[random.choice(mejores_indices)]
    return padres

def crossover(padres, cant_bin_per_gen, cant_genes):
    num_individuos, num_num_bin = padres.shape
    auxiliar = np.zeros((num_individuos, num_num_bin), dtype=int)
    puntos_crossover = [cant_bin_per_gen * 2 * i for i in range(1, cant_genes // 2)]
    for i in range(0, num_individuos - 1, 2):
        if puntos_crossover:
            corte = random.choice(puntos_crossover)
            auxiliar[i] = np.concatenate((padres[i][:corte], padres[i+1][corte:]))
            auxiliar[i+1] = np.concatenate((padres[i+1][:corte], padres[i][corte:]))
        else:
            auxiliar[i], auxiliar[i+1] = padres[i], padres[i+1]
    if num_individuos % 2 != 0: auxiliar[-1] = padres[-1]
    return auxiliar

def mutacion(poblacion, probabilidad_mutacion=0.05):
    mutado = poblacion.copy()
    mascara = np.random.rand(*mutado.shape) < probabilidad_mutacion
    mutado[mascara] = 1 - mutado[mascara]
    return mutado

# ==========================================
# 3. EXPORTACIÓN DEL RESULTADO (MODO AUDITORÍA)
# ==========================================
def exportar_horario(mejor_individuo, info_genes, cant_genes, cant_bin_per_gen, max_horas_edificio):
    horario_completo = decodificar_individuo(mejor_individuo, cant_genes, cant_bin_per_gen, max_horas_edificio, info_genes)
    DIAS = ['LUNES', 'MARTES', 'MIERCOLES', 'JUEVES', 'VIERNES', 'SABADO']
    registros = []
    
    for id_gen, bloques in enumerate(horario_completo):
        gen_info = info_genes[id_gen]
        if gen_info['tipo_sala'] == 3: tipo_sala_str = 'COMUN (3)'
        elif gen_info['tipo_sala'] == 5: tipo_sala_str = 'ONLINE (5)'
        else: tipo_sala_str = 'PROPIA (2)'
        
        mencion_str = f"Mención ID:{gen_info['id_mencion']}" if gen_info['tipo_asignatura'] == 'MENCION' else 'Obligatoria'
        if gen_info['cohorte'] == 'TRANSVERSAL': mencion_str = 'Electivo Libre'
        
        for posicion_en_bloque, casillero in enumerate(bloques):
            dia_idx = casillero // max_horas_edificio   
            hora_idx = casillero % max_horas_edificio   
            
            registros.append({
                'Cohorte': gen_info['cohorte'],
                'Semestre': '' if gen_info['semestre'] == 0 else gen_info['semestre'],
                'Tipo_Asignatura': mencion_str,
                'Codigo_curso': gen_info['codigo_asignatura'],
                'Nombre_asignatura': gen_info['nombre_asignatura'],
                'Profesor': gen_info['profesor'], 
                'Seccion': gen_info['seccion'],
                'Modulo_Consecutivo': posicion_en_bloque + 1,
                'Tipo_Sala': tipo_sala_str,
                'Dia': DIAS[dia_idx],
                'Modulo_Horario': hora_idx + 1,
                'Demanda_Proyectada': gen_info['demanda_proyectada'],
                'Demanda_Real': gen_info['demanda_real'],
                'alumnos_por_seccion': gen_info['alumnos_por_seccion'],
                'secciones_por_curso': gen_info['secciones_por_curso'],
                'tipo_ciclicidad': gen_info['tipo_ciclicidad'],
                'lista_cruzada' : gen_info['lista_cruzada'] # <--- CORREGIDO (Decía get_info)
            })
            
    df_auditoria = pd.DataFrame(registros)
    df_auditoria = df_auditoria.sort_values(by=['Cohorte', 'Semestre', 'Seccion', 'Dia', 'Modulo_Horario'])
    df_auditoria.to_csv('PROGRAMACION_HORARIO_PERIODISMO_FINAL.csv', index=False, encoding='utf-8-sig')
    print("\n🏆 ¡Algoritmo Finalizado!")
    print("El archivo completo se ha guardado como 'PROGRAMACION_HORARIO_PERIODISMO_FINAL.csv'")

# ==========================================
# 4. BUCLE PRINCIPAL (MAIN)
# ==========================================
if __name__ == "__main__":
    RUTA_EXCEL = 'CURSOS_A_PROGRAMAR.xlsx'
    
    cant_dias = 5
    
    print("Cargando datos institucionales y asignaciones docentes...")
    info_genes, cant_genes, max_horas_edificio = cargar_datos_excel(RUTA_EXCEL, cant_dias)
    
    if cant_genes > 0:
        cant_bin_per_gen = 6
        max_iteraciones = 1500
        cant_poblacion = 150
        threshold_val = 0 
        
        print(f"\nTotal de paquetes a programar (tras divisiones): {cant_genes}")
        print(f"Jornada máxima del edificio: {max_horas_edificio} módulos por día")
        
        poblacion = crear_poblacion(cant_poblacion, cant_genes, cant_bin_per_gen)
        mejor_historico_eval = -float('inf')
        mejor_historico_ind = None
        
        for iteracion in tqdm(range(max_iteraciones)):
            fitness_eval_result, actual_best_eval = eval_poblac_fitness(
                poblacion, info_genes, cant_genes, cant_bin_per_gen, cant_dias, max_horas_edificio
            )
            
            idx_mejor = np.argmax(fitness_eval_result)
            if actual_best_eval > mejor_historico_eval:
                mejor_historico_eval = actual_best_eval
                mejor_historico_ind = poblacion[idx_mejor].copy()
                
            if actual_best_eval >= threshold_val:
                print(f"\n¡Solución perfecta encontrada en iteración {iteracion}!")
                break
                
            padres = seleccion(poblacion, fitness_eval_result, threshold_padres=40)
            hijos = crossover(padres, cant_bin_per_gen, cant_genes)
            poblacion = mutacion(hijos, probabilidad_mutacion=0.05)
            
        print(f"\nMejor puntaje obtenido: {mejor_historico_eval}")
        exportar_horario(mejor_historico_ind, info_genes, cant_genes, cant_bin_per_gen, max_horas_edificio)