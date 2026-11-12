"""Figura 5.3: perfil del DI calibrado en PCC_0042_PR01_TH_P20_H12, con las
zonas del pozo que alcanzan los tramos de RQD de sondaje dentro del radio de
asignación. Uso: python3 fig_perfil_di.py final.json salida.png"""
import sys, json
from collections import defaultdict
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
R = json.load(open(sys.argv[1], encoding="utf-8")); P = R["pozo_P20_H12"]; DI = R["di_vigente"]
L = np.array(P["largo"]); D = np.array([np.nan if v is None else v for v in P["di"]], float)
U = DI["umbral"]; RAD = 5.0
dec = lambda x, n: f"{x:.{n}f}".replace(".", ",")
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
AZUL, ROJO, VERDE_Z, VERDE_T = "#2F5D8A", "#B03A2E", "#9CC5B0", "#1E5E3C"
fig, ax = plt.subplots(figsize=(11, 5.2))
ax.set_facecolor("#F2F2F2"); ax.grid(True, color="white", lw=1.0); ax.set_axisbelow(True)
for s in ax.spines.values(): s.set_visible(True); s.set_color("#404040"); s.set_linewidth(0.9)
# zonas por sondaje
Z = defaultdict(list)
for t in P["tramos_rqd"]: Z[t["sondaje"]].append(t)
ytop = np.nanmax(D) * 1.42
for k, (son, ts) in enumerate(sorted(Z.items(), key=lambda kv: min(t["largo_pozo_m"] for t in kv[1]))):
    a = min(t["largo_pozo_m"] - t["largo_tramo_m"] / 2 for t in ts); b = max(t["largo_pozo_m"] + t["largo_tramo_m"] / 2 for t in ts)
    ax.axvspan(a, b, color=VERDE_Z, alpha=0.45, lw=0, zorder=0)
    rq = [t["rqd"] for t in ts]; dist = min(t["dist_m"] for t in ts)
    rm = sorted({t["rqd_mwd"] for t in ts if t["rqd_mwd"] is not None})
    txt = (f"Sondaje {son}\n{len(ts)} tramos, a {dec(dist, 1)} m del pozo\n"
           f"RQD sondaje: {dec(min(rq), 0)}–{dec(max(rq), 0)} %\n"
           f"RQD equivalente DI: {dec(min(rm), 0)}–{dec(max(rm), 0)} %")
    xc = (a + b) / 2
    ax.text(xc, ytop * 0.97, txt, ha="right" if xc > L.max() * 0.8 else "center", va="top", fontsize=9,
            color=VERDE_T, linespacing=1.35, zorder=6,
            x=(b if xc > L.max() * 0.8 else xc)) if False else None
    ha = "right" if xc > L.max() * 0.8 else "left"
    ax.text(a - 0.3 if ha == "right" else b + 0.3, ytop * 0.97, txt, ha=ha, va="top", fontsize=9,
            color=VERDE_T, linespacing=1.35, zorder=6)
# Tramo de RQD bajo (< 50 %, «malo» según Deere): su franja propia, sobre la
# zona del sondaje, centrada en el punto del pozo más cercano a ese tramo.
for t in P["tramos_rqd"]:
    if t["rqd"] < 50:
        a_, b_ = t["largo_pozo_m"] - t["largo_tramo_m"] / 2, t["largo_pozo_m"] + t["largo_tramo_m"] / 2
        ax.axvspan(a_, b_, color="#E69F00", alpha=0.45, lw=0, zorder=1)
        ax.text(a_ - 0.25, ytop * 0.60, f"RQD {dec(t['rqd'], 0)} %\ntramo {dec(t['desde'], 0)}–{dec(t['hasta'], 0)} m\ndel sondaje ({dec(t['largo_tramo_m'], 0)} m)",
                ha="right", va="center", fontsize=9, color="#9C5A00", linespacing=1.3, zorder=6)
ax.plot(L, D, "-", color=AZUL, lw=1.1, zorder=3)
ax.fill_between(L, U, D, where=np.isfinite(D) & (D > U), color=ROJO, alpha=0.25, lw=0, zorder=2, interpolate=True)
ax.axhline(U, color=ROJO, ls="--", lw=1.1, zorder=4, label=f"Umbral DI = {dec(U, 0)} (roca discontinua sobre esta línea)")
ax.set_xlabel("Profundidad a lo largo del pozo [m]"); ax.set_ylabel("Índice de discontinuidad (DI)", color=AZUL)
ax.tick_params(axis="y", colors=AZUL); ax.set_ylim(-0.2, ytop); ax.set_xlim(-1.5, max(L.max(), max(t["largo_pozo_m"] + t["largo_tramo_m"] / 2 for t in P["tramos_rqd"])) + 1.5)
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), fontsize=9, frameon=False)
c = lambda v, _p=None: (f"{v:.6f}".rstrip("0").rstrip(".") or "0").replace(".", ",")
ax.xaxis.set_major_formatter(FuncFormatter(c)); ax.yaxis.set_major_formatter(FuncFormatter(c))
fig.tight_layout(); fig.savefig(sys.argv[2], dpi=300, bbox_inches="tight", facecolor="white"); print("OK")
