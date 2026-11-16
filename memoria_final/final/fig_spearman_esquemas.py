"""ρ de Spearman (UCS estimada vs. UCS de ensayo) según qué se deja fuera del
entrenamiento: GroupKFold por barreno, LOOCV-Caserón y LOOCV-Litología.
Uso: python3 fig_spearman_esquemas.py final.json loocv_litologia.json salida.png"""
import sys, json
import numpy as np, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
plt.rcParams.update({"font.family": "Carlito", "font.size": 12, "axes.labelcolor": "#404040", "axes.edgecolor": "#BFBFBF",
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y", "axes.axisbelow": True, "grid.color": "#E6E6E6",
    "xtick.color": "#404040", "ytick.color": "#595959", "figure.constrained_layout.use": True})
R = json.load(open(sys.argv[1], encoding="utf-8")); LL = json.load(open(sys.argv[2], encoding="utf-8"))
lc = R["loocv_caseron"]
vals = [("GroupKFold\npor barreno", R["groupkfold"]["spearman_medio"], "#4472C4"),
        ("LOOCV-Caserón", float(np.mean([f["spearman"] for f in lc["pliegues"] if f["spearman"] is not None])), "#7030A0"),
        ("LOOCV-Litología", LL["spearman"], "#ED7D31")]
coma = lambda v: (("+" if v >= 0 else "") + f"{v:.3f}").replace(".", ",")
fig, ax = plt.subplots(figsize=(9, 5.6))
x = np.arange(len(vals))
ax.bar(x, [v for _, v, _ in vals], color=[c for *_, c in vals], width=0.5)
for i, (_, v, _) in enumerate(vals):
    ax.text(i, v + (0.02 if v >= 0 else -0.02), coma(v), ha="center", va="bottom" if v >= 0 else "top", fontsize=11)
ax.axhline(0, color="#7F7F7F", lw=0.9)
ax.set_xticks(x, [n for n, *_ in vals]); ax.set_ylim(-0.6, 1)
ax.set_ylabel("ρ de Spearman (UCS estimada vs. UCS de ensayo)")
ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p=None: (f"{v:.1f}").replace(".", ",")))
fig.savefig(sys.argv[3], dpi=300, facecolor="white"); print("OK", vals)
