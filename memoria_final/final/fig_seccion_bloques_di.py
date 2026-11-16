"""Sección vertical del modelo de bloques de PCC_0042 (Figura 5.15) con el DI
en dos clases de color: azules para roca continua (DI ≤ 1) y naranjo a rojo
para discontinua (DI > 1), con corte nítido en 1. La UCS queda igual.
Uso: python3 fig_seccion_bloques_di.py final.json salida.png"""
import sys, json
import numpy as np, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, TwoSlopeNorm
from matplotlib.ticker import FuncFormatter
plt.rcParams.update({"font.family": "Carlito", "font.size": 11, "axes.labelcolor": "#404040", "axes.edgecolor": "#BFBFBF",
                     "axes.spines.top": False, "axes.spines.right": False, "xtick.color": "#595959", "ytick.color": "#595959",
                     "figure.constrained_layout.use": True})
R = json.load(open(sys.argv[1], encoding="utf-8")); B = R["bloques"]; s_ = B["seccion"]; lado = B["bloque_m"]
x = np.array(s_["x"]); z = np.array(s_["z"])
cmap_di = ListedColormap(np.vstack([plt.cm.Blues(np.linspace(0.95, 0.45, 128)), plt.cm.YlOrRd(np.linspace(0.45, 1.0, 128))]))
coma = FuncFormatter(lambda v, _p=None: (f"{v:.6f}".rstrip("0").rstrip(".") or "0").replace(".", ","))
fig, axs = plt.subplots(1, 2, figsize=(14, 5.6), sharey=True)
for ax, var, cmap, norm, lab, tit in ((axs[0], "di", cmap_di, TwoSlopeNorm(vmin=0, vcenter=1, vmax=2.5), "DI  (≤ 1 roca continua · > 1 roca discontinua)", "Índice de discontinuidad"),
                                      (axs[1], "ucs", "viridis", plt.Normalize(50, 250), "UCS [MPa]", "UCS de matriz estimada")):
    vv = np.array([np.nan if v is None else v for v in s_[var]], float)
    ix_ = np.round((x - x.min()) / lado).astype(int); iz_ = np.round((z - z.min()) / lado).astype(int)
    G = np.full((iz_.max() + 1, ix_.max() + 1), np.nan); G[iz_, ix_] = vv
    sc = ax.pcolormesh(x.min() - lado / 2 + lado * np.arange(ix_.max() + 2), z.min() - lado / 2 + lado * np.arange(iz_.max() + 2),
                       np.ma.masked_invalid(G), cmap=cmap, norm=norm, edgecolors="white", linewidth=0.15)
    ax.set_aspect("equal"); ax.set_xlabel("Este [m]"); ax.set_title(tit, fontsize=11, color="#404040")
    cb = fig.colorbar(sc, ax=ax, shrink=0.8, label=lab, extend="max" if var == "di" else "neither")
    cb.ax.yaxis.set_major_formatter(coma)
    if var == "di":
        cb.set_ticks([0, 0.5, 1, 1.5, 2, 2.5]); cb.ax.axhline(1.0, color="black", lw=1.2)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p=None: f"{v:.0f}")); ax.yaxis.set_major_formatter(coma)
axs[0].set_ylabel("Cota [m]")
fig.savefig(sys.argv[2], dpi=300, bbox_inches="tight", facecolor="white"); print("OK", sys.argv[2])
