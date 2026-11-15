"""Reporte de un barreno: todas las variables MWD, PEP y DI a lo largo del
barreno, con los filtros marcados, más una tabla resumen (todos / serie del DI).
Uso: python3 reporte_barreno.py proyecto_final.gwz BARRENO carpeta_salida"""
import sys, os, json
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import geomech_wizard as gw, cargar_caserones as cc
GWZ, WN, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True)
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
gw.load_project(GWZ)
w = gw.wells[WN]; ps = sorted(w.points, key=lambda p: p.largo); n = len(ps)
L = np.array([p.largo for p in ps])
V = {"PR": np.array([p.vel for p in ps], float), "PP": np.array([p.pp for p in ps], float),
     "FP": np.array([p.pa for p in ps], float), "DP": np.array([p.pd for p in ps], float),
     "RP": np.array([p.pr for p in ps], float), "FLP": np.array([p.pf for p in ps], float)}
with np.errstate(divide="ignore", invalid="ignore"):
    V["PEP"] = np.where(V["PR"] > 0, (V["PP"] + V["RP"] + V["FP"]) / V["PR"], np.nan)
DI = np.array([np.nan if p.di is None else p.di for p in ps])
lim = gw.limites_equipo(); tope = float(gw.get_param("limites.pr_max_di"))
gw.set_param("barra.margen_despues", 0); det = set(gw.detectar_cambio_de_barra(ps))
gw.reset_param("barra.margen_despues"); cb = set(gw.detectar_cambio_de_barra(ps))
co = set(gw._indices_tras_salto(ps))
emb = np.array([bool(p.emboquillado) for p in ps])
barra = np.array([i in det for i in range(n)]); margen = np.array([(i in cb and i not in det) for i in range(n)])
equipo = (V["PR"] <= 0) | (V["PR"] > tope) | (V["PP"] < lim["PP"][1]) | (V["FP"] < lim["FP"][1]) | (V["FLP"] > lim["FLP"][2])
cont = np.array([i in co for i in range(n)])
serie = gw.mascara_serie_di(ps)
roca = serie & ~np.array([p.entrenable for p in ps])
corte = gw.inicio_por_pozo.get(WN, (None, None))
lito = [p.lito for p in ps]

# ── figura ──
plt.rcParams.update({
    "font.family": "Carlito", "font.size": 10.5, "text.color": "#262626", "axes.labelcolor": "#404040",
    "axes.edgecolor": "#BFBFBF", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "axes.axisbelow": True, "grid.color": "#D9D9D9", "grid.linewidth": 0.8,
    "xtick.color": "#595959", "ytick.color": "#595959", "legend.frameon": False,
    "figure.constrained_layout.use": True, "savefig.pad_inches": 0.04})
AZUL, ROJO, VERDE, NARANJA, GRIS, MORADO, NEGRO = "#4472C4", "#C00000", "#70AD47", "#ED7D31", "#A5A5A5", "#7030A0", "#000000"
coma = FuncFormatter(lambda v, _: (f"{v:.6f}".rstrip("0").rstrip(".") or "0").replace(".", ","))
PAN = [("PR", "PR [m/min]"), ("PP", "PP [bar]"), ("FP", "FP [bar]"), ("DP", "DP [bar]"),
       ("RP", "RP [bar]"), ("FLP", "FLP [bar]"), ("PEP", "PEP [bar·min/m]"), ("DI", "DI")]
MARC = [(emb, "Emboquillado", GRIS), (barra, "Cambio de barra", ROJO), (margen, "Margen tras la barra", NARANJA),
        (equipo & ~emb & ~barra & ~margen, "Equipo sin perforar", MORADO), (cont, "Continuidad", NEGRO),
        (roca, "Fuera de rango (solo entrenamiento)", VERDE)]
fig, axs = plt.subplots(len(PAN), 1, figsize=(13, 15), sharex=True)
for ax, (k, et) in zip(axs, PAN):
    y = DI if k == "DI" else V[k]
    ax.plot(L, y, "-", color=AZUL, lw=0.7, zorder=2)
    if k != "DI":
        for m, r, c in MARC:
            if m.any(): ax.plot(L[m], y[m], "o", color=c, ms=2.6, mew=0, zorder=4, label=r)
    if k in lim:
        for v_ in lim[k][1:]: ax.axhline(v_, color=GRIS, ls="--", lw=0.8, zorder=1)
    if k == "PR":
        ax.axhline(tope, color=GRIS, ls=":", lw=0.8)
        ax.set_ylim(-0.05, max(lim["PR"][2] * 1.15, np.nanpercentile(y[y > 0], 99.5) * 1.15))
    if k == "PEP":
        ok = np.isfinite(y); ax.set_ylim(0, np.nanpercentile(y[ok & serie], 99.5) * 1.2)
    if k == "DI":
        ax.axhline(1.0, color=ROJO, ls="--", lw=0.9, label="Umbral DI = 1")
        ax.fill_between(L, 0, np.where(DI > 1, DI, np.nan), color=ROJO, alpha=0.25, lw=0, label="Roca discontinua")
        ax.set_ylim(0, np.nanmax(DI) * 1.05)
    for x in sorted({round(L[i], 2) for i in det}): ax.axvline(x, color=ROJO, ls=":", lw=0.5, alpha=0.5, zorder=0)
    if corte[0]: ax.axvline(corte[0], color=GRIS, ls="--", lw=1)
    ax.set_ylabel(et); ax.xaxis.set_major_formatter(coma); ax.yaxis.set_major_formatter(coma)
h, l = axs[0].get_legend_handles_labels()
h2, l2 = axs[-1].get_legend_handles_labels()
fig.legend(h + h2, l + l2, loc="outside lower center", ncol=4, fontsize=10, markerscale=2.5)
axs[-1].set_xlabel("Profundidad a lo largo del barreno [m]")
# litología como banda en el eje superior
cols = {"Kpcli": VERDE, "Bht": AZUL, "Brecha_mixta": NARANJA, "Kpcls": ROJO}
prev, ini = None, L[0]
for i, li in enumerate(lito + [None]):
    if li != prev or i == n:
        if prev is not None:
            axs[0].axvspan(ini, L[i - 1], ymin=0.94, ymax=1.0, color=cols.get(prev, GRIS), alpha=0.6, lw=0)
            axs[0].text((ini + L[i - 1]) / 2, axs[0].get_ylim()[1], str(prev), ha="center", va="bottom", fontsize=9, color="#404040")
        prev = li; ini = L[i] if i < n else ini
p = os.path.join(OUT, f"Reporte_variables_{WN}.png"); fig.savefig(p, dpi=250, facecolor="white"); print("OK", p)

# ── tabla resumen ──
def fila(k, m):
    y = (DI if k == "DI" else V[k])[m]; y = y[np.isfinite(y)]
    if not y.size: return None
    return {"min": float(y.min()), "p50": float(np.median(y)), "media": float(y.mean()), "max": float(y.max()),
            "n": int(y.size), "ceros": int((y == 0).sum())}
res = {"barreno": WN, "caseron": gw.caseron_de_pozo(w), "n": n, "largo_m": [float(L[0]), float(L[-1])],
       "litologias": sorted({str(x) for x in lito}), "estructuras": sorted({str(p.estructura) for p in ps if p.estructura}),
       "emboquillado": list(corte), "uniones_barra": len({round(L[i] / gw.LARGO_BARRA_M) for i in det}),
       "filtros": {"emboquillado": int(emb.sum()), "cambio_barra": int(barra.sum()), "margen": int(margen.sum()),
                   "equipo_sin_perforar": int(equipo.sum()), "continuidad": int(cont.sum()), "solo_entrenamiento": int(roca.sum()),
                   "serie_DI": int(serie.sum()), "entrenables": int(sum(p.entrenable for p in ps))},
       "di": {"pct_discontinua": float(100 * np.nanmean(DI[serie] > 1)), "pesos": gw.di_config["weights"]},
       "todos": {k: fila(k, np.ones(n, bool)) for k, _ in PAN}, "serie_DI": {k: fila(k, serie) for k, _ in PAN}}
json.dump(res, open(os.path.join(OUT, f"Reporte_variables_{WN}.json"), "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in res.items() if k not in ("todos", "serie_DI")}, ensure_ascii=False))
for g in ("todos", "serie_DI"):
    print(g)
    for k, f in res[g].items():
        if f: print(f"  {k:4s} min {f['min']:9.2f} p50 {f['p50']:8.2f} media {f['media']:9.2f} max {f['max']:10.2f} n {f['n']} ceros {f['ceros']}")
