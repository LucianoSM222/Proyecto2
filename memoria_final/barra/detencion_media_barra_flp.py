"""Barreno con pocas detenciones fuera de la grilla (≤ 14), ubicadas cerca de
la mitad de la barra (~0,88 m tras la unión), y con alza de FLP antes de cada
una. Dibuja la PR (antes del filtro) y la FLP.
Uso: python3 detencion_media_barra_flp.py proyecto_final.gwz carpeta"""
import sys, os
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import geomech_wizard as gw, cargar_caserones as cc
GWZ, OUT = sys.argv[1:3]
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
gw.load_project(GWZ)
LB = gw.LARGO_BARRA_M; MED = LB / 2
def rachas(m):
    r, i = [], 0
    while i < len(m):
        if m[i]:
            j = i
            while j + 1 < len(m) and m[j + 1]: j += 1
            r.append((i, j)); i = j + 1
        else: i += 1
    return r
cand = []
for wn, w in gw.wells.items():
    ps = sorted(w.points, key=lambda p: p.largo)
    if len(ps) < 1000: continue
    gw.set_param("barra.margen_despues", 0); det = sorted(gw.detectar_cambio_de_barra(ps)); gw.reset_param("barra.margen_despues")
    L = np.array([p.largo for p in ps]); v = np.array([p.vel for p in ps]); f = np.array([p.pf for p in ps]); emb = np.array([p.emboquillado for p in ps])
    U = []
    for i in det:
        if not U or L[i] - U[-1] > 0.5: U.append(L[i])
    if len(U) < 12: continue
    U = np.array(U); ds = set(det)
    fuera = [(a, b) for a, b in rachas((v <= 0) & ~emb) if not any(k in ds for k in range(a, b + 1)) and a >= 40]
    if not (3 <= len(fuera) <= 14): continue
    fase = [(L[a] - U[0]) % LB for a, _ in fuera]
    medio = [abs(x - MED) <= 0.2 for x in fase]
    alza = [f[a - 8:a].mean() - f[a - 40:a - 20].mean() for a, _ in fuera]
    sc = sum(medio) / len(fuera) + 0.5 * np.mean([x > 0.05 for x in alza])
    cand.append((sc, sum(medio), len(fuera), round(float(np.median(alza)), 3), wn))
cand.sort(reverse=True)
for c in cand[:8]: print(c)
wn = cand[0][4]; w = gw.wells[wn]; ps = sorted(w.points, key=lambda p: p.largo)
gw.set_param("barra.margen_despues", 0); det = set(gw.detectar_cambio_de_barra(ps)); gw.reset_param("barra.margen_despues")
cb = set(gw.detectar_cambio_de_barra(ps))
L = np.array([p.largo for p in ps]); v = np.array([p.vel for p in ps]); f = np.array([p.pf for p in ps]); emb = np.array([p.emboquillado for p in ps])
barra = np.array([i in det for i in range(len(ps))]); margen = np.array([(i in cb and i not in det) for i in range(len(ps))])
fuera = [(a, b) for a, b in rachas((v <= 0) & ~emb) if not any(k in det for k in range(a, b + 1)) and a >= 40]
fz = np.zeros(len(ps), bool)
for a, b in fuera: fz[a:b + 1] = True
plt.rcParams.update({"font.family": "Carlito", "font.size": 11, "axes.labelcolor": "#404040", "axes.edgecolor": "#BFBFBF",
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y", "grid.color": "#D9D9D9",
    "xtick.color": "#595959", "ytick.color": "#595959", "legend.frameon": False, "figure.constrained_layout.use": True})
coma = FuncFormatter(lambda x, _p=None: (f"{x:.6f}".rstrip("0").rstrip(".") or "0").replace(".", ","))
fig, (a1, a2) = plt.subplots(2, 1, figsize=(15, 6.6), sharex=True)
a1.plot(L, v, "-", color="#4472C4", lw=0.8, label="PR registrada")
a1.plot(L[barra], v[barra], "o", color="#C00000", ms=4.5, mec="white", mew=0.4, zorder=5, label=f"Detención en la unión de barra ({int(barra.sum())})")
a1.plot(L[margen], v[margen], "o", color="#ED7D31", ms=4.5, mec="white", mew=0.4, zorder=5, label=f"2 registros tras la detención ({int(margen.sum())})")
a1.plot(L[fz], v[fz], "D", color="#7030A0", ms=6, mec="white", mew=0.4, zorder=6, label=f"PR = 0 fuera de la grilla ({len(fuera)} detenciones)")
a2.plot(L, f, "-", color="#00897B", lw=0.9, label="FLP registrada")
a2.plot(L[fz], f[fz], "D", color="#7030A0", ms=6, mec="white", mew=0.4, zorder=6, label="Detención fuera de la grilla")
for x in sorted({round(L[i], 2) for i in det}):
    for a in (a1, a2): a.axvline(x, color="#C00000", ls=":", lw=0.6, alpha=0.5, zorder=0)
for a_, _ in fuera:
    for a in (a1, a2): a.axvline(L[a_], color="#7030A0", ls="-", lw=0.6, alpha=0.35, zorder=0)
hi = np.nanpercentile(v[v > 0], 99.5) * 1.15; a1.set_ylim(-0.05, hi)
a1.set_ylabel("PR [m/min]"); a2.set_ylabel("FLP [bar]"); a2.set_xlabel("Profundidad a lo largo del barreno [m]")
ok = ~emb; lo, hi2 = np.percentile(f[ok], [0.5, 99.8]); a2.set_ylim(lo - 0.3, hi2 + 0.3)
for a in (a1, a2):
    a.xaxis.set_major_formatter(coma); a.yaxis.set_major_formatter(coma); a.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=9.5)
p = os.path.join(OUT, f"PR_FLP_detencion_media_barra_{wn}.png"); fig.savefig(p, dpi=300, facecolor="white")
U0 = min(L[i] for i in det)
print("OK", p, [(round(L[a], 2), round((L[a] - U0) % LB, 2), round(float(f[a - 8:a].mean() - f[a - 40:a - 20].mean()), 2)) for a, _ in fuera])
