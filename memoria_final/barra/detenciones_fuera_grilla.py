"""Barrenos con detenciones PR = 0 FUERA de la grilla de cambio de barra
(detención a media barra). Elige el de periodicidad clara con más detenciones
fuera de la grilla y dibuja la PR antes y después del filtro de cambio de barra.
Uso: python3 detenciones_fuera_grilla.py proyecto_final.gwz carpeta"""
import sys, os, json
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
    gw.set_param("barra.margen_despues", 0); det = set(gw.detectar_cambio_de_barra(ps)); gw.reset_param("barra.margen_despues")
    L = np.array([p.largo for p in ps]); v = np.array([p.vel for p in ps]); emb = np.array([p.emboquillado for p in ps])
    uniones = len({round(L[i] / gw.LARGO_BARRA_M) for i in det})
    fuera = [(a, b) for a, b in rachas((v <= 0) & ~emb) if not any(k in det for k in range(a, b + 1))]
    if uniones >= 12 and len(fuera) >= 3:
        cand.append((len(fuera), uniones, wn, fuera))
cand.sort(reverse=True)
print("candidatos:", len(cand)); [print(c[:3]) for c in cand[:8]]
nf, nu, wn, fuera = cand[0]
w = gw.wells[wn]; ps = sorted(w.points, key=lambda p: p.largo)
gw.set_param("barra.margen_despues", 0); det = set(gw.detectar_cambio_de_barra(ps)); gw.reset_param("barra.margen_despues")
cb = set(gw.detectar_cambio_de_barra(ps))
L = np.array([p.largo for p in ps]); v = np.array([p.vel for p in ps])
barra = np.array([i in det for i in range(len(ps))]); margen = np.array([(i in cb and i not in det) for i in range(len(ps))])
fz = np.zeros(len(ps), bool)
for a, b in fuera: fz[a:b + 1] = True
plt.rcParams.update({"font.family": "Carlito", "font.size": 11, "axes.labelcolor": "#404040", "axes.edgecolor": "#BFBFBF",
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y", "grid.color": "#D9D9D9",
    "xtick.color": "#595959", "ytick.color": "#595959", "legend.frameon": False, "figure.constrained_layout.use": True})
coma = FuncFormatter(lambda x, _p=None: (f"{x:.6f}".rstrip("0").rstrip(".") or "0").replace(".", ","))
fig, (a1, a2) = plt.subplots(2, 1, figsize=(15, 6.4), sharex=True, sharey=True)
a1.plot(L, v, "-", color="#4472C4", lw=0.8, label="Registro")
a1.plot(L[barra], v[barra], "o", color="#C00000", ms=4.5, mec="white", mew=0.4, zorder=5, label=f"Detención en la unión de barra ({int(barra.sum())})")
a1.plot(L[margen], v[margen], "o", color="#ED7D31", ms=4.5, mec="white", mew=0.4, zorder=5, label=f"2 registros tras la detención ({int(margen.sum())})")
a1.plot(L[fz], v[fz], "D", color="#7030A0", ms=5.5, mec="white", mew=0.4, zorder=6, label=f"PR = 0 fuera de la grilla ({len(fuera)} detenciones)")
ys = v.copy(); ys[barra | margen] = np.nan
a2.plot(L, ys, "-", color="#70AD47", lw=0.8, label="Después del filtro de cambio de barra")
a2.plot(L[fz], v[fz], "D", color="#7030A0", ms=5.5, mec="white", mew=0.4, zorder=6, label="Detención a media barra: el filtro no la toca")
for x in sorted({round(L[i], 2) for i in det}):
    for a in (a1, a2): a.axvline(x, color="#C00000", ls=":", lw=0.6, alpha=0.5, zorder=0)
a1.set_title("(a) Antes del filtro", loc="left", fontsize=11, color="#404040"); a2.set_title("(b) Después del filtro (líneas punteadas: grilla de 1,756 m)", loc="left", fontsize=11, color="#404040")
hi = np.nanpercentile(v[v > 0], 99.5) * 1.15
for a in (a1, a2):
    a.set_ylabel("PR [m/min]"); a.set_ylim(-0.05, hi); a.xaxis.set_major_formatter(coma); a.yaxis.set_major_formatter(coma)
    a.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=9.5)
a2.set_xlabel("Profundidad a lo largo del barreno [m]")
p = os.path.join(OUT, f"PR_cambio_barra_detenciones_media_barra_{wn}.png"); fig.savefig(p, dpi=300, facecolor="white")
print("OK", p, "fuera:", [(round(L[a], 2), b - a + 1) for a, b in fuera])
