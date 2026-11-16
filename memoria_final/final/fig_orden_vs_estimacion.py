"""Indicadores de ORDENAMIENTO (ρ de Spearman) frente a indicadores de
ESTIMACIÓN (R² y RMSE) para los tres esquemas de validación.
Uso: python3 fig_orden_vs_estimacion.py final.json loocv_litologia.json salida.png"""
import sys, json
import numpy as np, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
plt.rcParams.update({"font.family": "Carlito", "font.size": 12, "axes.labelcolor": "#404040", "axes.edgecolor": "#BFBFBF",
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y", "axes.axisbelow": True,
    "grid.color": "#E6E6E6", "xtick.color": "#404040", "ytick.color": "#595959", "figure.constrained_layout.use": True})
R = json.load(open(sys.argv[1], encoding="utf-8")); LL = json.load(open(sys.argv[2], encoding="utf-8"))
gk, lc = R["groupkfold"], R["loocv_caseron"]
pl = [p for p in LL["pliegues"] if p["ucs_predicho"] is not None]
y = np.array([p["ucs_real"] for p in pl]); yh = np.array([p["ucs_predicho"] for p in pl])
r2_lito = 1 - ((y - yh) ** 2).sum() / ((y - y.mean()) ** 2).sum(); rmse_lito = float(np.sqrt(((y - yh) ** 2).mean()))
sp_lc = float(np.mean([f["spearman"] for f in lc["pliegues"] if f["spearman"] is not None]))
E = [("GroupKFold\npor barreno", gk["spearman_medio"], gk["r2_medio"], gk["rmse_medio"], "#4472C4"),
     ("LOOCV-Caserón", sp_lc, lc["r2_medio_definidos"], lc["rmse_medio"], "#7030A0"),
     ("LOOCV-Litología", LL["spearman"], r2_lito, rmse_lito, "#ED7D31")]
dec = lambda v, n=3, s=True: ((("+" if v >= 0 else "") if s else "") + f"{v:.{n}f}").replace(".", ",")
fig, axs = plt.subplots(1, 3, figsize=(16, 5.6))
x = np.arange(3); cols = [e[4] for e in E]
for ax, k, lab, n, s in ((axs[0], 1, "ρ de Spearman (UCS estimada vs. UCS de ensayo)", 3, True), (axs[1], 2, "R²", 3, True), (axs[2], 3, "RMSE [MPa]", 1, False)):
    v = [e[k] for e in E]; ax.bar(x, v, color=cols, width=0.55); ax.axhline(0, color="#7F7F7F", lw=0.9)
    rng = max(v) - min(min(v), 0)
    for i, vi in enumerate(v):
        ax.text(i, vi + (0.02 if vi >= 0 else -0.02) * rng, dec(vi, n, s), ha="center", va="bottom" if vi >= 0 else "top", fontsize=11)
    ax.set_xticks(x, [e[0] for e in E], fontsize=10.5); ax.set_ylabel(lab)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda t, _p=None: (f"{t:.6f}".rstrip("0").rstrip(".") or "0").replace(".", ",")))
axs[0].set_ylim(-0.6, 1); axs[1].set_ylim(min(-3.2, min(e[2] for e in E) - 0.4), 1)
axs[0].set_title("(a) Ordenamiento", loc="left", fontsize=12, color="#262626")
axs[1].set_title("(b) Estimación: varianza explicada", loc="left", fontsize=12, color="#262626")
axs[2].set_title("(c) Estimación: error", loc="left", fontsize=12, color="#262626")
fig.savefig(sys.argv[3], dpi=300, facecolor="white"); print("OK", [(e[0], round(e[1], 3), round(e[2], 3), round(e[3], 1)) for e in E])
