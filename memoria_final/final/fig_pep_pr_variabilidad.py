"""PEP y PR por intervalo de PP de 10 bar, por litología, en roca continua y
discontinua, más la VARIABILIDAD INTERNA de la PEP (CV = desv. est./media) que
es la función objetivo: entre los intervalos con PR mediana 1,0-1,2 m/min se
elige el de menor CV (estrella). La banda en el panel de PEP es el rango
intercuartil del intervalo. Mismos filtros que pep_estratos_clases.py (sin la
UCS modelada). Uso: python3 fig_pep_pr_variabilidad.py proyecto_final.gwz carpeta"""
import sys, os, json
sys.path.insert(0, "/home/user/Proyecto2")
from collections import defaultdict
import numpy as np, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import geomech_wizard as gw, cargar_caserones as cc
GWZ, OUT = sys.argv[1:3]
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
gw.load_project(GWZ)
ANC = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pep_estratos_clases.json")))["anclas"]
MIN_BIN = int(gw.get_param("pp.min_puntos_bin")); UMB = gw.di_threshold; PR_LO, PR_HI = 1.0, 1.2
cel = defaultdict(lambda: {"pep": [], "pr": []})
for p in gw.all_points():
    if not p.entrenable or p.lito not in ANC or p.di is None or p.pp is None: continue
    if p.vel is None or p.vel < gw.ROP_MIN_FISICA or p.se is None or not np.isfinite(p.se): continue
    k = ("discontinua" if p.di > UMB else "continua", p.lito, int(p.pp // 10 * 10))
    cel[k]["pep"].append(p.se); cel[k]["pr"].append(p.vel)
F = []
for (cl, li, b), v in cel.items():
    if len(v["pep"]) < MIN_BIN: continue
    pep = np.array(v["pep"]); pr = np.array(v["pr"])
    F.append({"clase": cl, "lito": li, "pp": b + 5, "n": int(pep.size), "pep": float(np.median(pep)),
              "q1": float(np.percentile(pep, 25)), "q3": float(np.percentile(pep, 75)),
              "cv": float(100 * pep.std() / pep.mean()), "pr": float(np.median(pr))})
json.dump(F, open(os.path.join(OUT, "pep_pr_variabilidad.json"), "w"), ensure_ascii=False, indent=1)
plt.rcParams.update({"font.family": "Carlito", "font.size": 11, "text.color": "#262626", "axes.labelcolor": "#404040",
    "axes.edgecolor": "#BFBFBF", "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "axes.grid.axis": "y", "grid.color": "#D9D9D9", "xtick.color": "#595959", "ytick.color": "#595959",
    "legend.frameon": False, "figure.constrained_layout.use": True})
COL = {"Kpcls": "#C00000", "Brecha_mixta": "#ED7D31", "Bht": "#4472C4", "Kpcli": "#70AD47"}
NOM = {"Kpcls": "Lavas superiores (Kpcls)", "Brecha_mixta": "Brecha mixta", "Bht": "Brecha hidrotermal (Bht)", "Kpcli": "Lavas inferiores (Kpcli)"}
dec = lambda x, n=1: f"{x:.{n}f}".replace(".", ","); mil = lambda n: f"{int(n):,}".replace(",", ".")
c_ = FuncFormatter(lambda v, _p=None: (f"{v:.6f}".rstrip("0").rstrip(".") or "0").replace(".", ","))
LITS = sorted(ANC, key=lambda l: ANC[l]); sz = lambda n: 8 * np.log10(n) ** 2
lim = {k: (min(f[k2] for f in F), max(f[k3] for f in F)) for k, k2, k3 in (("pep", "pep", "pep"), ("pr", "pr", "pr"), ("cv", "cv", "cv"))}
for clase, nom_c in (("continua", f"Roca continua (DI ≤ {dec(UMB, 0)})"), ("discontinua", f"Roca discontinua (DI > {dec(UMB, 0)})")):
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(19, 5.8))
    resumen = []
    for li in LITS:
        ee = sorted([f for f in F if f["clase"] == clase and f["lito"] == li], key=lambda f: f["pp"])
        if not ee: continue
        c = COL[li]; x = [f["pp"] for f in ee]; s = [sz(f["n"]) for f in ee]
        for ax, k in ((a1, "pep"), (a2, "pr"), (a3, "cv")):
            ax.plot(x, [f[k] for f in ee], "-", color=c, lw=1.4, label=f"{NOM[li]} — {dec(ANC[li])} MPa" if ax is a1 else None)
            ax.scatter(x, [f[k] for f in ee], s=s, color=c, edgecolor="white", lw=0.6, alpha=0.9, zorder=4)
        cand = [f for f in ee if PR_LO <= f["pr"] <= PR_HI]
        if cand:
            b = min(cand, key=lambda f: f["cv"])
            for ax, k in ((a1, "pep"), (a2, "pr"), (a3, "cv")):
                pass
            resumen.append(f"{NOM[li].split(' (')[0]}: {mil(b['pp'])} bar (CV {dec(b['cv'])} %)")
        else:
            resumen.append(f"{NOM[li].split(' (')[0]}: sin intervalo con PR 1,0–1,2")
    a1.set_ylabel("PEP mediana [bar·min/m]"); a2.set_ylabel("PR mediana [m/min]")
    a3.set_ylabel("Variabilidad interna de la PEP\nCV = desv. est. / media [%]")
    for ax, k in ((a1, "pep"), (a2, "pr"), (a3, "cv")):
        lo, hi = lim[k]; pad = 0.05 * (hi - lo); ax.set_ylim(lo - pad, hi + pad)
        ax.set_xlabel("PP [bar] (intervalos de 10 bar)"); ax.xaxis.set_major_formatter(c_); ax.yaxis.set_major_formatter(c_)
    h_, l_ = a1.get_legend_handles_labels()
    for nn in (100, 1000, 10000, 100000):
        h_.append(plt.scatter([], [], s=sz(nn), color="#A5A5A5", edgecolor="white")); l_.append(f"{mil(nn)} registros")
    fig.legend(h_, l_, fontsize=9.5, ncol=4, loc="outside lower center")
    p = os.path.join(OUT, f"PEP_PR_variabilidad_{clase}.png"); fig.savefig(p, dpi=250, facecolor="white"); print("OK", p, resumen)
