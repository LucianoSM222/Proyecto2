"""Libro Excel con los valores de las tablas y figuras del Capítulo 6. Solo
transcribe final.json (y pep_muestra.json si existe); los promedios y
diferencias se escriben como fórmulas para que el libro se recalcule.
Uso: python3 tablas_excel.py final.json salida.xlsx
"""
import sys, os, json
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

SRC, OUT = sys.argv[1], sys.argv[2]
R = json.load(open(SRC, encoding="utf-8"))
FM = os.path.join(os.path.dirname(SRC), "pep_muestra.json")
S = json.load(open(FM, encoding="utf-8")) if os.path.exists(FM) else None

FUENTE = "Calibri"
CAB = PatternFill("solid", fgColor="4472C4"); BANDA = PatternFill("solid", fgColor="D9E1F2")
BORDE = Border(bottom=Side(style="thin", color="FFFFFF"))
SIG = {"pp": "PP", "pr": "RP", "pd": "DP", "pf": "FP", "pa": "AP"}
NOM_LITO = {"Kpcli": "Lavas inferiores (Kpcli)", "Bht": "Brecha hidrotermal (Bht)",
            "Kpcls": "Lavas superiores (Kpcls)", "Brecha_mixta": "Brecha mixta"}
wb = Workbook(); wb.remove(wb.active)


def hoja(nombre):
    ws = wb.create_sheet(nombre); ws.sheet_view.showGridLines = False
    ws._fila = 1
    return ws


def titulo(ws, txt):
    c = ws.cell(ws._fila, 1, txt); c.font = Font(name=FUENTE, size=13, bold=True, color="404040")
    ws._fila += 1


def nota(ws, txt):
    c = ws.cell(ws._fila, 1, txt); c.font = Font(name=FUENTE, size=9, italic=True, color="595959")
    ws._fila += 1


def tabla(ws, cab, filas, fmt=None):
    """Escribe una tabla con estilo Excel; devuelve (fila_cabecera, primera, última)."""
    r0 = ws._fila
    for j, h in enumerate(cab, 1):
        c = ws.cell(r0, j, h)
        c.font = Font(name=FUENTE, bold=True, color="FFFFFF"); c.fill = CAB
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, f in enumerate(filas, 1):
        for j, v in enumerate(f, 1):
            c = ws.cell(r0 + i, j, v)
            c.font = Font(name=FUENTE, bold=isinstance(f[0], str) and f[0].startswith("Media"))
            c.alignment = Alignment(horizontal="center"); c.border = BORDE
            if i % 2: c.fill = BANDA
            if fmt and fmt[j - 1]: c.number_format = fmt[j - 1]
    ws._fila = r0 + len(filas) + 2
    for j, h in enumerate(cab, 1):
        largo = max([len(str(h))] + [len(str(f[j - 1])) for f in filas if not str(f[j - 1]).startswith("=")])
        ws.column_dimensions[get_column_letter(j)].width = max(ws.column_dimensions[get_column_letter(j)].width or 0,
                                                              min(48, largo + 3))
    return r0, r0 + 1, r0 + len(filas)


def col(j): return get_column_letter(j)


# ── Configuración ──────────────────────────────────────────────────────────
DI = R["di_vigente"]; L = R["limpieza"]; RF = R["train_rf"]
ws = hoja("Configuración"); titulo(ws, "Configuración de la corrida final (2026-10-22)")
tabla(ws, ["Elemento", "Valor"], [
    ["Registros MWD / pozos", f"{R['tabla_6_1']['n_total']} / 928"],
    ["Serie del DI", "depurada: emboquillado y percusión de empate fuera antes de la varianza móvil"],
    ["Ventana del DI [muestras]", DI["window"]], ["Umbral del DI", DI["umbral"]],
    *[[f"Peso {SIG[k]} (calibrado a 5 m)", round(v, 4)] for k, v in DI["pesos"].items()],
    ["ρ ajuste calibración", DI["rho_ajuste"]], ["ρ validación (un sondaje fuera)", DI["rho_validacion"]],
    ["Pares / sondajes de la calibración", f"{DI['n_pares']} / {DI['n_sondajes']}"],
    ["Emboquillado [m]", L["emboquillado_m"]], ["Umbral de percusión de empate", L["umbral_empate"]],
    ["Largo de barra [m]", R["tabla_6_1"]["largo_barra_m"]],
    ["Random Forest", "200 árboles · profundidad 8 · min_samples_split 6 · min_samples_leaf 3 · max_features √p · semilla 42"],
    ["Agregación del bosque", "mediana de los 200 árboles"],
    ["Siglas", "FP = flujo · AP = avance · PEP = (PP + RP + AP) / ROP [bar·min/m]"],
], fmt=[None, None])

# ── Tabla 6.1 ──────────────────────────────────────────────────────────────
T = R["tabla_6_1"]; ws = hoja("T6.1 Empate")
titulo(ws, "Tabla 6.1 · Sensibilidad del umbral de caída en percusión de empate")
ws.cell(ws._fila, 1, "Total de registros"); ws.cell(ws._fila, 2, T["n_total"]).number_format = "#,##0"
celda_total = f"$B${ws._fila}"; ws._fila += 2
r0 = ws._fila
tabla(ws, ["Umbral de caída", "Muestras marcadas", "% del total"],
      [[f["umbral"], f["n"], f"=B{r0 + i}/{celda_total}"] for i, f in enumerate(T["filas"], 1)],
      fmt=["0.00", "#,##0", "0.00%"])
nota(ws, f"Empates esperados por largo de barra ({T['largo_barra_m']} m, paso 2 cm): {T['teorico_largo_barra']:,}".replace(",", "."))

# ── Limpieza y embudo ──────────────────────────────────────────────────────
ws = hoja("Limpieza"); titulo(ws, "Registros excluidos por filtro")
tabla(ws, ["Filtro", "Registros", "Excluye del DI", "Excluye del entrenamiento"], [
    [f"Emboquillado (< {L['emboquillado_m']} m)", L["emboquillado_marcados"], "sí", "sí"],
    [f"Percusión de empate (caída ≥ {L['umbral_empate']}, fuera del emboquillado)", L["percusion_empate"], "sí", "sí"],
    ["PP fuera de 90–230 bar", L["rango_fisico_pp"], "no", "sí"],
    ["Continuidad del registro", L["continuidad"], "no", "sí"],
    ["Total no entrenable por limpieza", L["no_entrenables"], "", ""]], fmt=[None, "#,##0", None, None])
titulo(ws, "Embudo del conjunto de entrenamiento")
tabla(ws, ["Etapa", "Quedan", "Perdidos"], [[e["label"], e["quedan"], e["perdidos"]] for e in R["embudo"]],
      fmt=[None, "#,##0", "#,##0"])
E = R["entrenamiento"]
titulo(ws, "Entrenamiento por caserón")
_, a, b = tabla(ws, ["Caserón", "Registros", "Pozos"],
                [[k, v["n_puntos"], v["n_pozos"]] for k, v in E["por_caseron"].items()], fmt=[None, "#,##0", "#,##0"])
ws.cell(b + 1, 1, "Total").font = Font(name=FUENTE, bold=True)
ws.cell(b + 1, 2, f"=SUM(B{a}:B{b})").number_format = "#,##0"; ws.cell(b + 1, 3, f"=SUM(C{a}:C{b})").number_format = "#,##0"
ws._fila = b + 3
titulo(ws, "Etiquetas de UCS en el entrenamiento")
lit_de = {str(v): k for k, v in ((k, v["ancla"]) for k, v in R["ucs_por_litologia"].items())}
tabla(ws, ["UCS referencial [MPa]", "Litología", "Registros"],
      [[float(k), NOM_LITO.get(lit_de.get(str(float(k))), "—"), v] for k, v in E["etiquetas"].items()], fmt=["0.0", None, "#,##0"])

# ── Pearson ────────────────────────────────────────────────────────────────
pe = R["pearson"]; V = pe["variables"]; ws = hoja("Pearson")
for clave, tt in (("crudas", "Correlación de Pearson · señales registradas"),
                  ("perfiles_varianza", "Correlación de Pearson · varianza móvil estandarizada (entrada del DI)")):
    titulo(ws, tt)
    tabla(ws, [""] + V, [[v] + [round(x, 4) for x in fila] for v, fila in zip(V, pe[clave])], fmt=[None] + ["0.00"] * len(V))
nota(ws, f"n = {pe['n']:,} registros".replace(",", "."))

# ── Tabla 6.2 ──────────────────────────────────────────────────────────────
T2 = R["tabla_6_2"]; ws = hoja("T6.2 Radio RQD")
titulo(ws, "Tabla 6.2 · Sensibilidad de la calibración del DI al radio de asignación del RQD")
filas = []
for f in T2["filas"]:
    w = f.get("pesos") or {}
    ok = f["status"] == "ok"
    filas.append([f["radio_m"], f.get("n_pares") if ok else (f.get("n_intervalos") or 0), f.get("n_sondajes"),
                  *[w.get(k) if ok else None for k in ("pp", "pr", "pd", "pf")],
                  f.get("rho_ajuste") if ok else None, f.get("rho_validacion") if ok else None])
tabla(ws, ["Radio [m]", "Pares", "Sondajes", "Peso PP", "Peso RP", "Peso DP", "Peso FP", "ρ ajuste", "ρ validación"],
      filas, fmt=["0.0", "0", "0", "0.00", "0.00", "0.00", "0.00", "+0.000;-0.000", "+0.000;-0.000"])
nota(ws, f"Umbral {T2['umbral']} · ventana {T2['ventana']} · {T2['n_candidatos']} combinaciones (400 Dirichlet + convención, semilla {T2['semilla']}). Celdas vacías: sin pares suficientes.")

# ── Sensibilidad del DI a la ventana ───────────────────────────────────────
FV = os.path.join(os.path.dirname(SRC), "di_ventanas.json")
if os.path.exists(FV):
    DV = json.load(open(FV, encoding="utf-8")); ws = hoja("DI ventanas")
    titulo(ws, "Sensibilidad del DI al tamaño de ventana (10, 14 y 20 muestras)")
    titulo(ws, "Pozo de referencia PCC_0042_PR01_TH_P20_H12")
    tabla(ws, ["Ventana [muestras]", "Ventana [cm]", "Registros con DI", "Picos", "% sobre umbral"],
          [[r["ventana"], r["ventana"] * DV["paso_m"] * 100, r["registros_con_di"], r["picos"], r["pct_sobre_umbral"] / 100]
           for r in DV["pozo"]["filas"]], fmt=["0", "0", "#,##0", "#,##0", "0.0%"])
    FMT_DV = [None, "0", "#,##0", "#,##0", "#,##0", "#,##0", "0.00", "0.0%"]
    for et, bloque in [("Cuatro caserones", {"TOTAL": DV["global"]})] + [(f"Caserón {k}", {k: v}) for k, v in sorted(DV["por_caseron"].items())]:
        titulo(ws, et)
        (k, d), = bloque.items()
        tabla(ws, ["Ventana [muestras]", "Ventana [cm]", "Pozos", "Pozos sin DI (cortos)", "Registros con DI", "Picos",
                   "Picos por 100 m", "% sobre umbral"],
              [[d[str(v)]["ventana"], d[str(v)]["ventana_cm"], d[str(v)]["pozos"], d[str(v)]["pozos_sin_di"],
                d[str(v)]["registros_con_di"], d[str(v)]["picos"], d[str(v)]["picos_por_100m"],
                d[str(v)]["pct_sobre_umbral"] / 100] for v in DV["ventanas"]], fmt=FMT_DV)
    nota(ws, f"Umbral DI {DV['umbral']}; pesos calibrados a 5 m; serie depurada (emboquillado y percusión de empate fuera). "
             f"Picos: eventos sobre el umbral agrupados si están a menos de {DV['gap_m']} m.")

# ── DI medio vs RQD de sondaje ─────────────────────────────────────────────
FR = os.path.join(os.path.dirname(SRC), "di_rqd_caserones.json")
if os.path.exists(FR):
    DR = json.load(open(FR, encoding="utf-8")); ws = hoja("DI vs RQD")
    titulo(ws, "Correlación de rangos de Spearman entre el DI medio y el RQD de sondaje")
    tabla(ws, ["Radio [m]", "Caserón", "Pares", "Sondajes", "ρ de Spearman", "p"],
          [[f["radio_m"], f["caseron"], f["n_pares"], f["n_sondajes"], f["rho"], f["p"]] for f in DR["spearman"]],
          fmt=["0", None, "0", "0", "+0.000;-0.000", "0.000"])
    nota(ws, "Celdas vacías: el caserón no tiene tramos de RQD dentro del radio. «4 caserones» cuenta cada tramo una sola vez.")
    titulo(ws, "Cobertura: distancia de los tramos de RQD a cada caserón")
    tabla(ws, ["Caserón", "Distancia mínima [m]", "Distancia mediana [m]"] + [f"Tramos a ≤ {r:g} m" for r in DR["radios"]],
          [[c, v["dist_min_m"], v["dist_mediana_m"]] + [v[f"tramos_a_{r:g}m"] for r in DR["radios"]] for c, v in DR["cobertura"].items()],
          fmt=[None, "#,##0.0", "#,##0.0"] + ["0"] * len(DR["radios"]))
    nota(ws, f"{DR['n_tramos_rqd']} tramos de RQD en {len(DR['sondajes_rqd'])} sondajes. Apareo uno a uno: registro MWD más cercano al centro "
             f"del tramo; DI medio sobre el tramo de ese pozo con el largo del intervalo y ≥ {DR['piso']} registros.")
    titulo(ws, "Pares a ≤ 25 m")
    tabla(ws, ["Caserón", "Sondaje", "Desde [m]", "Hasta [m]", "RQD [%]", "Distancia [m]", "Pozo MWD", "Registros con DI", "DI medio"],
          [[p["caseron"], p["sondaje"], p["desde"], p["hasta"], p["rqd"], p["dist_m"], p["pozo"], p["n_di"], p["di_medio"]]
           for p in sorted(DR["pares"], key=lambda p: p["dist_m"]) if p["dist_m"] <= 25],
          fmt=[None, None, "0.00", "0.00", "0.0", "0.00", None, "0", "0.000"])

# ── GroupKFold y LOOCV-Caserón ─────────────────────────────────────────────
FMT_V = [None, "#,##0", "0", "+0.000;-0.000", "0.00", "+0.000;-0.000"]
for nombre, clave, et in (("GroupKFold", "groupkfold", "Fold"), ("LOOCV-Caserón", "loocv_caseron", "Caserón fuera")):
    ws = hoja(nombre)
    titulo(ws, f"Validación del Random Forest · {nombre}" + (" por pozo (k = 5)" if clave == "groupkfold" else ""))
    PL = R[clave]["pliegues"]
    _, a, b = tabla(ws, [et, "Registros de prueba", "Etiquetas en prueba", "R²", "RMSE [MPa]", "ρ de Spearman"],
                    [[str(f["pliegue"]), f["n_prueba"], f["n_etiquetas_prueba"], f["r2"], f["rmse"], f["spearman"]] for f in PL],
                    fmt=FMT_V)
    ws.cell(b + 1, 1, "Media" + (" (definidos)" if clave != "groupkfold" else "")).font = Font(name=FUENTE, bold=True)
    for j in (4, 5, 6):
        c = ws.cell(b + 1, j, f"=AVERAGE({col(j)}{a}:{col(j)}{b})"); c.number_format = FMT_V[j - 1]
        c.font = Font(name=FUENTE, bold=True); c.alignment = Alignment(horizontal="center")
    if clave == "groupkfold":
        ws.cell(b + 2, 1, "Desv. estándar").font = Font(name=FUENTE, bold=True)
        for j in (4, 5, 6):
            c = ws.cell(b + 2, j, f"=STDEV({col(j)}{a}:{col(j)}{b})"); c.number_format = "0.000"
            c.alignment = Alignment(horizontal="center")
    ws._fila = b + 4
    if clave != "groupkfold":
        nota(ws, "PCS_1059 tiene una sola etiqueta en la prueba: R² y ρ de Spearman indefinidos (celda vacía); AVERAGE los omite.")
    nota(ws, "Predicción = mediana de los 200 árboles. ρ de Spearman entre UCS predicha y UCS referencial.")

# ── Los cuatro métodos bajo LOOCV-Caserón ──────────────────────────────────
FL = os.path.join(os.path.dirname(SRC), "loocv_caseron_metodos.json")
if os.path.exists(FL):
    LM = json.load(open(FL, encoding="utf-8"))
    NOM_MET = {"linea_base": "Línea base (media litología)", "banda": "Banda por unidad",
               "relacion": "Relación directa PEP↔UCS", "ml": "ML (Random Forest)"}
    ws = hoja("LOOCV-Caserón métodos")
    titulo(ws, "Comparación de métodos de UCS · LOOCV-Caserón")
    filas = [[NOM_MET[k], f["caseron"], f["n_prueba"], f["n_etiquetas"], f["metricas"][k]["rmse"], f["metricas"][k]["mae"],
              f["metricas"][k]["pearson"], f["metricas"][k]["spearman"]]
             for k in LM["metodos"] for f in LM["pliegues"]]
    FMT_M = [None, None, "#,##0", "0", "0.0", "0.0", "+0.000;-0.000", "+0.000;-0.000"]
    _, a, b = tabla(ws, ["Método", "Caserón fuera", "Registros de prueba", "Etiquetas", "RMSE [MPa]", "MAE [MPa]",
                         "r de Pearson", "ρ de Spearman"], filas, fmt=FMT_M)
    titulo(ws, "Media de los caserones (correlaciones: solo los definidos)")
    r0 = ws._fila
    filas_m = [[NOM_MET[k]] + [f'=AVERAGEIF($A${a}:$A${b},$A{r0 + 1 + i},{col(j)}${a}:{col(j)}${b})' for j in (5, 6)]
               + ([None, None] if k == "linea_base" else
                  [f'=AVERAGEIF($A${a}:$A${b},$A{r0 + 1 + i},{col(j)}${a}:{col(j)}${b})' for j in (7, 8)])
               for i, k in enumerate(LM["metodos"])]
    tabla(ws, ["Método", "RMSE [MPa]", "MAE [MPa]", "r de Pearson", "ρ de Spearman"], filas_m,
          fmt=[None, "0.0", "0.0", "+0.000;-0.000", "+0.000;-0.000"])
    nota(ws, "Celdas vacías: correlación indefinida (PCS_1059 tiene una sola etiqueta; la línea base predice un valor constante).")
    nota(ws, "Relación directa: da un valor por litología; en un caserón con dos litologías su correlación es ±1 por construcción "
             "(PCC_0042 +1, PCC_1541 −1): solo dice si ordenó bien las dos, no cuánto acierta.")
    nota(ws, "Banda y relación: curva PEP→UCS ajustada sin el caserón, evaluada en la PEP mediana de cada litología del caserón excluido; "
             "la banda aparta cada registro del centro según su PEP.")
    titulo(ws, "Curva PEP→UCS de cada pliegue")
    tabla(ws, ["Caserón fuera", "Forma", "Coeficientes", "Pares (PEP mediana, UCS referencial)", "Extrapola"],
          [[f["caseron"], f["curva"]["forma"], ", ".join(f"{k:.4g}" for k in f["curva"]["coef"]),
            "; ".join(f"({p[0]:.1f}, {p[1]:.1f})" for p in f["curva"]["pares"]),
            ", ".join(e["litologia"] for e in f["extrapolacion"]) or "no"] for f in LM["pliegues"]],
          fmt=[None] * 5)

# ── Importancia, comparación ───────────────────────────────────────────────
ws = hoja("Importancia"); titulo(ws, "Importancia por permutación de las predictoras")
tabla(ws, ["Predictora", "Importancia"], sorted(([k, v] for k, v in RF["feat_imp"].items()), key=lambda x: -x[1]),
      fmt=[None, "0.000"])
nota(ws, RF["feat_imp_motivo"])
titulo(ws, "Ajuste del modelo de producción")
tabla(ws, ["Métrica", "Valor"], [["R² GroupKFold (media)", RF["cv_r2_mean"]], ["R² GroupKFold (desv.)", RF["cv_r2_std"]],
                                 ["R² entrenamiento", RF["r2_train"]], ["RMSE entrenamiento [MPa]", RF["rmse_train"]],
                                 ["Registros de entrenamiento", RF["n_train"]]], fmt=[None, "0.000"])

C = R["comparacion"]; ws = hoja("Comparación"); titulo(ws, "Comparación de algoritmos · GroupKFold por pozo")
_, a, b = tabla(ws, ["Modelo", "R² entrenamiento", "R² prueba", "Desv. R² prueba", "RMSE prueba [MPa]", "Desv. RMSE", "Sobreajuste (R² ent. − R² prueba)"],
                [[r["modelo"], r.get("r2_train_mean"), r["r2_mean"], r.get("r2_std"), r.get("rmse_mean"), r.get("rmse_std"), None]
                 for r in C["rows"] if r.get("r2_mean") is not None],
                fmt=[None, "0.000", "+0.000;-0.000", "0.000", "0.0", "0.0", "0.000"])
for i in range(a, b + 1):
    ws.cell(i, 7, f"=B{i}-C{i}").number_format = "0.000"; ws.cell(i, 7).alignment = Alignment(horizontal="center")
nota(ws, f"Mismos {C['n_samples']:,} registros para los cinco modelos, {C['n_grupos']} pozos, k = {C['k_splits']}.".replace(",", "."))

# ── UCS por litología, P10–P90 ─────────────────────────────────────────────
U = R["ucs_por_litologia"]; ws = hoja("UCS por litología")
titulo(ws, "UCS de laboratorio (referencial) y UCS predicha, roca intacta entrenable")
_, a, b = tabla(ws, ["Litología", "Registros", "UCS referencial [MPa]", "P10 ML", "P50 ML", "P90 ML", "P50 − referencial"],
                [[NOM_LITO.get(k, k), v["n"], v["ancla"], v["p10"], v["p50"], v["p90"], None]
                 for k, v in sorted(U.items(), key=lambda kv: kv[1]["ancla"])],
                fmt=[None, "#,##0", "0.0", "0.0", "0.0", "0.0", "+0.0;-0.0"])
for i in range(a, b + 1):
    ws.cell(i, 7, f"=E{i}-C{i}").number_format = "+0.0;-0.0"; ws.cell(i, 7).alignment = Alignment(horizontal="center")
titulo(ws, "Ancho de la banda P10–P90 de la predicción")
tabla(ws, ["Roca", "Registros", "Media [MPa]", "Mediana [MPa]"],
      [["intacta (DI ≤ 1)" if k == "intacta" else "fracturada (DI > 1)", v["n"], v["media"], v["mediana"]] for k, v in R["p10_p90"].items()],
      fmt=[None, "#,##0", "0.0", "0.0"])

# ── PEP ────────────────────────────────────────────────────────────────────
ws = hoja("PEP estratos"); titulo(ws, "PEP y ROP medianas por litología y estrato de PP (roca intacta entrenable)")
tabla(ws, ["Litología", "UCS referencial [MPa]", "Estrato PP [bar]", "Registros", "PEP mediana [bar·min/m]", "CV PEP", "ROP mediana [m/min]"],
      [[NOM_LITO.get(e["lito"], e["lito"]), e["ucs_lab"], f"{e['pp_bin']}–{e['pp_bin'] + 10}", e["n"], e["pep_mediana"], e["pep_cv"], e["rop_mediana"]]
       for e in R["pep_estratos"]], fmt=[None, "0.0", None, "#,##0", "0.0", "0.000", "0.000"])
if S:
    titulo(ws, "Correlación de Spearman de la PEP por registro")
    tabla(ws, ["Variable", "ρ de Spearman con la PEP"],
          [["UCS referencial", S["spearman_pep"]["ucs_ref"]], ["ROP", S["spearman_pep"]["rop"]], ["PP", S["spearman_pep"]["pp"]]],
          fmt=[None, "+0.000;-0.000"])
    nota(ws, f"{S['n']:,} registros entrenables de roca intacta con PEP ≤ {S['pep_max']:.0f} y ROP ≥ {S['rop_min']} m/min; "
             f"{S['fuera_pep_max']:,} excluidos por PEP > {S['pep_max']:.0f} (ROP ≈ 0).".replace(",", "."))

# ── Ajustes UCS referencial ~ PEP ──────────────────────────────────────────
FA = os.path.join(os.path.dirname(SRC), "pep_ajustes.json")
if os.path.exists(FA):
    PA = json.load(open(FA, encoding="utf-8")); ws = hoja("PEP ajustes")
    titulo(ws, "Ajustes UCS referencial ~ PEP: conjunto, agregación y forma")
    NOM_AG = {"registro": "Por registro", "litologia": "Por litología", "litologia_caseron": "Litología × caserón",
              "litologia_estrato_pp": "Litología × estrato de PP (10 bar)"}
    FORMAS = ["lineal", "parabolico", "potencial", "exponencial", "logaritmico"]
    tabla(ws, ["Conjunto", "Agregación", "Puntos", "Registros", "ρ de Spearman", "r de Pearson",
               "R² lineal", "R² parabólico", "R² potencial", "R² exponencial", "R² logarítmico"],
          [["Solo roca intacta (DI ≤ 1)" if c == "intacta" else "Todo (intacta + fracturada)", NOM_AG[g], d["n_puntos"], d["n_registros"],
            d["spearman"], d["pearson"]] + [d["ajustes"].get(f, {}).get("r2") for f in FORMAS]
           for c in ("intacta", "todo") for g, d in PA["conjuntos"][c].items() if g != "muestra"],
          fmt=[None, None, "#,##0", "#,##0", "+0.000;-0.000", "+0.000;-0.000"] + ["0.000"] * 5)
    nota(ws, "R² medido en MPa para todas las formas. Con 4 grupos la parábola tiene un solo grado de libertad: su R² no es comparable con el de 55 o 717.526 puntos.")
    titulo(ws, "Ecuaciones del ajuste parabólico")
    tabla(ws, ["Conjunto", "Agregación", "Ecuación", "R²"],
          [["Solo roca intacta" if c == "intacta" else "Todo", NOM_AG[g], d["ajustes"]["parabolico"]["ecuacion"], d["ajustes"]["parabolico"]["r2"]]
           for c in ("intacta", "todo") for g, d in PA["conjuntos"][c].items() if g != "muestra"], fmt=[None, None, None, "0.000"])
    titulo(ws, "Grupos litología × caserón (conjunto todo)")
    tabla(ws, ["Grupo", "PEP mediana [bar·min/m]", "UCS referencial [MPa]"],
          [[p["grupo"], p["pep_mediana"], p["ucs_ref"]] for p in PA["conjuntos"]["todo"]["litologia_caseron"]["puntos"]],
          fmt=[None, "0.0", "0.0"])

# ── ROP frente a las presiones ─────────────────────────────────────────────
FRP = os.path.join(os.path.dirname(SRC), "rop_presiones.json")
if os.path.exists(FRP):
    RPJ = json.load(open(FRP, encoding="utf-8")); ws = hoja("ROP vs presiones")
    titulo(ws, "Relación de la ROP con PP, AP, RP y DP (roca continua entrenable; FP excluida por criterio físico)")
    tabla(ws, ["Grupo", "Presión", "Registros", "Pozos", "ρ simple", "ρ parcial", "ρ dentro del pozo", "R² sola (rangos)", "R² las 4 (rangos)", "Mediana [bar]"],
          [[NOM_LITO.get(g, g), p, d["n"], d["n_pozos"], v["rho_simple"], v["rho_parcial"], v["rho_intra_pozo"], v["r2_sola"], d["r2_rangos_las_4"], v["mediana"]]
           for g, d in RPJ["grupos"].items() for p, v in d["presiones"].items()],
          fmt=[None, None, "#,##0", "#,##0", "+0.000;-0.000", "+0.000;-0.000", "+0.000;-0.000", "0.000", "0.000", "0.0"])
    nota(ws, "ρ parcial: rangos descontando linealmente las otras tres presiones. ρ dentro del pozo: desviaciones respecto de la mediana de cada pozo.")
    titulo(ws, "Correlación entre presiones (todas las litologías)")
    tabla(ws, ["Par", "ρ de Spearman"], [[k, v] for k, v in RPJ["grupos"]["Todas las litologías"]["correlacion_entre_presiones"].items()],
          fmt=[None, "+0.000;-0.000"])

# ── Concordancia ───────────────────────────────────────────────────────────
CO = R["concordancia_1541"]; ws = hoja("Concordancia 1541")
titulo(ws, "Picos de DI y cruces de malla en PCC_1541 (radio 3 m)")
_, a, b = tabla(ws, ["Umbral DI", "Picos", "Cruces", "Precisión", "Recall", "Precisión al azar", "Precisión − azar"],
      [[f["u"], f["n_picos"], f["n_cruces"], f["P"], f["R"], f["azar"], None] for f in CO["pr"]],
      fmt=["0.00", "#,##0", "#,##0", "0.0%", "0.0%", "0.0%", "+0.0%;-0.0%"])
for i in range(a, b + 1):
    ws.cell(i, 7, f"=D{i}-F{i}").number_format = "+0.0%;-0.0%"; ws.cell(i, 7).alignment = Alignment(horizontal="center")
import numpy as np
dl = np.array(CO["desfases"])
titulo(ws, "Desfase pico de DI − cruce de malla más cercano")
tabla(ws, ["Estadístico", "Valor [m]"], [["Picos", int(dl.size)], ["Media", float(dl.mean())], ["Mediana", float(np.median(dl))],
                                        ["Desv. estándar", float(dl.std())]], fmt=[None, "0.00"])

# ── Concordancia por conjunto de caserones ─────────────────────────────────
FCC = os.path.join(os.path.dirname(SRC), "concordancia_caserones.json")
if os.path.exists(FCC):
    CC = json.load(open(FCC, encoding="utf-8")); ws = hoja("Concordancia caserones")
    titulo(ws, "Picos de DI y cruces de malla: 4 caserones, PCC_0042 (calibración) y PCC_1541 (prueba)")
    tabla(ws, ["Conjunto", "Pozos", "Pozos con cruces", "Picos (umbral 1)", "Desfase medio [m]", "Desfase mediano [m]", "σ desfase [m]"],
          [[k, C["n_pozos"], C["n_pozos_con_cruces"], C["desfase"]["n"], C["desfase"]["media"], C["desfase"]["mediana"], C["desfase"]["sd"]]
           for k, C in CC["conjuntos"].items()], fmt=[None, "#,##0", "#,##0", "#,##0", "0.00", "0.00", "0.00"])
    for k, C in CC["conjuntos"].items():
        titulo(ws, f"Sensibilidad al umbral — {k}")
        _, a, b = tabla(ws, ["Umbral DI", "Picos", "Cruces", "Precisión", "Recall", "Precisión al azar", "Precisión − azar"],
                        [[f["u"], f["n_picos"], f["n_cruces"], f["P"], f["R"], f["azar"], None] for f in C["pr"]],
                        fmt=["0.00", "#,##0", "#,##0", "0.0%", "0.0%", "0.0%", "+0.0%;-0.0%"])
        for i in range(a, b + 1):
            ws.cell(i, 7, f"=D{i}-F{i}").number_format = "+0.0%;-0.0%"; ws.cell(i, 7).alignment = Alignment(horizontal="center")
    nota(ws, f"Radio de concordancia {CC['radio_m']:g} m; picos fusionados a < 0,5 m; azar: mismos picos recolocados al azar en su pozo (30 repeticiones).")

# ── Dominios y ranking ─────────────────────────────────────────────────────
Dm = R["dominios"]; ws = hoja("T6.3 Dominios")
titulo(ws, "Tabla 6.3 · Agrupación de dominios geomecánicos")
tabla(ws, ["Grupo", "Litología", "Estructura", "UCS ML media [MPa]", "DI medio", "Tramos", "Registros MWD"],
      [[g["id"], g.get("lito") or "—", g.get("estructura") or "—", g.get("ucsMean"), g.get("diMean"), g.get("n"), g["count"]]
       for g in Dm["grupos"]], fmt=[None, None, None, "0.0", "0.000", "#,##0", "#,##0"])
nota(ws, f"{Dm['n_grupos']} grupos en total; tramos de {Dm['tramo_m']} m, UCS ± {Dm['tol_ucs']} MPa, DI ± {Dm['tol_di']}. Se listan los de mayor muestra.")

RK = R["ranking"]; ws = hoja("T6.4 Ranking")
titulo(ws, f"Tabla 6.4 · Ranking de 5 recomendaciones históricas de perforación — dominio {RK['grupo']}")
CRIT = {"min_se_cv": "Mín. variación de PEP", "min_se": "Mínima PEP", "max_rop": "Máxima ROP"}
tabla(ws, ["Criterio", "N°", "PP [bar]", "RP [bar]", "AP [bar]", "DP [bar]", "FP [bar]", "ROP [m/min]", "PEP [bar·min/m]", "CV PEP", "Pozo", "Prof. [m]", "Registros"],
      [[CRIT[k], i, c["pp"], c["pr"], c["pa"], c["pd"], c["pf"], c["vel"], c["se"], c["se_cv"], c["well"], c["largo"], c["n_pts"]]
       for k, lst in RK["criterios"].items() for i, c in enumerate(lst[:5], 1)],
      fmt=[None, "0", "0", "0", "0", "0", "0.0", "0.00", "0", "0.000", None, "0.0", "0"])

# ── Bloques ────────────────────────────────────────────────────────────────
B = R["bloques"]; ws = hoja("Bloques"); BR = B["resumen"]
titulo(ws, f"Modelo de bloques de {str(B['bloque_m']).replace('.', ',')} m (IDW)")
_, a, b = tabla(ws, ["Caserón", "Bloques", "Registros MWD", "Cobertura"],
                [[k, v["n_bloques"], v["n_muestras"], v["cobertura"]] for k, v in B["por_caseron"].items()],
                fmt=[None, "#,##0", "#,##0", "0.0%"])
ws.cell(b + 1, 1, "Total").font = Font(name=FUENTE, bold=True)
ws.cell(b + 1, 2, f"=SUM(B{a}:B{b})").number_format = "#,##0"; ws.cell(b + 1, 3, f"=SUM(C{a}:C{b})").number_format = "#,##0"
ws._fila = b + 3
_, a, b = tabla(ws, ["Estadístico", "Valor"], [["Volumen [m³]", BR["volumen_m3"]], ["% de bloques con DI > 1", BR["pct_fracturado"] / 100],
                                     ["DI mediana", BR["di_mediana"]], ["UCS mediana [MPa]", BR["ucs_mediana"]],
                                     ["UCS P10 [MPa]", BR["ucs_p10"]], ["UCS P90 [MPa]", BR["ucs_p90"]]],
      fmt=[None, "#,##0.0"])
ws.cell(a + 1, 2).number_format = "0.0%"
BJ = json.load(open(os.path.join(os.path.dirname(SRC), "bloques.json")))
CORTES = [(0, 125, "< 125 MPa"), (125, 150, "125–150 MPa"), (150, 175, "150–175 MPa"), (175, 451, "≥ 175 MPa")]
CDI = ["sana (DI ≤ 1)", "transición (1 < DI ≤ 1,5)", "fracturada (DI > 1,5)"]
MM = [[0] * len(CORTES) for _ in CDI]
for d_, u_ in zip(BJ["di"], BJ["ucs"]):
    if d_ is None or u_ is None: continue
    MM[0 if d_ <= 1.0 else 1 if d_ <= 1.5 else 2][next(k for k, (lo_, hi_, _) in enumerate(CORTES) if lo_ <= u_ < hi_)] += 1
VOL = B["bloque_m"] ** 3
for et_, fac, fmt_ in (("bloques", 1, "#,##0"), ("volumen [m³]", VOL, "#,##0")):
    titulo(ws, f"Clasificación DI × UCS de matriz — {et_}")
    _, a, b = tabla(ws, ["Clase de DI"] + [c[2] for c in CORTES] + ["Total"],
                    [[CDI[i]] + [MM[i][j] * fac for j in range(len(CORTES))] + [None] for i in range(len(CDI))],
                    fmt=[None] + [fmt_] * (len(CORTES) + 1))
    for i in range(a, b + 1):
        ws.cell(i, len(CORTES) + 2, f"=SUM(B{i}:{col(len(CORTES) + 1)}{i})").number_format = fmt_
    ws.cell(b + 1, 1, "Total").font = Font(name=FUENTE, bold=True)
    for j in range(2, len(CORTES) + 3):
        ws.cell(b + 1, j, f"=SUM({col(j)}{a}:{col(j)}{b})").number_format = fmt_
    ws._fila = b + 3
nota(ws, f"Bloque de {str(B['bloque_m']).replace('.', ',')} m = {VOL:g} m³. Clases de UCS cada 25 MPa: todos los bloques caen en la banda ISRM R5.")
titulo(ws, "Bloques por clase de DI")
tabla(ws, ["Clase de DI", "Banda ISRM de UCS", "Bloques"], [[t["di"], t["banda"].replace("_", " "), t["n"]] for t in B["tabla"]],
      fmt=[None, None, "#,##0"])
nota(ws, "Aproximación de apoyo a la tronadura, no modelo geológico validado. Un bloque sin soporte de datos no se incluye.")

wb.save(OUT)
print("OK", OUT, len(wb.sheetnames), "hojas:", wb.sheetnames)
