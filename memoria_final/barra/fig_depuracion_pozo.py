"""Figura de depuración (antes / después) de un pozo, con PP o con PR.
Uso: python3 fig_depuracion_pozo.py pozo_ejemplo.json POZO {pp|pr} salida.png"""
import sys, json
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams.update({
    "font.family": "Carlito", "font.size": 11, "text.color": "#262626",
    "axes.titlesize": 12, "axes.titlecolor": "#404040", "axes.labelcolor": "#404040",
    "axes.edgecolor": "#BFBFBF", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "axes.axisbelow": True, "grid.color": "#D9D9D9", "grid.linewidth": 0.8,
    "xtick.color": "#595959", "ytick.color": "#595959", "legend.frameon": False,
    "figure.constrained_layout.use": True, "savefig.pad_inches": 0.04})
from matplotlib.ticker import FuncFormatter
AZUL, ROJO, VERDE, NARANJA, GRIS, MORADO = "#4472C4", "#C00000", "#70AD47", "#ED7D31", "#A5A5A5", "#7030A0"
SRC, WN, VAR, OUT = sys.argv[1:5]
E = json.load(open(SRC, encoding="utf-8"))[WN]
L = np.array(E["largo"]); Y = np.array(E[VAR], float); mot = np.array(E["motivo"], dtype=object)
corte = E["corte_emboquillado"][0]
dec = lambda x, n: f"{x:.{n}f}".replace(".", ",")
mil = lambda n: f"{int(n):,}".replace(",", ".")
ETQ = {"pp": "PP [bar]", "pr": "PR [m/min]"}[VAR]
MOT = [("emboquillado", "Emboquillado (meseta de PP)", GRIS), ("barra", "Cambio de barra (PR = 0)", ROJO),
       ("margen", "Margen tras el cambio de barra", NARANJA), ("equipo", "Equipo sin perforar", MORADO),
       ("continuidad", "Continuidad del registro", "#000000"), ("roca", "Fuera de rango, solo entrenamiento", VERDE)]
fig, (a1, a2) = plt.subplots(2, 1, figsize=(14, 6.8), sharex=True)
a1.plot(L, Y, "-", color=AZUL, lw=0.8)
for k, et, c_ in MOT:
    m = mot == k
    if m.any():
        a1.plot(L[m], Y[m], "o", color=c_, ms=4.2, mec="white", mew=0.4, zorder=5, label=f"{et} ({int(m.sum())})")
a1.axvline(corte, color=GRIS, ls="--", lw=1)
a1.set_ylabel(ETQ); a1.legend(loc="lower right", fontsize=9, ncol=3)
a1.set_title("Antes de la depuración", loc="left", fontsize=10)
serie = (mot == "") | (mot == "roca")
Ys = Y.copy(); Ys[~serie] = np.nan
a2.plot(L, Ys, "-", color=VERDE, lw=0.8, label=f"Serie depurada para el DI ({mil(serie.sum())} registros)")
a2.axvspan(0, corte, color=GRIS, alpha=0.30, lw=0, zorder=0, label=f"Emboquillado (< {dec(corte, 2)} m)")
for x_ in L[mot == "barra"]:
    a2.axvline(x_, color=ROJO, ls=":", lw=0.8, alpha=0.6, zorder=0)
a2.set_ylabel(ETQ); a2.set_xlabel("Profundidad a lo largo del pozo [m]")
a2.set_title("Después de la depuración (líneas punteadas: cambios de barra cada 1,756 m)", loc="left", fontsize=10)
a2.legend(loc="lower right", fontsize=9, ncol=2)
if VAR == "pr":
    hi = np.nanpercentile(Y[Y > 0], 99.5) * 1.15
    for a in (a1, a2): a.set_ylim(-0.05, hi)
c = lambda v, _p=None: (f"{v:.6f}".rstrip("0").rstrip(".") or "0").replace(".", ",")
for a in (a1, a2):
    a.yaxis.set_major_formatter(FuncFormatter(c)); a.xaxis.set_major_formatter(FuncFormatter(c))
fig.savefig(OUT, dpi=300 if "final" in OUT else 110, bbox_inches="tight", facecolor="white"); print("OK", OUT)
