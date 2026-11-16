"""Emboquillado en un barreno, un solo panel: el registro con los puntos del
emboquillado marcados (sin el 'después'). Una figura con PP y otra con PR.
Uso: python3 fig_emboquillado_solo.py filtros_separados.json BARRENO carpeta"""
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
AZUL, GRIS, MORADO = "#4472C4", "#7F7F7F", "#7030A0"
coma = FuncFormatter(lambda v, _: (f"{v:.6f}".rstrip("0").rstrip(".") or "0").replace(".", ","))
dec = lambda x, n: f"{x:.{n}f}".replace(".", ",")
SRC, WN, OUT = sys.argv[1:4]
J = json.load(open(SRC)); E = J["barrenos"][WN]
L = np.array(E["largo"]); emb = np.array(E["emboquillado"]); corte = E["corte"][0]
for var, etq in (("PP", "PP [bar]"), ("PR", "PR [m/min]")):
    y = np.array(E[var], float)
    fig, ax = plt.subplots(figsize=(12, 3.8))
    ax.plot(L, y, "-", color=AZUL, lw=0.8, label="Registro")
    ax.plot(L[emb], y[emb], "o", color=GRIS, ms=4.5, mec="white", mew=0.4, zorder=5,
            label=f"Emboquillado, hasta {dec(corte, 2)} m ({int(emb.sum())} registros)")
    ax.axvline(corte, color=GRIS, ls="--", lw=1, label="Fin del emboquillado (meseta de PP)")
    if var == "PP":
        ax.axhline(J["limites"]["PP"][1], color=MORADO, ls=":", lw=1, label="PP mínima del equipo (90 bar)")
    else:
        ax.set_ylim(-0.05, np.nanpercentile(y[y > 0], 99.5) * 1.15)
    ax.set_xlim(0, min(L[-1], corte + 6)); ax.set_ylabel(etq); ax.set_xlabel("Profundidad a lo largo del barreno [m]")
    ax.xaxis.set_major_formatter(coma); ax.yaxis.set_major_formatter(coma)
    ax.legend(loc="lower right", fontsize=9.5, ncol=2)
    p = os.path.join(OUT, f"Filtro2_emboquillado_solo_{var}_{WN}.png"); fig.savefig(p, dpi=300, facecolor="white"); plt.close(fig); print("OK", p)
