"""Una figura por filtro, en un barreno: la variable que mejor muestra que lo
excluido es intervención del equipo, antes (registros marcados) y después.
Uso: python3 fig_filtros_separados.py filtros_separados.json BARRENO carpeta_salida"""
import sys, json, os
import numpy as np, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
plt.rcParams.update({
    "font.family": "Carlito", "font.size": 11, "text.color": "#262626", "axes.labelcolor": "#404040",
    "axes.edgecolor": "#BFBFBF", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "axes.axisbelow": True, "grid.color": "#D9D9D9", "grid.linewidth": 0.8,
    "xtick.color": "#595959", "ytick.color": "#595959", "legend.frameon": False,
    "figure.constrained_layout.use": True, "savefig.pad_inches": 0.04})
AZUL, ROJO, VERDE, NARANJA, GRIS, MORADO = "#4472C4", "#C00000", "#70AD47", "#ED7D31", "#A5A5A5", "#7030A0"
coma = FuncFormatter(lambda v, _: (f"{v:.6f}".rstrip("0").rstrip(".") or "0").replace(".", ","))
dec = lambda x, n: f"{x:.{n}f}".replace(".", ",")
SRC, WN, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True)
J = json.load(open(SRC)); E = J["barrenos"][WN]; LIM = J["limites"]
L = np.array(E["largo"]); V = {k: np.array(E[k], float) for k in ("PR", "PP", "FP", "DP", "RP", "FLP")}
ETQ = {"PR": "PR [m/min]", "PP": "PP [bar]", "FP": "FP [bar]", "RP": "RP [bar]", "DP": "DP [bar]", "FLP": "FLP [bar]"}

def figura(nombre, var, grupos, xlim=None, ylim=None, lineas=(), yv=None, etq=None, despues=None):
    """grupos: [(máscara, rótulo, color)]. Panel (a) antes con lo marcado; (b) después sin ello."""
    y = V[var] if yv is None else yv; et = ETQ.get(var, var) if etq is None else etq
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 6.2), sharex=True, sharey=True)
    a1.plot(L, y, "-", color=AZUL, lw=0.8, label="Registro")
    fuera = np.zeros(L.size, bool)
    for m, r, c in grupos:
        m = np.asarray(m, bool); fuera |= m
        if m.any(): a1.plot(L[m], y[m], "o", color=c, ms=4.5, mec="white", mew=0.4, zorder=5, label=f"{r} ({int(m.sum())})")
    for v_, r, c in lineas:
        for a in (a1, a2): a.axhline(v_, color=c, ls="--", lw=1)
        a1.plot([], [], color=c, ls="--", lw=1, label=r)
    ys = y.copy(); ys[fuera if despues is None else despues] = np.nan
    a2.plot(L, ys, "-", color=VERDE, lw=0.8, label="Después del filtro")
    a1.set_title("(a) Antes del filtro", loc="left", fontsize=11, color="#404040")
    a2.set_title("(b) Después del filtro", loc="left", fontsize=11, color="#404040")
    for a in (a1, a2):
        a.set_ylabel(et); a.xaxis.set_major_formatter(coma); a.yaxis.set_major_formatter(coma)
        if xlim: a.set_xlim(*xlim)
        if ylim: a.set_ylim(*ylim)
    a1.legend(loc="best", fontsize=9.5, ncol=2); a2.legend(loc="lower right", fontsize=9.5)
    a2.set_xlabel("Profundidad a lo largo del barreno [m]")
    p = os.path.join(OUT, f"{nombre}_{WN}.png"); fig.savefig(p, dpi=300, facecolor="white"); plt.close(fig); print("OK", p)

b, mg = np.array(E["barra"]), np.array(E["margen"])
prmax = np.nanpercentile(V["PR"][V["PR"] > 0], 99.5) * 1.15
# 1. Cambio de barra: PR (la detención es PR = 0, y al reanudar la PR viene baja)
figura("Filtro1_cambio_de_barra_PR", "PR", [(b, "Detención en la unión (PR = 0)", ROJO), (mg, "2 registros tras la detención", NARANJA)],
       ylim=(-0.05, prmax))
# 2. Emboquillado: PP (la percusión reducida la fija el operador)
emb = np.array(E["emboquillado"]); corte = E["corte"][0]
figura("Filtro2_emboquillado_PP", "PP", [(emb, f"Emboquillado (hasta {dec(corte, 2)} m)", GRIS)],
       xlim=(0, min(L[-1], corte + 6)), lineas=[(LIM["PP"][1], "PP mínima del equipo (90 bar)", MORADO)])
# 3a. Límites del equipo: registros sin perforar; PR y PP muestran que el equipo no avanza ni percute
eq = E["equipo"]
pr0 = np.array(["PR = 0" in c or "PR > 10" in c for c in eq]); ppb = np.array(["PP < mín" in c for c in eq])
fpb = np.array(["FP < mín" in c for c in eq]); flp = np.array(["FLP > máx" in c for c in eq])
otros = fpb | flp
figura("Filtro3a_equipo_sin_perforar_PP", "PP",
       [(ppb, "PP bajo 90 bar", MORADO), (pr0 & ~ppb, "PR = 0 (sin avance)", ROJO)] + ([(otros & ~ppb & ~pr0, "FP < 20 o FLP > 10 bar", NARANJA)] if otros.any() else []),
       lineas=[(LIM["PP"][1], "PP mínima del equipo (90 bar)", MORADO)])
# 3b. Límites de roca: se quedan en el DI, salen solo del entrenamiento
roca = E["roca"]; var_r = max(("PR", "RP", "DP"), key=lambda k: sum(k in c for c in roca))
mr = np.array([var_r in c for c in roca])
lo, hi = LIM[var_r][1], LIM[var_r][2]
figura(f"Filtro3b_limites_roca_{var_r}", var_r, [(mr, f"{var_r} fuera de {dec(lo, 1)}–{dec(hi, 1)} (solo entrenamiento)", VERDE)],
       ylim=(-0.05, max(prmax, np.nanmax(V[var_r][mr]) * 1.05 if mr.any() else prmax)) if var_r == "PR" else None,
       lineas=[(lo, f"Límites sanos de {var_r}", GRIS), (hi, "_", GRIS)])
# 4. Continuidad: separación entre registros consecutivos
d = np.r_[np.nan, np.diff(L)] * 100
V["dL"] = d
co = np.array(E["continuidad"]); salto = d > 2.95
figura("Filtro4_continuidad_separacion", "dL", [(salto, "Salto > 2,95 cm", ROJO), (co & ~salto, "Ventana del DI que cruza el salto", NARANJA)],
       etq="Separación entre registros [cm]", lineas=[(2.95, "Umbral 2,95 cm", ROJO)],
       ylim=(0, max(5, np.nanmax(d) * 1.1)))
