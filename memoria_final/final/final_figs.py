"""Figuras y tablas finales del Capítulo 6. Solo DIBUJA: todo número sale de
final.json (final_calc.py). PNG 300 dpi, español, coma decimal, siglas Pucobre
(FP = flujo, AP = avance), PEP = presión específica de penetración."""
import sys, os, json, csv
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

SRC = sys.argv[1]; OUT = sys.argv[2]
os.makedirs(OUT, exist_ok=True)
R = json.load(open(SRC, encoding="utf-8"))
# Estilo de gráfico de Excel: Carlito (métrica de Calibri), sin marco superior
# ni derecho, grilla gris clara, leyenda sin recuadro, título centrado y sin
# pies de figura; el layout restringido elimina el espacio en blanco.
plt.rcParams.update({
    "font.family": "Carlito", "font.size": 11, "text.color": "#262626",
    "axes.titlesize": 12, "axes.titlecolor": "#404040", "axes.labelcolor": "#404040",
    "axes.edgecolor": "#BFBFBF", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "axes.axisbelow": True, "grid.color": "#D9D9D9", "grid.linewidth": 0.8,
    "xtick.color": "#595959", "ytick.color": "#595959", "legend.frameon": False,
    "figure.titlesize": 14, "figure.titleweight": "normal",
    "figure.constrained_layout.use": True, "savefig.pad_inches": 0.04,
})
AZUL, ROJO, VERDE, NARANJA, GRIS, MORADO = "#4472C4", "#C00000", "#70AD47", "#ED7D31", "#A5A5A5", "#7030A0"
COL_LITO = {"Kpcli": "#70AD47", "Bht": "#4472C4", "Kpcls": "#C00000", "Brecha_mixta": "#ED7D31"}
NOM_LITO = {"Kpcli": "Lavas inferiores (Kpcli)", "Bht": "Brecha hidrotermal (Bht)",
            "Kpcls": "Lavas superiores (Kpcls)", "Brecha_mixta": "Brecha mixta"}
SIG = {"pp": "PP", "pr": "RP", "pd": "DP", "pf": "FP", "pa": "AP"}
DI = R["di_vigente"]; W = DI["pesos"]; UMB = DI["umbral"]
hechas = []


def dec(x, n=1):
    if x is None: return "—"
    return f"{x:,.{n}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def mil(n): return f"{int(n):,}".replace(",", ".")


def pesos_txt():
    return " · ".join(f"{SIG[k]} {dec(W[k], 2)}" for k in ("pp", "pr", "pd", "pf") if k in W)


def pie(fig, txt, y=0.005):
    """Sin pies de figura (pedido del autor): el contexto va en el texto de la memoria."""
    return None


def _coma(v, _pos=None):
    t = f"{v:.6f}".rstrip("0").rstrip(".")
    return "0" if t in ("-0", "") else t.replace(".", ",")


def guardar(fig, nombre):
    # Ejes numéricos con coma decimal, como en un Excel en español.
    from matplotlib.ticker import ScalarFormatter, FuncFormatter
    from matplotlib.collections import QuadMesh
    for ax in fig.axes:
        if ax.images or any(isinstance(c, QuadMesh) for c in ax.collections):
            ax.grid(False)   # sin rejilla sobre mapas de calor ni sobre bloques
        for eje in (ax.xaxis, ax.yaxis):
            if type(eje.get_major_formatter()) is ScalarFormatter:
                eje.set_major_formatter(FuncFormatter(_coma))
    fig.savefig(f"{OUT}/{nombre}", dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig); hechas.append(nombre); print("OK", nombre, flush=True)


def tabla_png(nombre, titulo, cab, filas, anchos=None, nota=None, fs=9, ancho_fig=None):
    with open(f"{OUT}/{nombre}.csv", "w", newline="", encoding="utf-8-sig") as fh:
        wr = csv.writer(fh, delimiter=";"); wr.writerow(cab); wr.writerows(filas)
    h = 0.32 * (len(filas) + 1) + 0.35
    fig, ax = plt.subplots(figsize=(ancho_fig or max(7, 1.25 * len(cab)), h)); ax.axis("off")
    t = ax.table(cellText=filas, colLabels=cab, cellLoc="center", colWidths=anchos,
                 bbox=[0, 0, 1, 1])
    t.auto_set_font_size(False); t.set_fontsize(fs + 1)
    # Estilo de tabla de Excel: encabezado azul con texto blanco, filas bandeadas
    for (i, j), c in t.get_celld().items():
        c.set_edgecolor("#FFFFFF"); c.set_linewidth(0.8)
        if i == 0:
            c.set_facecolor("#4472C4"); c.set_text_props(weight="bold", color="white")
        else:
            c.set_facecolor("#D9E1F2" if i % 2 else "#FFFFFF")
    ax.set_title(titulo, fontsize=13, pad=6, loc="center", color="#404040")
    guardar(fig, nombre + ".png")


PIE_CFG = (f"DI calibrado a 5 m ({pesos_txt()}; ventana {DI['window']} muestras ≈ 28 cm; umbral {dec(UMB, 1)}). "
           f"Emboquillado 2 m · percusión de empate {dec(R['limpieza']['umbral_empate'], 2)} · continuidad activa.")

# ── Tabla 6.1 ───────────────────────────────────────────────────────────────
t = R["tabla_6_1"]
tabla_png("T6_01_sensibilidad_percusion_empate", "Sensibilidad del umbral de caída en percusión de empate",
          ["Umbral de caída", "Muestras marcadas", "% del total"],
          [[dec(f["umbral"], 2), mil(f["n"]), dec(f["pct"], 2)] for f in t["filas"]],
          nota=(f"Sobre los {mil(t['n_total'])} registros. Empates esperados por largo de barra "
                f"({dec(t['largo_barra_m'], 3)} m, paso 2 cm): {mil(t['teorico_largo_barra'])}. Umbral adoptado: 0,25."))

# ── 6.1 Pearson ─────────────────────────────────────────────────────────────
pe = R["pearson"]; V = pe["variables"]


def heat(ax, M, titulo):
    M = np.array(M)
    im = ax.imshow(M, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(V))); ax.set_xticklabels(V); ax.set_yticks(range(len(V))); ax.set_yticklabels(V)
    for i in range(len(V)):
        for j in range(len(V)):
            ax.text(j, i, dec(M[i, j], 2), ha="center", va="center", fontsize=9,
                    color="white" if abs(M[i, j]) > 0.6 else "#222222")
    ax.set_title(titulo, fontsize=10.5); return im


fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5.4))
heat(a1, pe["crudas"], "Señales registradas")
im = heat(a2, pe["perfiles_varianza"], "Varianza móvil estandarizada\n(entrada del DI)")
fig.colorbar(im, ax=[a1, a2], shrink=0.8, label="r de Pearson")
fig.suptitle("Correlación de Pearson entre las cinco presiones MWD")
pie(fig, f"n = {mil(pe['n'])} registros, 4 caserones. PP percusión · RP rotación · DP dámper · FP flujo · AP avance.", y=-0.02)
guardar(fig, "F6_01_correlacion_pearson.png")

# ── 6.2 percusión de empate, P20_H12 ────────────────────────────────────────
P = R["pozo_P20_H12"]; L = np.array(P["largo"]); PP = np.array(P["pp"], float)
ix = np.array(P["empate_idx"], int)
fig, (a1, a2) = plt.subplots(2, 1, figsize=(14, 6.8), sharex=True)
a1.plot(L, PP, "-", color=AZUL, lw=0.8)
a1.plot(L[ix], PP[ix], "o", color=ROJO, ms=5.5, mec="white", mew=0.6, zorder=5, label=f"Percusión de empate ({len(ix)})")
a1.set_ylabel("PP [bar]"); a1.grid(alpha=0.3); a1.legend(loc="lower right", fontsize=9)
a1.set_title("Antes del filtro", loc="left", fontsize=10)
keep = np.ones(L.size, bool); keep[ix] = False
a2.plot(L[keep], PP[keep], "-", color=VERDE, lw=0.8)
a2.set_ylabel("PP [bar]"); a2.set_xlabel("Profundidad a lo largo del pozo [m]"); a2.grid(alpha=0.3)
a2.set_title("Después del filtro", loc="left", fontsize=10)
fig.suptitle(f"Filtro de percusión de empate — PCC_0042_PR01_TH_P20_H12 (umbral de caída {dec(R['limpieza']['umbral_empate'], 2)})")
pie(fig, f"Largo {dec(L[-1], 1)} m · {mil(L.size)} registros. Una muestra se marca si cae ≥ 25% bajo el promedio de sus dos vecinas y estas difieren entre sí menos de 12,5%.", y=-0.01); guardar(fig, "F6_02_percusion_empate.png")

# ── localización de los registros filtrados, P20_H12 ───────────────────────
# Cada registro excluido se asigna a UN motivo, en el orden en que se aplican
# los filtros: emboquillado, percusión de empate, rango de PP, continuidad.
EMB = R["limpieza"]["emboquillado_m"]; ENT = np.array(P["entrenable"], bool)
motivo = np.full(L.size, "", dtype=object)
motivo[L < EMB] = "emb"
emp = np.zeros(L.size, bool); emp[ix] = True
motivo[(motivo == "") & emp] = "emp"
motivo[(motivo == "") & ~ENT & ((PP < 90) | (PP > 230))] = "rango"
motivo[(motivo == "") & ~ENT] = "cont"
MOT = [("emb", f"Emboquillado (< {dec(EMB, 0)} m)", GRIS), ("emp", "Percusión de empate", ROJO),
       ("rango", "PP fuera de 90–230 bar", NARANJA), ("cont", "Continuidad del registro", MORADO)]
fig, (a1, a2) = plt.subplots(2, 1, figsize=(14, 6.8), sharex=True)
a1.plot(L, PP, "-", color=AZUL, lw=0.8)
for k, et, c in MOT:
    m = motivo == k
    if m.any():
        a1.plot(L[m], PP[m], "o", color=c, ms=4.5, mec="white", mew=0.5, zorder=5, label=f"{et} ({int(m.sum())})")
a1.set_ylabel("PP [bar]"); a1.legend(loc="lower right", fontsize=9, ncol=2)
a1.set_title("Antes del filtro", loc="left", fontsize=10)
queda = motivo == ""
a2.plot(L[queda], PP[queda], "-", color=VERDE, lw=0.8, label=f"Registros que quedan ({int(queda.sum())})")
a2.axvspan(0, EMB, color=GRIS, alpha=0.25, lw=0, zorder=0, label=f"Emboquillado (< {dec(EMB, 0)} m)")
for k, et, c in MOT[1:]:
    for x_ in L[motivo == k]:
        a2.axvline(x_, color=c, ls=":", lw=0.8, alpha=0.6, zorder=0)
a2.set_ylabel("PP [bar]"); a2.set_xlabel("Profundidad a lo largo del pozo [m]")
a2.set_title("Después del filtro (líneas punteadas: posición de cada registro excluido)", loc="left", fontsize=10)
a2.legend(loc="lower right", fontsize=9, ncol=2)
fig.suptitle(f"Localización de los registros filtrados — PCC_0042_PR01_TH_P20_H12 ({int((~queda).sum())} de {mil(L.size)} registros)")
guardar(fig, "F6_02c_localizacion_registros_filtrados.png")

# ── Tabla 6.2 ───────────────────────────────────────────────────────────────
filas = []
for f in R["tabla_6_2"]["filas"]:
    if f["status"] != "ok":
        filas.append([dec(f["radio_m"], 1), str(f.get("n_intervalos") or 0), str(f.get("n_sondajes") or "—"),
                      "—", "—", "—", "—", "—", "—"]); continue
    w = f["pesos"]
    filas.append([dec(f["radio_m"], 1), str(f["n_pares"]), str(f["n_sondajes"]),
                  dec(w.get("pp", 0), 2), dec(w.get("pr", 0), 2), dec(w.get("pd", 0), 2), dec(w.get("pf", 0), 2),
                  ("+" if f["rho_ajuste"] >= 0 else "") + dec(f["rho_ajuste"], 3),
                  "—" if f["rho_validacion"] is None else ("+" if f["rho_validacion"] >= 0 else "") + dec(f["rho_validacion"], 3)])
T62 = R["tabla_6_2"]
tabla_png("T6_02_sensibilidad_radio_RQD", "Sensibilidad de la calibración del DI al radio de asignación del RQD",
          ["Radio [m]", "Pares", "Sondajes", "Peso PP", "Peso RP", "Peso DP", "Peso FP", "ρ ajuste", "ρ validación"],
          filas,
          nota=(f"Umbral DI {dec(T62['umbral'], 1)} · ventana {T62['ventana']} · {T62['n_candidatos']} combinaciones "
                f"(400 Dirichlet + convención, semilla {T62['semilla']}) · ≥ {T62['min_puntos_intervalo']} puntos por intervalo. "
                "ρ de Spearman entre RQD_MWD y RQD de sondaje; validación dejando un sondaje fuera."))

# ── 6.3 perfil de DI con RQD ────────────────────────────────────────────────
D3 = np.array([np.nan if v is None else v for v in P["di"]])
fig, (ax, ax2) = plt.subplots(2, 1, figsize=(14, 6.4), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
ax.plot(L, D3, "-", color="#1a1a1a", lw=0.7, label="DI")
ax.axhline(UMB, color=ROJO, ls="--", lw=1.2, label=f"Umbral DI = {dec(UMB, 1)}")
ax.fill_between(L, UMB, D3, where=D3 > UMB, color=ROJO, alpha=0.25)
ax.set_ylabel("DI"); ax.grid(alpha=0.3); ax.legend(loc="upper right", fontsize=8.5)
sond = sorted({t["sondaje"] for t in P["tramos_rqd"]}); MK = ["o", "s", "^", "D", "v"]
for k, sd in enumerate(sond):
    tt = [t for t in P["tramos_rqd"] if t["sondaje"] == sd]
    for t in tt:
        a_ = t["largo_pozo_m"] - t["largo_tramo_m"] / 2; b_ = t["largo_pozo_m"] + t["largo_tramo_m"] / 2
        ax2.hlines(t["rqd"], a_, b_, color=VERDE, lw=1.6, alpha=0.7)
    ax2.plot([t["largo_pozo_m"] for t in tt], [t["rqd"] for t in tt], MK[k % 5], color=VERDE, ms=6,
             label=f"RQD sondaje {sd} (d = {dec(min(t['dist_m'] for t in tt), 1)}–{dec(max(t['dist_m'] for t in tt), 1)} m)")
    q = [t for t in tt if t.get("rqd_mwd") is not None]
    ax2.plot([t["largo_pozo_m"] for t in q], [t["rqd_mwd"] for t in q], MK[k % 5], mfc="white", mec="#1a1a1a", ms=6,
             label=f"RQD_MWD del mismo tramo ({sd})")
ax2.set_ylim(0, 105); ax2.set_ylabel("RQD [%]"); ax2.grid(alpha=0.3)
ax2.set_xlabel("Profundidad a lo largo del pozo [m]"); ax2.legend(fontsize=7.5, loc="lower left", ncol=2)
nso = int(np.nansum(D3 > UMB))
fig.suptitle("Índice de discontinuidad calibrado y RQD de sondaje — PCC_0042_PR01_TH_P20_H12")
pie(fig, f"Pesos calibrados a 5 m: {pesos_txt()}. {mil(nso)} de {mil(D3.size)} registros ({dec(100*nso/D3.size, 1)}%) sobre el umbral. "
         f"Tramos de RQD cuyo centro está a ≤ 5 m del pozo ({len(P['tramos_rqd'])}); RQD_MWD = regla de Deere (0,10 m) sobre DI ≤ umbral.", y=-0.03); guardar(fig, "F6_03_perfil_DI_calibrado.png")

# ── sensibilidad del DI a la ventana: 10, 14 y 20 muestras (di_ventanas.py) ─
FV = os.path.join(os.path.dirname(SRC), "di_ventanas.json")
if os.path.exists(FV):
    DV = json.load(open(FV, encoding="utf-8")); VS = DV["ventanas"]; PZ = DV["pozo"]
    CV = {10: AZUL, 14: VERDE, 20: NARANJA}
    Lv = np.array(PZ["largo"])
    fig, ax = plt.subplots(figsize=(14, 4.8))
    for v in VS:
        d = np.array([np.nan if x is None else x for x in PZ[str(v)]["di"]])
        f = next(r for r in PZ["filas"] if r["ventana"] == v)
        ax.plot(Lv, d, "-", color=CV.get(v, GRIS), lw=0.9 if v != 14 else 1.2, alpha=0.9,
                label=f"Ventana {v} ({dec(v * DV['paso_m'] * 100, 0)} cm): {f['picos']} picos · {dec(f['pct_sobre_umbral'], 1)}% sobre el umbral")
    ax.axhline(DV["umbral"], color=ROJO, ls="--", lw=1.2, label=f"Umbral DI = {dec(DV['umbral'], 1)}")
    ax.set_xlabel("Profundidad a lo largo del pozo [m]"); ax.set_ylabel("DI"); ax.legend(fontsize=9, loc="upper right")
    fig.suptitle("Sensibilidad del DI al tamaño de ventana — PCC_0042_PR01_TH_P20_H12")
    guardar(fig, "F6_03b_sensibilidad_ventana_DI.png")
    G = DV["global"]
    tabla_png("T6_05_sensibilidad_ventana_DI", "Sensibilidad del DI al tamaño de ventana",
              ["Ventana [muestras]", "Ventana [cm]", "Picos P20_H12", "% sobre umbral P20_H12",
               "Picos 4 caserones", "Picos por 100 m", "% sobre umbral 4 caserones"],
              [[str(v), dec(G[str(v)]["ventana_cm"], 0), str(next(r["picos"] for r in PZ["filas"] if r["ventana"] == v)),
                dec(next(r["pct_sobre_umbral"] for r in PZ["filas"] if r["ventana"] == v), 1),
                mil(G[str(v)]["picos"]), dec(G[str(v)]["picos_por_100m"], 1), dec(G[str(v)]["pct_sobre_umbral"], 1)]
               for v in VS], ancho_fig=13)

# ── DI medio vs RQD de sondaje (di_rqd_caserones.py) ──────────────────────
FR = os.path.join(os.path.dirname(SRC), "di_rqd_caserones.json")
if os.path.exists(FR):
    DR = json.load(open(FR, encoding="utf-8"))
    fig, axs = plt.subplots(1, len(DR["radios"]), figsize=(15, 5.2), sharey=True)
    SDS = sorted({p["sondaje"] for p in DR["pares"] if p["dist_m"] <= max(DR["radios"]) and p["di_medio"] is not None})
    EST = {sd: (["o", "s", "^", "D", "v"][i % 5], [AZUL, VERDE, NARANJA, MORADO, ROJO][i % 5]) for i, sd in enumerate(SDS)}
    for ax, r in zip(axs, DR["radios"]):
        mejor = {}
        for p in DR["pares"]:
            if p["dist_m"] <= r and p["di_medio"] is not None:
                k = (p["sondaje"], p["desde"])
                if k not in mejor or p["dist_m"] < mejor[k]["dist_m"]: mejor[k] = p
        sel = list(mejor.values())
        for sd in SDS:
            q = [p for p in sel if p["sondaje"] == sd]
            ax.plot([p["di_medio"] for p in q], [p["rqd"] for p in q], EST[sd][0], color=EST[sd][1], ms=6, alpha=0.8)
        f = next(x for x in DR["spearman"] if x["radio_m"] == r and x["caseron"] == "4 caserones")
        ax.set_title(f"Radio {dec(r, 0)} m — n = {f['n_pares']} · ρ = {('+' if f['rho'] >= 0 else '') + dec(f['rho'], 3)} (p = {dec(f['p'], 3)})",
                     fontsize=10.5)
        ax.set_xlabel("DI medio del tramo"); ax.grid(True, axis="both")
    axs[0].set_ylabel("RQD de sondaje [%]"); axs[0].set_ylim(-3, 103)
    fig.legend(handles=[plt.Line2D([], [], ls="", marker=EST[sd][0], color=EST[sd][1], ms=7, label=sd) for sd in SDS],
               fontsize=9.5, ncol=len(SDS), loc="outside lower center")
    fig.suptitle("DI medio y RQD de sondaje — todos los pares caen en PCC_0042")
    guardar(fig, "F6_03c_DI_medio_vs_RQD.png")

# ── 6.5 Spearman del bosque según el esquema de validación ───────────────
gk = R["groupkfold"]; lc = R["loocv_caseron"]
vals = [("GroupKFold\npor pozo", gk["spearman_medio"], ""),
        ("LOOCV-Caserón", float(np.mean([f["spearman"] for f in lc["pliegues"] if f["spearman"] is not None])), "")]
fig, ax = plt.subplots(figsize=(7, 4.8))
bb = ax.bar([v[0] for v in vals], [v[1] for v in vals], color=[AZUL, MORADO], width=0.5)
for b_, (_, x, nt) in zip(bb, vals):
    ax.annotate(("+" if x >= 0 else "") + dec(x, 3) + (f"\n{nt}" if nt else ""), (b_.get_x() + b_.get_width() / 2, x),
                xytext=(0, 4 if x >= 0 else -26), textcoords="offset points", ha="center", fontsize=8.5)
ax.axhline(0, color="#333", lw=0.8); ax.set_ylim(0, 1); ax.set_ylabel("ρ de Spearman (UCS predicha vs. referencial)"); ax.grid(axis="y", alpha=0.3)
fig.suptitle("Ordenamiento de la resistencia según qué se deja fuera del entrenamiento")
pie(fig, "Random Forest con la mediana de sus árboles. Pozo nuevo en caserón conocido · caserón nunca visto · litología nunca vista. "
         "En LOOCV-Caserón, PCS_1059 tiene una sola etiqueta y su ρ no está definido.", y=-0.04); guardar(fig, "F6_05_spearman_por_esquema.png")

# ── 6.4 LOOCV-Caserón: ρ de Spearman y R² por caserón dejado fuera ────────
PL = lc["pliegues"]; nom = [f["pliegue"] for f in PL]; xx = np.arange(len(PL))
fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5))
for ax, clave, et, col, lim in ((a1, "spearman", "ρ de Spearman (UCS predicha vs. referencial)", MORADO, (0, 1)),
                                (a2, "r2", "R²", AZUL, None)):
    v = [f[clave] for f in PL]
    bb = ax.bar(xx, [0 if x is None else x for x in v], color=col, width=0.55)
    for b_, x, f in zip(bb, v, PL):
        cx = b_.get_x() + b_.get_width() / 2
        if x is None:
            ax.annotate("indefinido\n(una sola etiqueta)", (cx, 0), xytext=(0, 4 if lim else -6), textcoords="offset points",
                        ha="center", va="bottom" if lim else "top", fontsize=8.5, color="#595959")
        else:
            ax.annotate(("+" if x >= 0 else "") + dec(x, 3), (cx, x), xytext=(0, 4 if x >= 0 else -13),
                        textcoords="offset points", ha="center", fontsize=9)
    dfn = [x for x in v if x is not None]; mu = float(np.mean(dfn))
    ax.axhline(mu, color="#333", ls="--", lw=1, label=f"Media de los definidos: {('+' if mu >= 0 else '') + dec(mu, 3)}")
    ax.axhline(0, color="#333", lw=0.8)
    ax.set_xticks(xx); ax.set_xticklabels([f"{n}\n({mil(f['n_prueba'])} reg.)" for n, f in zip(nom, PL)])
    ax.set_ylabel(et); ax.set_xlabel("Caserón dejado fuera del entrenamiento")
    ax.legend(fontsize=9, loc="upper right" if lim else "lower right")
    ax.set_ylim(*(lim or (min(dfn) - 0.5, 0.25)))
a1.set_title("Ordenamiento de la resistencia", fontsize=10.5); a2.set_title("Varianza explicada", fontsize=10.5)
fig.suptitle("Validación LOOCV-Caserón del Random Forest")
guardar(fig, "F6_04_LOOCV_caseron.png")

# ── 6.4b los cuatro métodos bajo LOOCV-Caserón (loocv_caseron_metodos.py) ──
FL = os.path.join(os.path.dirname(SRC), "loocv_caseron_metodos.json")
if os.path.exists(FL):
    LM = json.load(open(FL, encoding="utf-8")); MD = LM["medias"]
    MET = [("linea_base", "Línea base\n(media litología)", "#7F7F7F"), ("banda", "Banda\npor unidad", NARANJA),
           ("relacion", "Relación directa\nPEP↔UCS", "#2E7D57"), ("ml", "ML\n(Random Forest)", "#2F5597")]
    fig, axs = plt.subplots(1, 3, figsize=(16, 5.2))
    for ax, cl, et, nd in ((axs[0], "rmse", "RMSE [MPa]", 1), (axs[1], "pearson", "r de Pearson", 3),
                           (axs[2], "spearman", "ρ de Spearman", 3)):
        v = [MD[k][cl] for k, _, _ in MET]
        bb = ax.bar(range(len(MET)), [0 if x is None else x for x in v], color=[c for _, _, c in MET], width=0.62)
        for b_, x in zip(bb, v):
            cx = b_.get_x() + b_.get_width() / 2
            if x is None:
                ax.annotate("indefinido\n(predicción\nconstante)", (cx, 0), xytext=(0, 4), textcoords="offset points",
                            ha="center", va="bottom", fontsize=8.5, color="#595959")
            else:
                ax.annotate((("+" if x >= 0 else "") if cl != "rmse" else "") + dec(x, nd), (cx, x),
                            xytext=(0, 4 if x >= 0 else -13), textcoords="offset points", ha="center", fontsize=9.5)
        ax.set_xticks(range(len(MET))); ax.set_xticklabels([e for _, e, _ in MET], fontsize=9)
        ax.set_ylabel(et); ax.axhline(0, color="#333", lw=0.8)
        if cl != "rmse":
            dfn = [x for x in v if x is not None]
            ax.set_ylim(min(dfn) - 0.1 if min(dfn) < 0 else 0, 1)
    axs[0].set_title("Error", fontsize=10.5); axs[1].set_title("Correlación lineal", fontsize=10.5)
    axs[2].set_title("Ordenamiento", fontsize=10.5)
    fig.suptitle("Comparación de métodos de UCS — LOOCV-Caserón (media de los caserones dejados fuera)")
    guardar(fig, "F6_04b_LOOCV_caseron_metodos.png")

# ── 6.6 PEP vs UCS predicha ─────────────────────────────────────────────────
S6 = R["pep_vs_ucs"]
fig, axs = plt.subplots(1, 2, figsize=(13, 5.2), sharey=True)
for ax, k, tit in ((axs[0], "intacta", f"Roca intacta (DI ≤ {dec(UMB, 1)})"), (axs[1], "fracturada", f"Roca fracturada (DI > {dec(UMB, 1)})")):
    d = S6[k]; pep = np.array(d["pep"]); u = np.array(d["ucs_ml"])
    for lito, c in COL_LITO.items():
        m = np.array([l == lito for l in d["lito"]])
        if m.any(): ax.scatter(pep[m], u[m], s=2, alpha=0.25, color=c, label=NOM_LITO[lito], rasterized=True)
    ax.set_xscale("log"); ax.set_xlabel("PEP [bar·min/m] (escala log)"); ax.grid(alpha=0.3)
    ax.set_title(f"{tit} — n = {mil(d['n'])}", fontsize=10)
axs[0].set_ylabel("UCS predicha [MPa]")
lg = axs[0].legend(fontsize=8, markerscale=5, loc="upper left")
for hnd in lg.legend_handles: hnd.set_alpha(1)
fig.suptitle("Presión específica de penetración (PEP) y UCS predicha por el modelo")
pie(fig, "Muestra aleatoria de 25.000 registros por panel (semilla 42), ROP ≥ 0,2 m/min. " + PIE_CFG, y=-0.03); guardar(fig, "F6_06_PEP_vs_UCS.png")

# ── 6.6b PEP vs UCS predicha: dominio de entrenamiento y extrapolación ─────
# Una sola vista: el bosque se entrena SOLO con DI ≤ umbral, así que lo que
# predice sobre roca fracturada es extrapolación.
fig, ax = plt.subplots(figsize=(10, 6.2))
# Las dos muestras son de 25.000; la fracturada se submuestrea a la proporción
# real de las clases para que la nube no exagere su peso.
_prop = S6["fracturada"]["n"] / S6["intacta"]["n"]
for k, mk, c, et in (("intacta", "o", AZUL, f"DI ≤ {dec(UMB, 0)}, roca intacta — dominio de entrenamiento"),
                     ("fracturada", "x", ROJO, f"DI > {dec(UMB, 0)}, fracturada — EXTRAPOLACIÓN")):
    d = S6[k]; pep = np.array(d["pep"]); u = np.array(d["ucs_ml"])
    m = pep <= 1000
    if k == "fracturada":
        keep = np.zeros(pep.size, bool)
        keep[np.random.default_rng(42).choice(pep.size, int(round(pep.size * _prop)), replace=False)] = True
        m &= keep
    ax.scatter(pep[m], u[m], s=5 if mk == "o" else 8, marker=mk, alpha=0.3 if mk == "o" else 0.5,
               lw=0 if mk == "o" else 0.6, color=c, rasterized=True, label=f"{et} (n = {mil(d['n'])})")
ax.set_xlim(-40, 1040)
ax.set_xlabel("PEP = (PP + RP + AP) / ROP [bar·min/m]  (PEP ≤ 1.000)"); ax.set_ylabel("UCS predicha por ML [MPa]")
ax.grid(True, axis="both")
h, l = ax.get_legend_handles_labels()
lg = ax.legend(h[::-1], l[::-1], loc="upper right", fontsize=9, markerscale=2.5, frameon=True, framealpha=0.9)
for hnd in lg.legend_handles: hnd.set_alpha(1)
guardar(fig, "F6_06b_PEP_vs_UCS_extrapolacion.png")

# ── 6.6c PEP vs UCS predicha: ajuste SOLO sobre roca intacta ───────────────
# La fracturada se dibuja en un solo color y no participa de ningún ajuste: el
# modelo no se entrena con ella y su UCS predicha es extrapolación.
from scipy.optimize import curve_fit


def _ajustes_intacta(x, y):
    sst = float(np.sum((y - y.mean()) ** 2)); out = {}
    def r2(p): return 1 - float(np.sum((y - p) ** 2)) / sst
    for g, nom in ((1, "lineal"), (2, "parabólico"), (3, "cúbico")):
        c = np.polyfit(x, y, g); out[nom] = (r2(np.polyval(c, x)), lambda t, c=c: np.polyval(c, t), c)
    k_, n_ = np.polyfit(np.log(x), np.log(y), 1)[::-1]; k_ = np.exp(k_)
    out["potencial"] = (r2(k_ * x ** n_), lambda t, k=k_, n=n_: k * t ** n, (k_, n_))
    a_, b_ = np.polyfit(np.log(x), y, 1)
    out["logarítmico"] = (r2(a_ * np.log(x) + b_), lambda t, a=a_, b=b_: a * np.log(t) + b, (a_, b_))
    f = lambda t, a, b, c: a - b * np.exp(-t / c)
    try:
        p_, _ = curve_fit(f, x, y, p0=(170.0, 80.0, 150.0), maxfev=20000)
        out["saturación"] = (r2(f(x, *p_)), lambda t, p=p_: f(t, *p), tuple(p_))
    except RuntimeError:
        pass
    return out


def _ecuacion(nom, c):
    if nom == "lineal": return f"UCS = {dec(c[0], 4)}·PEP + {dec(c[1], 1)}"
    if nom == "parabólico": return f"UCS = {dec(c[0], 6)}·PEP² + {dec(c[1], 4)}·PEP + {dec(c[2], 1)}"
    if nom == "cúbico": return f"UCS = {dec(c[0], 9)}·PEP³ {dec(c[1], 6)}·PEP² + {dec(c[2], 4)}·PEP + {dec(c[3], 1)}"
    if nom == "potencial": return f"UCS = {dec(c[0], 3)}·PEP^{dec(c[1], 4)}"
    if nom == "logarítmico": return f"UCS = {dec(c[0], 3)}·ln(PEP) + {dec(c[1], 1)}"
    return f"UCS = {dec(c[0], 1)} − {dec(c[1], 1)}·e^(−PEP/{dec(c[2], 1)})"


di_ = S6["intacta"]; pep_i = np.array(di_["pep"]); u_i = np.array(di_["ucs_ml"]); lit_i = np.array(di_["lito"])
mi = (pep_i <= 1000) & (pep_i > 0)
AJ = _ajustes_intacta(pep_i[mi], u_i[mi])
# Parsimonia: entre las formas a menos de 0,01 de R² del máximo, la de menos
# coeficientes (el cúbico gana 0,005 al parabólico con un parámetro más).
_NPAR = {"lineal": 2, "potencial": 2, "logarítmico": 2, "parabólico": 3, "saturación": 3, "cúbico": 4}
_r2max = max(v[0] for v in AJ.values())
mejor = min((k for k in AJ if AJ[k][0] >= _r2max - 0.01), key=lambda k: (_NPAR[k], -AJ[k][0]))
R["ajuste_pep_ucs_intacta"] = {k: {"r2": round(v[0], 4), "coef": [float(t) for t in v[2]]} for k, v in AJ.items()}
print("ajustes intacta:", {k: round(v[0], 4) for k, v in AJ.items()}, "→", mejor, flush=True)
fig, ax = plt.subplots(figsize=(10, 6.2))
for lito in sorted(set(lit_i[mi]), key=lambda l: {"Kpcls": 0, "Brecha_mixta": 1, "Bht": 2, "Kpcli": 3}.get(l, 9)):
    m = mi & (lit_i == lito)
    ax.scatter(pep_i[m], u_i[m], s=5, lw=0, alpha=0.35, color=COL_LITO.get(lito, GRIS), rasterized=True,
               label=f"DI ≤ {dec(UMB, 0)} · {NOM_LITO.get(lito, lito)}")
df_ = S6["fracturada"]; pep_f = np.array(df_["pep"]); u_f = np.array(df_["ucs_ml"])
keep = np.zeros(pep_f.size, bool)
keep[np.random.default_rng(42).choice(pep_f.size, int(round(pep_f.size * df_["n"] / di_["n"])), replace=False)] = True
mf = keep & (pep_f <= 1000)
ax.scatter(pep_f[mf], u_f[mf], s=8, marker="x", lw=0.6, alpha=0.45, color="#7F7F7F", rasterized=True,
           label=f"DI > {dec(UMB, 0)}, fracturada — EXTRAPOLACIÓN, fuera del ajuste (n = {mil(df_['n'])})")
xx = np.linspace(max(5, pep_i[mi].min()), 1000, 400)
ax.plot(xx, AJ[mejor][1](xx), "-", color="#1a1a1a", lw=2,
        label=f"Ajuste {mejor} (solo intacta): {_ecuacion(mejor, AJ[mejor][2])} · R² = {dec(AJ[mejor][0], 3)}")
ax.set_xlim(-40, 1040)
ax.set_xlabel("PEP = (PP + RP + AP) / ROP [bar·min/m]  (PEP ≤ 1.000)"); ax.set_ylabel("UCS predicha por ML [MPa]")
ax.grid(True, axis="both")
lg = ax.legend(loc="lower right", fontsize=8.5, markerscale=2.5, frameon=True, framealpha=0.92)
for hnd in lg.legend_handles: hnd.set_alpha(1)
guardar(fig, "F6_06c_PEP_vs_UCS_ajuste_intacta.png")

# ── 6.7 UCS lab vs ML por litología ─────────────────────────────────────────
U7 = R["ucs_por_litologia"]
orden = sorted(U7, key=lambda k: U7[k]["ancla"] or 0)
# Boxplot desde la curva de cuantiles guardada (400 registros ordenados):
# caja P25–P75, mediana, bigotes P10–P90 (exactos en final.json). Sin atípicos:
# con cientos de miles de registros por litología solo ensuciarían la vista.
fig, ax = plt.subplots(figsize=(10, 5.6))
stats = []
for lito in orden:
    d = U7[lito]; cv_ = np.array(d["curva"])
    stats.append({"label": f"{NOM_LITO.get(lito, lito)}\nn = {mil(d['n'])}", "med": d["p50"],
                  "q1": float(np.percentile(cv_, 25)), "q3": float(np.percentile(cv_, 75)),
                  "whislo": d["p10"], "whishi": d["p90"], "fliers": []})
bp = ax.bxp(stats, positions=range(len(orden)), widths=0.5, patch_artist=True, showfliers=False,
            medianprops=dict(color="#1a1a1a", lw=1.8), whiskerprops=dict(color="#595959"), capprops=dict(color="#595959"))
for caja, lito in zip(bp["boxes"], orden):
    caja.set_facecolor(COL_LITO.get(lito, GRIS)); caja.set_alpha(0.75); caja.set_edgecolor("#404040")
for k, lito in enumerate(orden):
    d = U7[lito]
    ax.plot(k, d["ancla"], marker="D", ms=9, color="white", mec="#C00000", mew=2, zorder=6)
    ax.annotate(f"ref. {dec(d['ancla'], 1)}\np50 {dec(d['p50'], 1)}", (k + 0.28, d["ancla"]), va="center", fontsize=8.5)
ax.set_ylim(0, 220); ax.set_ylabel("UCS [MPa]"); ax.set_xlim(-0.6, len(orden) - 0.2)
ax.legend(handles=[Patch(facecolor="#BFBFBF", edgecolor="#404040", label="UCS predicha: caja P25–P75, línea mediana, bigotes P10–P90"),
                   plt.Line2D([], [], ls="", marker="D", ms=8, color="white", mec="#C00000", mew=2, label="UCS de laboratorio (referencial)")],
          loc="lower right", fontsize=8.5, frameon=True, framealpha=0.9)
fig.suptitle("UCS de laboratorio y UCS predicha por litología")
guardar(fig, "F6_07_UCS_lab_vs_ML.png")

# ── 6.8 comparación de algoritmos ───────────────────────────────────────────
C = R["comparacion"]; rows = [r for r in C.get("rows", []) if r.get("r2_mean") is not None]
fig, ax = plt.subplots(figsize=(10, 5))
xx = np.arange(len(rows)); wdt = 0.38
tr = [r.get("r2_train_mean") for r in rows]; te = [r["r2_mean"] for r in rows]
b1 = ax.bar(xx - wdt / 2, tr, wdt, color="#9DB6CF", label="Entrenamiento")
b2 = ax.bar(xx + wdt / 2, te, wdt, color=AZUL, label="Prueba (pozos no vistos)")
for b_, x in list(zip(b1, tr)) + list(zip(b2, te)):
    if x is None: continue
    ax.annotate(("+" if x >= 0 else "") + dec(x, 3), (b_.get_x() + b_.get_width() / 2, x),
                xytext=(0, 3 if x >= 0 else -12), textcoords="offset points", ha="center", fontsize=8.5)
ax.set_xticks(xx); ax.set_xticklabels([r["modelo"] for r in rows]); ax.axhline(0, color="#333", lw=0.8)
ax.set_ylabel("R²"); ax.legend(fontsize=9); ax.grid(axis="y", alpha=0.3)
fig.suptitle("Comparación de algoritmos — GroupKFold por pozo")
pie(fig, f"Mismos {mil(C.get('n_samples', 0))} registros para los cinco modelos (submuestreo por pozo completo, semilla 42), {C.get('n_grupos')} pozos. "
         "Random Forest evaluado con la mediana de sus árboles. Prueba = media de los pliegues.", y=-0.04); guardar(fig, "F6_08_comparacion_algoritmos.png")

# ── 6.9 desfases y concordancia en PCC_1541 ─────────────────────────────────
CO = R["concordancia_1541"]; dl = np.array(CO["desfases"]); PRr = CO["pr"]
fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.5, 5.4))
a1.hist(dl, bins=np.arange(-30, 30.5, 1.0), color=AZUL, alpha=0.85, edgecolor="white", lw=0.3)
a1.axvline(0, color="#333", lw=0.9)
a1.axvline(dl.mean(), color=ROJO, ls="--", lw=1.4, label=f"Media {dec(dl.mean(), 2)} m")
a1.axvline(np.median(dl), color=VERDE, ls="--", lw=1.4, label=f"Mediana {dec(np.median(dl), 2)} m")
a1.set_xlim(-25, 25); a1.set_xlabel("Pico de DI − cruce de malla más cercano [m]"); a1.set_ylabel("N° de picos")
a1.legend(fontsize=8.5); a1.grid(alpha=0.25)
a1.text(0.02, 0.97, f"σ = {dec(dl.std(), 2)} m\nn = {mil(dl.size)} picos", transform=a1.transAxes, va="top", fontsize=8.5)
uu = [f["u"] for f in PRr]
a2.plot(uu, [100 * f["P"] for f in PRr], "o-", color=AZUL, label="Precisión: picos a ≤ 3 m de un cruce")
a2.plot(uu, [100 * f["R"] for f in PRr], "s-", color=ROJO, label="Recall: cruces con un pico a ≤ 3 m")
a2.plot(uu, [100 * f["azar"] for f in PRr], ":", color=GRIS, lw=2, label="Precisión esperada al azar")
a2.axvline(UMB, color="#333", ls="--", lw=0.9)
f1 = next(f for f in PRr if abs(f["u"] - UMB) < 1e-9)
a2.annotate(f"umbral {dec(UMB, 1)}: precisión {dec(100*f1['P'], 1)}% · azar {dec(100*f1['azar'], 1)}%",
            (UMB, 100 * f1["P"]), xytext=(10, 18), textcoords="offset points", fontsize=8.5, arrowprops=dict(arrowstyle="-", color="#555"))
a2.set_xlabel("Umbral de DI"); a2.set_ylabel("%"); a2.set_ylim(0, 100); a2.legend(fontsize=8); a2.grid(alpha=0.3)
fig.suptitle("Picos de DI y cruces de malla (litología y estructura) — PCC_1541")
pie(fig, f"{CO['n_pozos']} pozos con cruces; picos fusionados a < 0,5 m; radio de concordancia {dec(CO['radio_m'], 0)} m. "
         "La malla es una interpolación, no verdad terreno. Azar: mismos picos recolocados al azar en su pozo (30 repeticiones). " + PIE_CFG, y=-0.04); guardar(fig, "F6_09_desfase_DI_mallas_PCC1541.png")

# ── desfase y sensibilidad al umbral: 4 caserones, PCC_0042 y PCC_1541 ─────
FCC = os.path.join(os.path.dirname(SRC), "concordancia_caserones.json")
if os.path.exists(FCC):
    CC = json.load(open(FCC, encoding="utf-8"))
    ET = {"4 caserones": "Cuatro caserones", "PCC_0042": "PCC_0042 (calibración del DI)", "PCC_1541": "PCC_1541 (prueba)"}
    fig, axs = plt.subplots(3, 2, figsize=(13.5, 13), gridspec_kw={"width_ratios": [1.1, 1]})
    for fila, (nom, C) in zip(axs, CC["conjuntos"].items()):
        a1, a2 = fila; dl = np.array(C["desfases"]); PRr = C["pr"]
        a1.hist(dl, bins=np.arange(-30, 30.5, 1.0), color=AZUL, alpha=0.85, edgecolor="white", lw=0.3)
        a1.axvline(0, color="#333", lw=0.9)
        a1.axvline(dl.mean(), color=ROJO, ls="--", lw=1.4, label=f"Media {dec(dl.mean(), 2)} m")
        a1.axvline(np.median(dl), color=VERDE, ls="--", lw=1.4, label=f"Mediana {dec(np.median(dl), 2)} m")
        a1.set_xlim(-25, 25); a1.set_ylabel("N° de picos"); a1.legend(fontsize=8.5, loc="upper right")
        a1.text(0.02, 0.97, f"σ = {dec(dl.std(), 2)} m\nn = {mil(dl.size)} picos\n{C['n_pozos_con_cruces']} pozos con cruces",
                transform=a1.transAxes, va="top", fontsize=8.5)
        a1.set_title(f"{ET[nom]} — desfase pico–cruce", fontsize=10.5)
        uu = [f["u"] for f in PRr]
        a2.plot(uu, [100 * f["P"] for f in PRr], "o-", color=AZUL, label="Precisión: picos a ≤ 3 m de un cruce")
        a2.plot(uu, [100 * f["R"] for f in PRr], "s-", color=ROJO, label="Recall: cruces con un pico a ≤ 3 m")
        a2.plot(uu, [100 * f["azar"] for f in PRr], ":", color=GRIS, lw=2, label="Precisión esperada al azar")
        a2.axvline(UMB, color="#333", ls="--", lw=0.9)
        f1 = next(f for f in PRr if abs(f["u"] - UMB) < 1e-9)
        a2.annotate(f"umbral {dec(UMB, 1)}: precisión {dec(100 * f1['P'], 1)}% · azar {dec(100 * f1['azar'], 1)}%",
                    (UMB, 100 * f1["P"]), xytext=(10, 18), textcoords="offset points", fontsize=8.5,
                    arrowprops=dict(arrowstyle="-", color="#555"))
        a2.set_ylabel("%"); a2.set_ylim(0, 100); a2.set_title(f"{ET[nom]} — sensibilidad al umbral", fontsize=10.5)
    axs[-1][0].set_xlabel("Pico de DI − cruce de malla más cercano [m]"); axs[-1][1].set_xlabel("Umbral de DI")
    h_, l_ = axs[0][1].get_legend_handles_labels()
    fig.legend(h_, l_, fontsize=9.5, ncol=3, loc="outside lower center")
    fig.suptitle("Picos de DI y cruces de malla (litología y estructura) por conjunto de caserones")
    guardar(fig, "F6_09b_desfase_umbral_por_caseron.png")

# ── 6.10 perfil PCS_1043_PR01_TH_P07_H4 ─────────────────────────────────────
Q = R.get("pozo_P07_H4")
if Q:
    L = np.array(Q["largo"])

    def med(a, k=5):
        a = np.array([np.nan if v is None else v for v in a], float)
        out = np.copy(a)
        for i in range(a.size):
            s_ = a[max(0, i - k // 2): i + k // 2 + 1]; out[i] = np.nanmedian(s_) if np.isfinite(s_).any() else np.nan
        return out
    series = [("ROP [m/min]", med(Q["vel"]), "#333"), ("PP [bar]", med(Q["pp"]), AZUL), ("DP [bar]", med(Q["pd"]), MORADO),
              ("RP [bar]", med(Q["pr"]), NARANJA), ("FP [bar]", med(Q["pf"]), "#1F9E9E"), ("AP [bar]", med(Q["pa"]), GRIS),
              ("PEP [bar·min/m]", med([v if (v is not None and v <= 1000) else None for v in Q["se"]]), ROJO)]
    fig, axs = plt.subplots(len(series) + 3, 1, figsize=(13, 15), sharex=True,
                            gridspec_kw={"height_ratios": [1] * len(series) + [1.3, 1.3, 0.45]})
    for ax, (et, s_, c) in zip(axs, series):
        ax.plot(L, s_, color=c, lw=0.8); ax.set_ylabel(et, fontsize=8.5); ax.grid(alpha=0.3)
    axs[-3].plot(L, med(Q["ucs_ml"]), color=AZUL, lw=1)
    axs[-3].fill_between(L, med(Q["ucs_ml_p10"]), med(Q["ucs_ml_p90"]), color=AZUL, alpha=0.18, label="P10–P90")
    axs[-3].set_ylabel("UCS ML [MPa]", fontsize=8.5); axs[-3].grid(alpha=0.3); axs[-3].legend(fontsize=8, loc="upper left")
    dd = np.array([np.nan if v is None else v for v in Q["di"]])
    axs[-2].plot(L, dd, color="#1a1a1a", lw=0.7); axs[-2].axhline(UMB, color=ROJO, ls="--", lw=1)
    axs[-2].fill_between(L, UMB, dd, where=dd > UMB, color=ROJO, alpha=0.25)
    axs[-2].set_ylabel("DI", fontsize=8.5); axs[-2].grid(alpha=0.3)
    ax = axs[-1]; ax.set_yticks([0.5, 1.5]); ax.set_yticklabels(["Estructura", "Litología"], fontsize=8); ax.set_ylim(0, 2)
    PAL = ["#7B2D8E", "#D4A017", "#1F9E9E", "#B5446E"]; ests = sorted({e for e in Q["estructura"] if e})
    for serie, y0, col in ((Q["lito"], 1, lambda v: COL_LITO.get(v, GRIS)), (Q["estructura"], 0, lambda v: PAL[ests.index(v) % 4])):
        ini = 0
        for i in range(1, len(serie) + 1):
            if i == len(serie) or serie[i] != serie[ini]:
                if serie[ini]: ax.axvspan(L[ini], L[i - 1], ymin=y0 / 2 + 0.05, ymax=y0 / 2 + 0.45, color=col(serie[ini]))
                ini = i
    hs = [Patch(color=COL_LITO.get(l, GRIS), label=NOM_LITO.get(l, l)) for l in sorted({l for l in Q["lito"] if l})]
    hs += [Patch(color=PAL[i % 4], label=e) for i, e in enumerate(ests)]
    fig.legend(handles=hs, fontsize=9, ncol=6, loc="outside lower center")
    ax.set_xlabel("Profundidad a lo largo del pozo [m]")
    fig.suptitle("Registros MWD, PEP, UCS predicha y DI — PCS_1043_PR01_TH_P07_H4")
    pie(fig, "Series suavizadas con mediana móvil de 5 registros (≈ 10 cm). PEP ≤ 1.000 bar·min/m: con ROP ≈ 0 la PEP no tiene sentido físico y se omite. " + PIE_CFG, y=-0.02); guardar(fig, "F6_10_perfil_PCS1043_P07_H4.png")

# ── 6.11 sección de tronadura ───────────────────────────────────────────────
B = R["bloques"]
if B.get("status") == "ok" and B.get("seccion", {}).get("x"):
    s_ = B["seccion"]; x = np.array(s_["x"]); z = np.array(s_["z"]); lado = B["bloque_m"]
    fig, axs = plt.subplots(1, 2, figsize=(14, 5.6), sharey=True)
    for ax, var, cmap, lab, vmin, vmax in ((axs[0], "di", "RdYlGn_r", "DI", 0, 2.5), (axs[1], "ucs", "viridis", "UCS [MPa]", 50, 250)):
        vv = np.array([np.nan if v is None else v for v in s_[var]], float)
        ix_ = np.round((x - x.min()) / lado).astype(int); iz_ = np.round((z - z.min()) / lado).astype(int)
        G = np.full((iz_.max() + 1, ix_.max() + 1), np.nan); G[iz_, ix_] = vv
        sc = ax.pcolormesh(x.min() - lado / 2 + lado * np.arange(ix_.max() + 2),
                           z.min() - lado / 2 + lado * np.arange(iz_.max() + 2),
                           np.ma.masked_invalid(G), cmap=cmap, vmin=vmin, vmax=vmax, edgecolors="white", linewidth=0.15)
        ax.set_aspect("equal"); ax.set_xlabel("Este [m]"); ax.grid(alpha=0.2)
        fig.colorbar(sc, ax=ax, shrink=0.8, label=lab)
        ax.ticklabel_format(useOffset=False, style="plain")
    axs[0].set_ylabel("Cota [m]")
    axs[0].set_title("Índice de discontinuidad", fontsize=10.5); axs[1].set_title("UCS de matriz predicha", fontsize=10.5)
    fig.suptitle(f"Sección vertical del caserón PCC_0042 — Norte ≈ {dec(s_['norte'], 0)} m (bloques de {dec(lado, 1)} m)")
    pie(fig, f"IDW anisotrópico; un bloque sin soporte de datos no se dibuja. Apoyo a la tronadura, no modelo geológico validado. {PIE_CFG}", y=-0.04); guardar(fig, "F6_11_seccion_tronadura_PCC0042.png")

    # ── 6.12 clasificación DI × UCS de bloques ──────────────────────────────
    BJ = json.load(open(os.path.join(os.path.dirname(SRC), "bloques.json")))
    cdi = ["sana (DI ≤ 1)", "transición (1 < DI ≤ 1,5)", "fracturada (DI > 1,5)"]
    CORTES = [(0, 125, "< 125 MPa"), (125, 150, "125–150 MPa"), (150, 175, "150–175 MPa"), (175, 451, "≥ 175 MPa")]
    def _ci(d): return 0 if d <= 1.0 else (1 if d <= 1.5 else 2)
    M = np.zeros((3, len(CORTES)))
    for d, u in zip(BJ["di"], BJ["ucs"]):
        if d is None or u is None: continue
        j = next(k for k, (lo_, hi_, _) in enumerate(CORTES) if lo_ <= u < hi_)
        M[_ci(d), j] += 1
    N = M.sum()
    fig, ax = plt.subplots(figsize=(9.6, 4.6))
    im = ax.imshow(M / N * 100, cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(CORTES))); ax.set_xticklabels([c[2] for c in CORTES])
    ax.set_xlabel("UCS de matriz predicha del bloque")
    ax.set_yticks(range(3)); ax.set_yticklabels(cdi)
    for i in range(3):
        for j in range(len(CORTES)):
            ax.text(j, i, f"{mil(M[i, j])} bloque{'' if M[i, j] == 1 else 's'}\n{mil(round(M[i, j] * B['bloque_m'] ** 3))} m³\n{dec(100 * M[i, j] / N, 1)}%", ha="center", va="center", fontsize=9,
                    color="white" if M[i, j] / N > 0.35 else "#222")
    fig.colorbar(im, ax=ax, shrink=0.85, label="% de los bloques")
    fig.suptitle(f"Clasificación de {mil(N)} bloques de {dec(B['bloque_m'], 1)} m ({mil(round(N * B['bloque_m'] ** 3))} m³) según DI y UCS")
    pie(fig, "Clases de UCS cada 25 MPa (todos los bloques caen en la banda ISRM R5, 100–250 MPa). " + PIE_CFG, y=-0.05); guardar(fig, "F6_12_clasificacion_DI_UCS.png")

# ── Tabla 6.3 dominios y 6.4 ranking ────────────────────────────────────────
Dm = R["dominios"]
tot = sum(g["count"] for g in Dm["grupos"])
tabla_png("T6_03_dominios", "Agrupación de dominios geomecánicos (los de mayor muestra)",
          ["Grupo", "Litología", "Estructura", "UCS ML media [MPa]", "DI medio", "Registros MWD"],
          [[g["id"], g.get("lito") or "—", g.get("estructura") or "—", dec(g.get("ucsMean"), 1), dec(g.get("diMean"), 3), mil(g["count"])]
           for g in Dm["grupos"][:10]], anchos=[0.1, 0.18, 0.14, 0.22, 0.14, 0.22], ancho_fig=10,
          nota=(f"{Dm['n_grupos']} grupos. Tramos de {dec(Dm['tramo_m'], 0)} m; misma litología y estructura, "
                f"UCS ML ± {dec(Dm['tol_ucs'], 0)} MPa y DI ± {dec(Dm['tol_di'], 1)}."))
RK = R["ranking"]; CRIT = {"min_se_cv": "Mín. variación de PEP", "min_se": "Mínima PEP", "max_rop": "Máxima ROP"}
filas = []
for k, lst in RK["criterios"].items():
    for i, c in enumerate(lst[:5], 1):
        filas.append([CRIT[k], str(i), dec(c["pp"], 0), dec(c["pr"], 0), dec(c["pa"], 0), dec(c["pd"], 0), dec(c["pf"], 0),
                      dec(c["vel"], 2), dec(c["se"], 0), dec(c["se_cv"], 3), c["well"], dec(c["largo"], 1)])
tabla_png("T6_04_ranking_recomendaciones", f"Ranking de 5 recomendaciones históricas — dominio {RK['grupo']}",
          ["Criterio", "N°", "PP [bar]", "RP [bar]", "AP [bar]", "DP [bar]", "FP [bar]", "ROP [m/min]", "PEP", "CV PEP", "Pozo", "Prof. [m]"],
          filas, nota="Segmentos continuos de ≥ 5 registros entrenables del mismo dominio, DI ≤ 1, en pozos de ≥ 20 m. PEP en bar·min/m.",
          anchos=[0.15, 0.035, 0.06, 0.06, 0.06, 0.06, 0.06, 0.075, 0.055, 0.065, 0.21, 0.07], fs=8, ancho_fig=15)

# ── 6.13 PEP vs UCS lab, ROP y PP ───────────────────────────────────────────
E = R["pep_estratos"]
fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.5, 5.2))
for lito in sorted({e["lito"] for e in E}, key=lambda l: next(e["ucs_lab"] for e in E if e["lito"] == l)):
    ee = [e for e in E if e["lito"] == lito]; c = COL_LITO.get(lito, GRIS)
    nm = f"{NOM_LITO.get(lito, lito)} — {dec(ee[0]['ucs_lab'], 1)} MPa"
    a1.plot([e["pp_bin"] + 5 for e in ee], [e["pep_mediana"] for e in ee], "o-", color=c, ms=4, label=nm)
    a2.plot([e["pp_bin"] + 5 for e in ee], [e["rop_mediana"] for e in ee], "o-", color=c, ms=4, label=nm)
a1.set_xlabel("PP [bar] (estratos de 10 bar)"); a1.set_ylabel("PEP mediana [bar·min/m]"); a1.grid(alpha=0.3); a1.legend(fontsize=8)
a2.set_xlabel("PP [bar] (estratos de 10 bar)"); a2.set_ylabel("ROP mediana [m/min]"); a2.grid(alpha=0.3)
fig.suptitle("PEP y ROP según la UCS de laboratorio y la presión de percusión")
pie(fig, "Registros entrenables de roca intacta, ROP ≥ 0,2 m/min; estratos con ≥ 20 registros. " + PIE_CFG, y=-0.04); guardar(fig, "F6_13_PEP_UCS_ROP_PP_continua.png") if not os.path.exists(os.path.join(os.path.dirname(SRC), "pep_estratos_clases.json")) else plt.close(fig)

# ── 6.13b PEP por registro: UCS referencial, ROP y PP (pep_muestra.py) ─────
FM = os.path.join(os.path.dirname(SRC), "pep_muestra.json")
if os.path.exists(FM):
    S = json.load(open(FM, encoding="utf-8")); rho = S["spearman_pep"]
    pep = np.array(S["pep"]); ur = np.array(S["ucs_ref"]); rop = np.array(S["rop"]); ppm = np.array(S["pp"])
    lit = np.array(S["lito"])
    fig, axs = plt.subplots(1, 3, figsize=(16, 5.2), sharey=True)
    jit = np.random.default_rng(42).uniform(-2.5, 2.5, ur.size)
    for lito in sorted(set(lit), key=lambda l: S["anclas"][l]):
        m = lit == lito
        axs[0].scatter(ur[m] + jit[m], pep[m], s=2, alpha=0.2, color=COL_LITO.get(lito, GRIS), rasterized=True,
                       label=f"{NOM_LITO.get(lito, lito)} — {dec(S['anclas'][lito], 1)} MPa")
        axs[0].plot(S["anclas"][lito], np.median(pep[m]), "_", color="#1a1a1a", ms=26, mew=2.2, zorder=6)
    axs[0].set_xlabel("UCS referencial [MPa]"); axs[0].set_ylabel("PEP [bar·min/m]")
    lg = axs[0].legend(fontsize=7.8, markerscale=5, loc="upper right")
    for hnd in lg.legend_handles: hnd.set_alpha(1)
    axs[0].set_title(f"PEP vs. UCS referencial (— mediana) · ρ = {dec(rho['ucs_ref'], 3)}", fontsize=10.5)
    for ax, x_, et, k in ((axs[1], rop, "ROP [m/min]", "rop"), (axs[2], ppm, "PP [bar]", "pp")):
        sc_ = ax.scatter(x_, pep, c=ppm, s=2, alpha=0.35, cmap="viridis", vmin=90, vmax=230, rasterized=True)
        ax.set_xlabel(et); ax.set_title(f"PEP vs. {et.split(' ')[0]} (color = PP) · ρ = {dec(rho[k], 3)}", fontsize=10.5)
    fig.colorbar(sc_, ax=list(axs[1:]), shrink=0.85, label="PP [bar]")
    axs[0].set_ylim(0, S["pep_max"])
    fig.suptitle(f"PEP = (PP + RP + AP) / ROP — {mil(len(pep))} de {mil(S['n'])} registros entrenables de roca intacta "
                 f"(PEP ≤ {mil(S['pep_max'])})")
    guardar(fig, "F6_13b_PEP_UCS_ROP_PP_registros.png")

# ── ajuste UCS referencial ~ PEP agrupado por litología y caserón (pep_ajustes.py)
FA = os.path.join(os.path.dirname(SRC), "pep_ajustes.json")
if os.path.exists(FA):
    PA = json.load(open(FA, encoding="utf-8")); G = PA["conjuntos"]["todo"]["litologia_caseron"]
    aj = G["ajustes"]["parabolico"]; c2, c1, c0 = aj["coef"]
    fig, ax = plt.subplots(figsize=(10, 6))
    M = PA["conjuntos"]["todo"]["muestra"]
    ax.scatter(M["pep"], M["ucs_ref"] + np.random.default_rng(42).uniform(-2, 2, len(M["pep"])), s=2, color=GRIS,
               alpha=0.08, rasterized=True, label="Registros (muestra de 30.000)")
    for j, p in enumerate(sorted(G["puntos"], key=lambda q: (q["ucs_ref"], q["pep_mediana"]))):
        lito, cas = p["grupo"].split(" · ")
        ax.plot(p["pep_mediana"], p["ucs_ref"], "o", ms=9, color=COL_LITO.get(lito, GRIS), mec="white", mew=1, zorder=5)
        ax.annotate(cas, (p["pep_mediana"], p["ucs_ref"]), xytext=(4, 7 if j % 2 == 0 else -15), textcoords="offset points", fontsize=8.5)
    xx = np.linspace(min(p["pep_mediana"] for p in G["puntos"]) - 20, max(p["pep_mediana"] for p in G["puntos"]) + 20, 200)
    ax.plot(xx, c2 * xx ** 2 + c1 * xx + c0, "-", color="#1a1a1a", lw=1.8,
            label=f"UCS = {dec(c2, 5)}·PEP² + {dec(c1, 3)}·PEP {'−' if c0 < 0 else '+'} {dec(abs(c0), 1)}   (R² = {dec(aj['r2'], 3)})")
    hs, ls_ = ax.get_legend_handles_labels()
    hs += [plt.Line2D([], [], ls="", marker="o", ms=8, color=COL_LITO[l]) for l in ("Kpcls", "Brecha_mixta", "Bht", "Kpcli")]
    ls_ += [f"{NOM_LITO[l]} — {dec(PA['anclas'][l], 1)} MPa" for l in ("Kpcls", "Brecha_mixta", "Bht", "Kpcli")]
    lg = ax.legend(hs, ls_, fontsize=8.5, loc="lower right", frameon=True, framealpha=0.9)
    for hnd in lg.legend_handles: hnd.set_alpha(1)
    ax.set_xlim(200, 600); ax.set_ylim(40, 200)
    ax.set_xlabel("PEP mediana del grupo [bar·min/m]"); ax.set_ylabel("UCS referencial [MPa]"); ax.grid(True, axis="both")
    fig.suptitle(f"Ajuste parabólico UCS–PEP por litología y caserón (ρ = {('+' if G['spearman'] >= 0 else '') + dec(G['spearman'], 3)}, n = {G['n_puntos']} grupos)")
    guardar(fig, "F6_13c_ajuste_PEP_UCS_litologia_caseron.png")

# ── PEP, ROP y UCS modelada por intervalo de PP: continua vs fracturada ─────
FE = os.path.join(os.path.dirname(SRC), "pep_estratos_clases.json")
if os.path.exists(FE):
    EC = json.load(open(FE, encoding="utf-8")); FL_ = EC["filas"]
    LITS = sorted(EC["anclas"], key=lambda l: EC["anclas"][l])
    ETC = {"continua": f"Roca continua (DI ≤ {dec(UMB, 0)})", "fracturada": f"Roca fracturada (DI > {dec(UMB, 0)})"}

    NMAX = max(f["n"] for f in FL_)

    def _panel(ax, clase, campo, et, pp_min, con_n):
        for lito in LITS:
            ee = sorted([f for f in FL_ if f["clase"] == clase and f["lito"] == lito and f["pp_bin"] >= pp_min],
                        key=lambda f: f["pp_bin"])
            if not ee: continue
            c = COL_LITO.get(lito, GRIS); x_ = [f["pp_bin"] + 5 for f in ee]; y_ = [f[campo] for f in ee]
            ax.plot(x_, y_, "-", color=c, lw=1.4, label=f"{NOM_LITO.get(lito, lito)} — {dec(EC['anclas'][lito], 1)} MPa")
            # Representatividad: el área del punto crece con log10 de los registros del intervalo.
            ax.scatter(x_, y_, s=[(8 * np.log10(f["n"]) ** 2) if con_n else 18 for f in ee], color=c,
                       edgecolor="white", lw=0.6, alpha=0.9, zorder=4)
        ax.set_ylabel(et); ax.set_title(ETC[clase], fontsize=10.5)

    for nombre, pp_min, con_n, sub in (("F6_13_PEP_UCS_ROP_PP.png", 90, True, "tamaño del punto = registros del intervalo"),
                                       ("F6_13_PEP_UCS_ROP_PP_desde120.png", 120, False, "intervalos desde 120 bar")):
        fig, axs = plt.subplots(2, 2, figsize=(13.5, 9.5), sharex=True)
        for i, clase in enumerate(("continua", "fracturada")):
            _panel(axs[i][0], clase, "pep_mediana", "PEP mediana [bar·min/m]", pp_min, con_n)
            _panel(axs[i][1], clase, "rop_mediana", "ROP mediana [m/min]", pp_min, con_n)
        for k, campo in ((0, "pep_mediana"), (1, "rop_mediana")):
            v_ = [f[campo] for f in FL_ if f["pp_bin"] >= pp_min]; pad = 0.05 * (max(v_) - min(v_))
            for i in (0, 1): axs[i][k].set_ylim(min(v_) - pad, max(v_) + pad)
            axs[1][k].set_xlabel("PP [bar] (intervalos de 10 bar)")
        h_, l_ = axs[0][0].get_legend_handles_labels()
        if con_n:
            for nn in (100, 1000, 10000, 100000):
                h_.append(plt.scatter([], [], s=8 * np.log10(nn) ** 2, color="#A5A5A5", edgecolor="white"))
                l_.append(f"{mil(nn)} registros")
        fig.legend(h_, l_, fontsize=9.5, ncol=4 if not con_n else 4, loc="outside lower center")
        fig.suptitle(f"PEP y ROP según la UCS de laboratorio y la presión de percusión ({sub})")
        guardar(fig, nombre)

    fig, axs = plt.subplots(1, 2, figsize=(13.5, 5.4), sharey=True)
    for ax, clase in zip(axs, ("continua", "fracturada")):
        for lito in LITS:
            ee = sorted([f for f in FL_ if f["clase"] == clase and f["lito"] == lito], key=lambda f: f["pp_bin"])
            if not ee: continue
            r_ = EC["rho_pp_ucs"].get(clase, {}).get(lito, {}).get("rho")
            ax.plot([f["pp_bin"] + 5 for f in ee], [f["ucs_ml_mediana"] for f in ee], "o-", color=COL_LITO.get(lito, GRIS), ms=4,
                    label=f"{NOM_LITO.get(lito, lito)} (ρ = {('+' if r_ >= 0 else '') + dec(r_, 2)})")
            ax.axhline(EC["anclas"][lito], color=COL_LITO.get(lito, GRIS), ls=":", lw=1)
        ax.set_title(ETC[clase] + (" — extrapolación" if clase == "fracturada" else ""), fontsize=10.5)
        ax.set_xlabel("PP [bar] (intervalos de 10 bar)"); ax.legend(fontsize=8.5, loc="lower right")
    axs[0].set_ylabel("UCS modelada (mediana) [MPa]")
    fig.suptitle("UCS modelada por el Random Forest según la presión de percusión (punteado: UCS referencial)")
    guardar(fig, "F6_13e_UCS_modelada_vs_PP.png")

# ── ROP frente a las cuatro presiones (rop_presiones.py) ──────────────────
FRP = os.path.join(os.path.dirname(SRC), "rop_presiones.json")
if os.path.exists(FRP):
    RPJ = json.load(open(FRP, encoding="utf-8")); G0 = RPJ["grupos"]["Todas las litologías"]; PS = list(G0["presiones"])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(15, 5.4), gridspec_kw={"width_ratios": [1.2, 1]})
    MED = [("rho_simple", "ρ simple", "#9DB6CF"), ("rho_parcial", "ρ parcial (descontando las otras 3)", AZUL),
           ("rho_intra_pozo", "ρ dentro de cada pozo", "#1F3864")]
    xx = np.arange(len(PS)); wd = 0.26
    for k, (cl, et, c) in enumerate(MED):
        v = [G0["presiones"][p][cl] for p in PS]
        bb = a1.bar(xx + (k - 1) * wd, v, wd, color=c, label=et)
        for b_, x in zip(bb, v):
            a1.annotate(("+" if x >= 0 else "") + dec(x, 2), (b_.get_x() + b_.get_width() / 2, x),
                        xytext=(0, 3 if x >= 0 else -11), textcoords="offset points", ha="center", fontsize=8)
    a1.axhline(0, color="#333", lw=0.8); a1.set_xticks(xx); a1.set_xticklabels(PS)
    a1.set_ylabel("ρ de Spearman con la ROP"); a1.set_ylim(-0.3, 0.45); a1.legend(fontsize=8.5, loc="upper right")
    a1.set_title(f"Todas las litologías — {mil(G0['n'])} registros, {G0['n_pozos']} pozos · R² (4 presiones) = {dec(G0['r2_rangos_las_4'], 3)}", fontsize=10)
    LG = [g for g in RPJ["grupos"] if g != "Todas las litologías"]
    M = np.array([[RPJ["grupos"][g]["presiones"][p]["rho_intra_pozo"] for p in PS] for g in LG])
    im = a2.imshow(M, cmap="RdBu_r", vmin=-0.4, vmax=0.4, aspect="auto")
    a2.set_xticks(range(len(PS))); a2.set_xticklabels(PS)
    a2.set_yticks(range(len(LG))); a2.set_yticklabels([f"{NOM_LITO.get(g, g)}\nR² = {dec(RPJ['grupos'][g]['r2_rangos_las_4'], 3)}" for g in LG], fontsize=9)
    for i in range(len(LG)):
        for j in range(len(PS)):
            a2.text(j, i, ("+" if M[i, j] >= 0 else "") + dec(M[i, j], 2), ha="center", va="center", fontsize=9,
                    color="white" if abs(M[i, j]) > 0.25 else "#222")
    fig.colorbar(im, ax=a2, shrink=0.85, label="ρ dentro de cada pozo")
    a2.set_title("ρ dentro de cada pozo, por litología", fontsize=10)
    fig.suptitle("Relación de la ROP con las presiones de percusión, avance, rotación y dámper (roca continua)")
    guardar(fig, "F6_14_ROP_vs_presiones.png")

json.dump(hechas, open(f"{OUT}/_hechas.json", "w"))
print(len(hechas), "archivos")
