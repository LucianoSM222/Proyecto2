"""Filtro de continuidad con el DI POR TRAMOS (prueba de 2026-11-15): el salto
no excluye registros, solo corta la serie en tramos continuos.
Uso: python3 fig_continuidad_tramos.py filtros_separados.json BARRENO carpeta"""
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
AZUL, ROJO, VERDE, VERDE2 = "#4472C4", "#C00000", "#70AD47", "#38761D"
coma = FuncFormatter(lambda v, _: (f"{v:.6f}".rstrip("0").rstrip(".") or "0").replace(".", ","))
SRC, WN, OUT = sys.argv[1:4]
L = np.array(json.load(open(SRC))["barrenos"][WN]["largo"])
d = np.r_[np.nan, np.diff(L)] * 100; salto = d > 2.95
seg = np.cumsum(salto)                     # tramo continuo de cada registro
fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 6.2), sharex=True, sharey=True)
a1.plot(L, d, "-", color=AZUL, lw=0.8, label="Registro")
a1.plot(L[salto], d[salto], "o", color=ROJO, ms=4.5, mec="white", mew=0.4, zorder=5, label=f"Salto > 2,95 cm ({int(salto.sum())})")
a1.set_title("(a) Antes del filtro", loc="left", fontsize=11, color="#404040")
for k in np.unique(seg):
    m = seg == k; y = d.copy(); y[~m] = np.nan; y[salto & m] = np.nan   # la separación del salto no es de ningún tramo
    a2.plot(L, y, "-", color=(VERDE, VERDE2)[k % 2], lw=0.8,
            label=f"Tramos continuos ({int(seg.max()) + 1}), sin registros excluidos" if k == 0 else None)
a2.set_title("(b) Después del filtro: la serie se corta en cada salto y el DI se calcula dentro de cada tramo",
             loc="left", fontsize=11, color="#404040")
for a in (a1, a2):
    a.axhline(2.95, color=ROJO, ls="--", lw=1, label="Umbral 2,95 cm")
    for x in L[salto]: a.axvline(x, color=ROJO, ls=":", lw=0.8, alpha=0.6)
    a.set_ylabel("Separación entre registros [cm]"); a.xaxis.set_major_formatter(coma); a.yaxis.set_major_formatter(coma)
    a.legend(loc="upper right", fontsize=9.5, ncol=3)
a1.plot([], [], color=ROJO, ls=":", lw=0.8, label="Corte de tramo"); a1.legend(loc="upper right", fontsize=9.5, ncol=2)
a1.set_ylim(0, max(5, np.nanmax(d) * 1.1)); a2.set_xlabel("Profundidad a lo largo del barreno [m]")
p = os.path.join(OUT, f"Filtro4_continuidad_por_tramos_{WN}.png"); fig.savefig(p, dpi=300, facecolor="white"); print("OK", p)
