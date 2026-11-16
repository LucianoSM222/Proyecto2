"""Figura: periodicidad de la percusión de empate (distancia entre caídas del mismo pozo)."""
import sys, json
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
D = sys.argv[1]; OUT = sys.argv[2]
M = json.load(open(f"{D}/marcas.json")); P = json.load(open(f"{D}/periodo.json")); L = P["L"]
plt.rcParams.update({"font.family": "Carlito", "font.size": 11, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.edgecolor": "#BFBFBF", "axes.grid": True,
                     "axes.grid.axis": "y", "grid.color": "#D9D9D9", "legend.frameon": False,
                     "xtick.color": "#595959", "ytick.color": "#595959", "axes.labelcolor": "#404040"})
d = []
for x in M["0.25"].values():
    x = np.array(x)
    if x.size < 2: continue
    dd = x[None, :] - x[:, None]; d.extend(dd[(dd > 0.05) & (dd < 6)].tolist())
fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5), gridspec_kw={"width_ratios": [1.6, 1]})
a1.hist(d, bins=np.arange(0.05, 6.0, 0.02), color="#4472C4")
for k in (1, 2, 3):
    a1.axvline(k * L, color="#C00000", ls="--", lw=1)
    a1.text(k * L, a1.get_ylim()[1] * 0.97, f"{k}×{L:.3f} m".replace(".", ","), color="#C00000", ha="center", va="top", fontsize=9,
            bbox=dict(facecolor="white", edgecolor="none", pad=1))
a1.set_xlabel("Distancia entre dos caídas del mismo pozo [m]"); a1.set_ylabel("N° de pares"); a1.grid(alpha=0.3)
a1.set_title("Pares de caídas (umbral 0,25)", fontsize=10.5)
Ls = np.array(P["barrido"]["L"]); c = np.array(P["barrido"]["0.25"])
a2.plot(Ls, c, color="#4472C4"); a2.axhline(P["azar"]["0.25"] if "azar" in P else 0.202, color="#888", ls=":", lw=1.8, label="azar")
k = int(np.argmax(c)); a2.axvline(L, color="#C00000", ls="--", lw=1, label=f"largo de barra {L:.3f} m".replace(".", ","))
a2.annotate(f"máximo en {Ls[k]:.3f} m".replace(".", ","), (Ls[k], c[k]), xytext=(15, -5), textcoords="offset points", fontsize=9)
a2.set_xlabel("Período de prueba [m]"); a2.set_ylabel("Coherencia de fase (0-1)"); a2.grid(alpha=0.3); a2.legend(fontsize=8.5)
a2.set_title("Qué período ordena mejor las caídas", fontsize=10.5)
from matplotlib.ticker import FuncFormatter
for ax_ in (a1, a2):
    ax_.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}".replace(".", ",")))
a2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.2f}".replace(".", ",")))
fig.suptitle("La percusión de empate se repite con el largo de barra", fontsize=14, color="#404040")
fig.tight_layout()
fig.savefig(OUT, dpi=300, bbox_inches="tight", facecolor="white"); print("OK")
