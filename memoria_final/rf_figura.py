"""Figura F_RF_detalle — zoom al modelo de resistencia (Random Forest).
Todos los números salen de rf_figura_datos.json; nada inventado."""
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

S = "/home/user/Proyecto2/memoria_final"
D = json.load(open(f"{S}/rf_figura_datos.json", encoding="utf-8"))
C, RF = D["config"], D["config"]["rf"]

# Liberation Sans: métricamente compatible con Arial, que no está en el sistema.
plt.rcParams.update({"font.family": "Liberation Sans", "font.size": 8})
PAL = {"tren": ("#DCF0E7", "#2F8F6B"), "bosque": ("#D6E2F0", "#1F4E79"),
       "eval": ("#F5DEDB", "#B03A2E"), "salida": ("#EFEFEF", "#555555")}


def mil(n):
    return f"{int(n):,}".replace(",", ".")


def dec(x, n=1):
    return f"{x:.{n}f}".replace(".", ",")


fig = plt.figure(figsize=(8.27, 16.2))
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")


def caja(x, y, w, h, txt, tipo, fs=7.2, bold=True, align="center"):
    f, b = PAL[tipo]
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.22,rounding_size=0.5",
                                facecolor=f, edgecolor=b, linewidth=1.0, zorder=2))
    L = txt.split("\n"); paso = fs * 0.098
    ty = y + h / 2 + (len(L) - 1) * paso / 2
    for i, ln in enumerate(L):
        ax.text(x + w / 2 if align == "center" else x + 1.1, ty - i * paso, ln,
                ha=align, va="center", fontsize=fs + (0.4 if i == 0 and bold else 0),
                fontweight="bold" if i == 0 and bold else "normal", zorder=3)


def flecha(x1, y1, x2, y2, pz=False, col="#444444"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=9,
                                 linewidth=0.9, color=col, zorder=1,
                                 linestyle=(0, (3, 2)) if pz else "solid"))


def grupo(x, y, w, h, tit, tipo):
    _, b = PAL[tipo]
    ax.add_patch(Rectangle((x, y), w, h, fill=False, edgecolor=b, linewidth=1.1,
                           linestyle=(0, (4, 3)), zorder=1))
    ax.text(x + 1.0, y + h - 1.1, tit, fontsize=9.0, fontweight="bold", color=b,
            va="center", zorder=5,
            bbox=dict(boxstyle="square,pad=0.25", facecolor="white", edgecolor="none"))


fig.text(0.5, 0.990, "Modelo de resistencia: cómo aprende y cómo se evalúa el bosque aleatorio",
         ha="center", fontsize=11.5, fontweight="bold")
fig.text(0.5, 0.9775, f"MWD GeoMech Wizard · {mil(D['embudo'][0]['quedan'])} registros MWD · "
         f"DI calibrado a 5 m · umbral {dec(C['di_threshold'],0)} · ventana {C['di_window']} muestras = "
         f"{dec(C['di_ventana_cm'],0)} cm", ha="center", fontsize=7.6, color="#555555")

# ═════════ A ═════════
grupo(2, 69.5, 96, 26.8, "A.  Construcción del conjunto de entrenamiento", "tren")
emb = {e["etapa"]: e for e in D["embudo"]}
ET = [("total", "Total de registros MWD"),
      ("entrenable", "Emboquillado 2 m, PP 90-230 bar, empate, continuidad"),
      ("con_dominio", "Dentro de una malla (dominio asignado)"),
      ("sin_ambiguedad", "Sin ambigüedad de traslape"),
      ("banda_ucs", "Dominio con banda de UCS"),
      ("rango_ucs", "Etiqueta en el rango físico 0-450 MPa"),
      ("roca_intacta", f"DI ≤ {dec(C['di_threshold'],0)} — roca intacta")]
for i, (k, lab) in enumerate(ET):
    e = emb.get(k, {"quedan": 0, "perdidos": 0})
    yy = 91.8 - i * 3.15
    perd = f"   (−{mil(e['perdidos'])})" if i and e["perdidos"] else ""
    caja(3.3, yy, 43, 2.55, f"{lab}:  {mil(e['quedan'])}{perd}", "tren", fs=7.0,
         bold=False, align="left")
    if i < len(ET) - 1:
        flecha(24.8, yy, 24.8, yy - 0.58)
ax.text(24.8, 71.2, f"Etiqueta por litología, modo «{C['modo_ucs']}»:\n"
        "valor central → media → punto medio de la banda",
        ha="center", va="center", fontsize=6.9, color="#2F8F6B", style="italic")

caja(48.5, 88.0, 22.5, 6.4, "Matriz X — 7 variables\n" + " · ".join(C["ml_labels"][:4]) +
     "\n" + " · ".join(C["ml_labels"][4:]) + "\nuna fila por registro", "tren", fs=7.0)
caja(72.5, 86.0, 24.5, 8.4, "Vector y — UCS de la litología\n" + "\n".join(
    f"{e['litologia']}:  {dec(e['ucs_MPa'],1)} MPa   ({mil(e['n_puntos'])} pts)" for e in D["etiquetas"]),
     "tren", fs=6.7)
caja(48.5, 80.4, 22.5, 6.0, f"Grupos — el POZO\n{D['n_pozos_grupo']} pozos distintos\n"
     "unidad de la validación", "tren", fs=7.0)
caja(72.5, 80.4, 24.5, 4.6, f"Conjunto final\n{mil(emb['roca_intacta']['quedan'])} filas × 7 columnas",
     "tren", fs=7.0)
caja(48.5, 71.0, 48.5, 8.2, "Reparto por caserón\n" + "\n".join(
    f"{c['caseron']}:  {mil(c['n_puntos'])} puntos  /  {c['n_pozos']} pozos" for c in D["por_caseron"]),
     "tren", fs=6.9)

# ═════════ B ═════════
grupo(2, 37.0, 96, 31.0, "B.  El bosque — cómo aprende", "bosque")
caja(3.3, 62.4, 29.5, 4.3, f"Bootstrap\n{RF['n_estimators']} árboles; cada uno recibe una muestra\n"
     "CON REEMPLAZO del mismo tamaño", "bosque", fs=6.9)
caja(35.0, 62.4, 29.5, 4.3, "En cada nodo\nse sortean √7 ≈ 2 variables de las 7\n"
     f"(max_features = «{RF['max_features']}»)", "bosque", fs=6.9)
caja(66.8, 62.4, 30.2, 4.3, "Corte elegido\nel umbral que más reduce el error\ncuadrático del nodo",
     "bosque", fs=6.9)
flecha(33.1, 64.5, 34.8, 64.5); flecha(64.8, 64.5, 66.6, 64.5)

caja(3.3, 57.0, 45.5, 4.4, f"Condiciones de parada\nprofundidad máxima {RF['max_depth']}  ·  "
     f"mínimo {RF['min_samples_split']} muestras para dividir\nmínimo {RF['min_samples_leaf']} muestras por hoja",
     "bosque", fs=6.9)
caja(51.0, 57.0, 46.0, 4.4, "Cada hoja guarda\nel promedio de UCS de las muestras que le\n"
     "tocaron; ese valor es lo que el árbol responde", "bosque", fs=6.9)
flecha(26.0, 62.4, 26.0, 61.6); flecha(74.0, 62.4, 74.0, 61.6)

# inserto: árbol real
AR = D["arbol_ejemplo"]; raiz = AR["raiz"]
caja(3.3, 42.2, 45.5, 13.6, "", "bosque")
ax.text(26.0, 54.7, f"Árbol real del bosque — primeros 2 niveles de {mil(AR['n_nodos'])} nodos",
        ha="center", fontsize=7.1, fontweight="bold")


def nodo(n, x, y, w):
    if n is None: return
    t = (f"hoja\n{mil(n['n_muestras'])} muestras\n{dec(n['valor_UCS'],1)} MPa" if n.get("hoja")
         else f"{n['variable']} ≤ {dec(n['umbral'],2)}\n{mil(n['n_muestras'])} muestras\n{dec(n['valor_UCS'],1)} MPa")
    ax.add_patch(FancyBboxPatch((x - w / 2, y), w, 2.9, boxstyle="round,pad=0.1,rounding_size=0.35",
                                facecolor="white", edgecolor="#1F4E79", linewidth=0.8, zorder=3))
    for i, ln in enumerate(t.split("\n")):
        ax.text(x, y + 2.15 - i * 0.75, ln, ha="center", va="center", fontsize=5.9, zorder=4)


nodo(raiz, 26.0, 50.6, 13.0)
for j, hn in enumerate([raiz.get("izq"), raiz.get("der")]):
    cx = 14.6 + j * 22.8
    nodo(hn, cx, 46.6, 12.0)
    flecha(26.0 + (-3.0 if j == 0 else 3.0), 50.6, cx + (2.6 if j == 0 else -2.6), 49.5)
    if hn and not hn.get("hoja"):
        for k2, nn in enumerate([hn.get("izq"), hn.get("der")]):
            nx = cx - 5.3 + k2 * 10.6
            nodo(nn, nx, 42.6, 10.0)
            flecha(cx + (-1.8 if k2 == 0 else 1.8), 46.6, nx + (1.2 if k2 == 0 else -1.2), 45.5)

caja(51.0, 45.4, 46.0, 9.0, f"Agregación de los {RF['n_estimators']} árboles\n"
     f"UCS_ml  =  MEDIANA de las {RF['n_estimators']} respuestas (p50)\n"
     "P10 y P90 entre árboles  =  banda de incertidumbre\n"
     "la banda se ensancha según la calidad del ancla\ny se acota al rango físico 0-450 MPa",
     "bosque", fs=6.9)
flecha(48.9, 49.0, 50.8, 49.9)
ax.text(50, 39.9, "El bosque NO ajusta pesos ni coeficientes: elige variables y umbrales de corte.",
        ha="center", fontsize=8.0, fontweight="bold", color="#1F4E79")
ax.text(50, 38.4, f"Semilla fija {RF['random_state']} — el mismo conjunto produce siempre el mismo bosque.",
        ha="center", fontsize=6.8, color="#1F4E79", style="italic")
flecha(50, 70.2, 50, 68.0)

# ═════════ C ═════════
grupo(2, 14.0, 96, 21.5, "C.  Evaluación", "eval")
gk, lo = D["groupkfold"], D["loocv"]
caja(3.3, 25.8, 45.5, 7.0, f"GroupKFold por pozo ({gk['n_pliegues']} pliegues)\n"
     "¿predice un tiro nuevo en un caserón conocido?\n"
     f"R² medio = {dec(gk['r2_medio'],3)}   ·   RMSE medio = {dec(gk['rmse_medio'],1)} MPa\n"
     "el pozo entero cae de un solo lado del corte", "eval", fs=6.9)
pl = lo["pliegues"]
l1 = "   ·   ".join(f"{f['pliegue'].split('_')[0]}_{f['pliegue'].split('_')[1]}: "
                    f"{dec(f['r2_reportado'],2) if f.get('r2_reportado') is not None else 'indef.'}"
                    for f in pl[:2])
l2 = "   ·   ".join(f"{f['pliegue'].split('_')[0]}_{f['pliegue'].split('_')[1]}: "
                    f"{dec(f['r2_reportado'],2) if f.get('r2_reportado') is not None else 'indef.'}"
                    for f in pl[2:])
caja(51.0, 25.8, 46.0, 7.0, f"LOOCV-Caserón — un caserón fuera por vez ({len(pl)} iteraciones)\n"
     "¿predice un caserón nunca visto?\n" + f"R²:  {l1}\nR²:  {l2}\n"
     f"R² medio ({lo['n_definidos']} definidos) = {dec(lo['r2_medio_cross_val_score'],3)}   ·   "
     f"RMSE medio = {dec(lo['rmse_medio'],1)} MPa", "eval", fs=6.6)
flecha(26.0, 35.6, 26.0, 33.1); flecha(74.0, 35.6, 74.0, 33.1)
ax.text(74.0, 24.9, "PCS_1059 lleva una sola etiqueta (Kpcli): su R² no está definido.",
        ha="center", fontsize=6.3, color="#B03A2E", style="italic")

caja(3.3, 20.0, 45.5, 4.3, "Contra la línea base\n"
     f"predecir siempre la media ({dec(D['linea_base']['media_global']['prediccion_MPa'],0)} MPa): "
     f"RMSE {dec(D['linea_base']['media_global']['rmse'],1)} MPa\n"
     f"el bosque: {dec(gk['rmse_medio'],1)} MPa   ·   ρ de Spearman por pozo = {dec(D['spearman_ajuste'],3)}",
     "eval", fs=6.9)

imp = D["importancia"]
caja(51.0, 15.0, 46.0, 9.3, "", "eval")
ax.text(74.0, 23.4, "Importancia por permutación", ha="center", fontsize=7.1, fontweight="bold")
ax.text(74.0, 22.4, f"{mil(C['perm_n'])} puntos · semilla {C['perm_semilla']} · sobre pozos no vistos",
        ha="center", fontsize=6.1, color="#555555", style="italic")
items = sorted(imp.items(), key=lambda kv: kv[1])
mx = max(abs(v) for v in imp.values()) or 1
for i, (k, v) in enumerate(items):
    yy = 15.9 + i * 0.90
    ax.text(56.0, yy, k, ha="right", va="center", fontsize=6.2)
    ax.add_patch(Rectangle((56.6, yy - 0.29), 27.0 * abs(v) / mx, 0.58,
                           facecolor="#B03A2E", edgecolor="none", zorder=3))
    ax.text(57.0 + 27.0 * abs(v) / mx, yy, dec(v, 4), va="center", fontsize=5.9, color="#333333")

# ═════════ D ═════════
grupo(2, 1.8, 96, 10.8, "D.  Predicción y salidas", "salida")
ip = D["intervalo_p10_p90"]
caja(3.3, 8.0, 45.5, 3.4, "Se predice sobre TODOS los registros\n"
     f"incluidos los {mil(ip['roca_fracturada']['n'])} fracturados (DI > "
     f"{dec(C['di_threshold'],0)}) que NO entrenaron", "salida", fs=6.9)
caja(51.0, 8.0, 46.0, 3.4, "Banda P10-P90 por punto\n"
     f"roca intacta: {dec(ip['roca_intacta']['ancho_medio_MPa'],1)} MPa de ancho medio\n"
     f"roca fracturada: {dec(ip['roca_fracturada']['ancho_medio_MPa'],1)} MPa", "salida", fs=6.9)
bc = D.get("banda_check", {})
caja(3.3, 4.3, 93.7, 3.1, "Por cada punto:  UCS_ml  ·  banda P10-P90  ·  UCS_matriz (arrastra el "
     f"último valor estable donde DI > {dec(C['di_threshold'],0)})",
     "salida", fs=6.8)
caja(3.3, 2.2, 93.7, 1.6, "Agrupación en dominios (tramos de 2 m)  →  entrada del soporte a "
     "perforación y tronadura", "salida", fs=7.0, bold=False)
flecha(50, 14.2, 50, 11.6); flecha(50, 8.0, 50, 7.5); flecha(50, 4.3, 50, 3.9)

fig.text(0.5, 0.004, "Elaboración propia.  Tipografía Liberation Sans (compatible con Arial).",
         ha="center", fontsize=6.6, color="#666666")
fig.savefig("/home/user/Proyecto2/figuras/F_RF_detalle.png", dpi=300,
            bbox_inches="tight", facecolor="white")
print("F_RF_detalle.png OK")
