"""Sección 2D en el plano de un abanico: corte de las mallas DXF (litología y
estructuras) con el plano del abanico y los barrenos coloreados por PEP o por
PR (serie filtrada del DI).
Uso: python3 fig_seccion_abanico.py proyecto_final.gwz CASERON ABANICO {pep|pr|di} salida.png [todo]"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw, cargar_caserones as cc
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter
GWZ, CAS, AB, VAR, OUT = sys.argv[1:6]
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
import glob, os
APROX = set()
if GWZ == "fresco":
    # Carga directa del caserón con el cargador vigente; los barrenos del
    # abanico que no cumplen la coherencia estricta se agregan por tolerancia
    # (7 %) y quedan marcados como posición aproximada.
    cc.asegurar_datos_extraidos(); cc.cargar_caseron(CAS, verbose=False)
    carpeta = cc._carpeta_mwd(CAS)
    plan = next(gw.wells[w].plan_id for w in gw.wells if gw._abanico_de_pozo(gw.wells[w]) == AB and (gw.wells[w].caseron == CAS))
    dqs = [gw.parse_dq(p, os.path.basename(p)) for p in glob.glob(os.path.join(carpeta, f"DQ{plan}_*.xml"))]
    dq_res, _ = gw.merge_dq_siblings(dqs)
    cargados = {gw.wells[w].hole_id for w in gw.wells if gw.wells[w].plan_id == plan}
    faltan = {}
    for p in glob.glob(os.path.join(carpeta, f"MW{plan.replace('_P', '_P')}H*_*.xml")):
        mw = gw.parse_mw(p, os.path.basename(p))
        if mw["puntos"] and mw["hole_id"] not in cargados:
            faltan.setdefault(f"{mw['plan_id']}_H{mw['hole_id']}", []).append(mw)
    antes = set(gw.wells)
    gw.match_and_place_wells(dq_res, faltan, asignar_por_tolerancia=True, tolerancia_err_pct=7.0)
    for wn in set(gw.wells) - antes:
        gw.wells[wn].caseron = CAS; APROX.add(gw.wells[wn].hole_id)
else:
    gw.load_project(GWZ)
if VAR == "di" and GWZ == "fresco":
    _fin = json.load(open(os.path.join("/home/user/Proyecto2/memoria_final/final", "final.json"), encoding="utf-8"))["di_vigente"]
    gw.aplicar_limpieza_estandar()
    gw.create_di_variant("calibrada_RQD_5m", _fin["pesos"], window=_fin["window"], threshold=_fin["umbral"])
    gw.activar_di("calibrada_RQD_5m"); gw.compute_di()
    # PRUEBA: estandarización por caserón (todo el caserón cargado), pesos de PESOS_JSON
    sys.path.insert(0, "/tmp/claude-0/-home-user-Proyecto2/fb9dc967-91ef-5038-a9a9-9123585f5c0b/scratchpad")
    import est_caseron as ec
    _w = json.loads(os.environ["PESOS_JSON"]); gw.di_config["weights"] = _w
    ec.preparar(gw, lambda w: CAS); ec.parchear(gw); gw.compute_di()
    print("pesos usados", gw.di_config["weights"])
plt.rcParams.update({"font.family": "Carlito", "font.size": 11, "axes.edgecolor": "#BFBFBF",
                     "axes.labelcolor": "#404040", "xtick.color": "#595959", "ytick.color": "#595959",
                     "legend.frameon": False})
ws = [w for w in gw.wells.values() if (w.caseron or gw.caseron_de_pozo(w)) == CAS and gw._abanico_de_pozo(w) == AB]
ws.sort(key=lambda w: w.hole_id)
# Barrenos que se omiten del dibujo, a pedido (p. ej. EXCLUIR=17,18).
_excl = {x.strip() for x in os.environ.get("EXCLUIR", "").split(",") if x.strip()}
ws = [w for w in ws if str(w.hole_id) not in _excl]
_col = np.array([[min(w.points, key=lambda p: p.largo).este, min(w.points, key=lambda p: p.largo).norte,
                  min(w.points, key=lambda p: p.largo).cota] for w in ws])
_med = np.median(_col, 0)
fuera = [w.hole_id for w, cc_ in zip(ws, _col) if np.linalg.norm(cc_ - _med) > 4.0]
SIN_FILTRO = len(sys.argv) > 6 and sys.argv[6] == "todo"
if not SIN_FILTRO:
    ws = [w for w, cc_ in zip(ws, _col) if np.linalg.norm(cc_ - _med) <= 4.0]
P = np.array([[p.este, p.norte, p.cota] for w in ws for p in w.points])
c = P.mean(0); _, _, vt = np.linalg.svd(P - c, full_matrices=False); n = vt[2]
h = np.cross(n, [0, 0, 1.0]); h /= np.linalg.norm(h)
if h[0] < 0: h = -h                                      # el eje horizontal crece hacia el Este
uv = lambda X: np.c_[(X - c) @ h, X[:, 2]]
U = uv(P); umin, umax = U[:, 0].min(), U[:, 0].max(); zmin, zmax = U[:, 1].min(), U[:, 1].max()
M = 8.0
COL_L = {"Kpcli": "#70AD47", "Bht": "#4472C4", "Brecha_mixta": "#ED7D31", "Kpcls": "#C00000",
         "Ka": "#8C8C8C", "Lutitas_normales": "#B08850", "Kpcsb_sedimentaria": "#C9A227"}
NOM_L = {"Kpcli": "Lavas inferiores (Kpcli)", "Bht": "Brecha hidrotermal (Bht)", "Brecha_mixta": "Brecha mixta",
         "Kpcls": "Lavas superiores (Kpcls)", "Ka": "Calizas (Ka)", "Lutitas_normales": "Lutitas (Kpcs)",
         "Kpcsb_sedimentaria": "Brecha sedimentaria (Kpcsb)"}
NOM_E = {"ZF": "Zona de falla", "FI": "Falla interna", "FM": "Falla menor"}


def corte(tri):
    d = (tri - c) @ n                                    # (k, 3)
    s = np.sign(d); m = (s.min(1) < 0) & (s.max(1) > 0)
    tri, d = tri[m], d[m]; segs = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        da, db = d[:, a], d[:, b]; cruza = (da * db) < 0
        t = np.where(cruza, da / np.where(cruza, da - db, 1), np.nan)
        segs.append(tri[:, a] + t[:, None] * (tri[:, b] - tri[:, a]))
    S = np.stack(segs, 1)                                 # (k, 3 aristas, 3)
    out = []
    for k in range(S.shape[0]):
        q = S[k][~np.isnan(S[k][:, 0])]
        if len(q) >= 2: out.append(uv(q[:2]))
    return np.array(out) if out else np.zeros((0, 2, 2))


fig, ax = plt.subplots(figsize=(13, 8.2))
ax.set_facecolor("#FFFFFF")
leg = []; vistas = set()
from matplotlib.patches import Patch
from matplotlib.colors import ListedColormap
v_ = np.cross(h, n); v_ = v_ if v_[2] > 0 else -v_
gu = np.arange(umin - M, umax + M + 0.5, 0.5); gz = np.arange(zmin - M, zmax + M + 0.5, 0.5)
GU, GZ = np.meshgrid(gu, gz)
G3 = c + GU.ravel()[:, None] * h + ((GZ.ravel() - c[2]) / v_[2])[:, None] * v_
lit_layers = [L for L in gw.layers.values() if L.caseron == CAS and L.kind != "estructura" and L.atributos.get("litologia")]
lit_layers.sort(key=lambda L: -np.prod(L.bbox_max - L.bbox_min))   # las menores pisan a las mayores
codigo = np.full(G3.shape[0], -1); orden = []
for L in lit_layers:
    li = L.atributos["litologia"]
    if li not in orden: orden.append(li)
    codigo[gw.points_in_mesh(G3, L)] = orden.index(li)
presentes = [i for i in range(len(orden)) if (codigo == i).any()]
if presentes:
    cmap = ListedColormap([COL_L.get(li, "#BBBBBB") for li in orden])
    img = np.ma.masked_less(codigo.reshape(GU.shape).astype(float), 0)
    ax.imshow(img, origin="lower", extent=(gu[0] - .25, gu[-1] + .25, gz[0] - .25, gz[-1] + .25), cmap=cmap,
              vmin=-0.5, vmax=len(orden) - 0.5, alpha=0.28, interpolation="nearest", zorder=0, aspect="auto")
    for i in presentes:
        leg.append(Patch(facecolor=COL_L.get(orden[i], "#BBBBBB"), alpha=0.45, label=NOM_L.get(orden[i], orden[i])))
for nm, L in gw.layers.items():
    if L.caseron != CAS: continue
    S = corte(L.triangles)
    if not len(S): continue
    mid = S.mean(1); k = (mid[:, 0] > umin - M) & (mid[:, 0] < umax + M) & (mid[:, 1] > zmin - M) & (mid[:, 1] < zmax + M)
    S = S[k]
    if not len(S): continue
    if L.kind == "estructura":
        e = L.atributos.get("estructura"); col = "#1A1A1A" if e == "ZF" else "#7030A0"
        ax.add_collection(LineCollection(S, colors=col, linewidths=2.2 if e == "ZF" else 1.6, linestyles="--", zorder=3))
        nom = nm.split(":")[-1].replace("_" + CAS.split("_")[-1], "")
        mm = S.mean(1); vis = (mm[:, 0] > umin - M + 1) & (mm[:, 0] < umax + M - 1) & (mm[:, 1] < zmax + M - 2) & (mm[:, 1] > zmin - M + 1)
        if not vis.any(): continue
        p = mm[vis][np.argmax(mm[vis][:, 1])]
        ax.text(p[0], p[1] + 1.2, nom, color=col, fontsize=9, ha="center", va="bottom", weight="bold", zorder=6,
                bbox=dict(fc="white", ec="none", alpha=0.75, pad=0.6))
        key = ("e", e)
        if key not in vistas:
            vistas.add(key); leg.append(Line2D([], [], color=col, ls="--", lw=2, label=f"{NOM_E.get(e, e)} ({e})"))
    else:
        ax.add_collection(LineCollection(S, colors="#595959", linewidths=0.7, zorder=2))
        if ("l", "contacto") not in vistas:
            vistas.add(("l", "contacto")); leg.append(Line2D([], [], color="#595959", lw=1, label="Contacto litológico (malla)"))
# barrenos
cfg = {"pep": ("se", "PEP [bar·min/m]", 150, 650, "viridis"), "pr": ("vel", "PR [m/min]", 0.3, 1.5, "plasma"),
       "di": ("di", "Índice de discontinuidad (DI)", 0.0, 3.0, "RdYlBu_r")}[VAR]
sin_di = []
xs, ys, vs = [], [], []
for w in ws:
    pts = sorted(w.points, key=lambda p: p.largo); m = gw.mascara_serie_di(pts)
    Q = uv(np.array([[p.este, p.norte, p.cota] for p in pts]))
    ax.plot(Q[:, 0], Q[:, 1], "-", color="#BFBFBF", lw=0.8, zorder=1)
    for q, p, ok in zip(Q, pts, m):
        if VAR == "di":
            if p.di is None or not np.isfinite(p.di): sin_di.append(q); continue
            xs.append(q[0]); ys.append(q[1]); vs.append(p.di); continue
        if ok or SIN_FILTRO:
            v = getattr(p, cfg[0])
            xs.append(q[0]); ys.append(q[1]); vs.append(v if np.isfinite(v) else cfg[3] * 10)
    ax.plot(Q[0, 0], Q[0, 1], "s", color="#404040", ms=4, zorder=5)
    ax.text(Q[-1, 0], Q[-1, 1], " " + w.hole_id + ("*" if w.hole_id in APROX else "") + " ", fontsize=8.5,
            color="#404040", ha="left" if Q[-1, 0] >= Q[0, 0] else "right", va="center", zorder=6)
if VAR == "di":
    from matplotlib.colors import TwoSlopeNorm
    if sin_di:
        SD = np.array(sin_di); ax.scatter(SD[:, 0], SD[:, 1], s=4, color="#D0D0D0", zorder=3, lw=0)
    # Dos clases con corte nítido en DI = 1: azules para la roca continua
    # (≤ 1) y naranjo a rojo para la discontinua (> 1), sin tono intermedio.
    from matplotlib.colors import ListedColormap
    _azul = plt.cm.Blues(np.linspace(0.95, 0.45, 128)); _rojo = plt.cm.YlOrRd(np.linspace(0.45, 1.0, 128))
    cmap_di = ListedColormap(np.vstack([_azul, _rojo]))
    sc = ax.scatter(xs, ys, c=vs, s=7, cmap=cmap_di, norm=TwoSlopeNorm(vmin=0.0, vcenter=1.0, vmax=3.0), zorder=4, lw=0)
    cb = fig.colorbar(sc, ax=ax, shrink=0.75, pad=0.015, extend="max", ticks=[0, 0.5, 1, 1.5, 2, 2.5, 3])
    cb.set_label("DI  (≤ 1 roca continua · > 1 roca discontinua)")
    cb.ax.axhline(1.0, color="black", lw=1.2)
    cb.ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p=None: (f"{v:.1f}").replace(".", ",")))
else:
    sc = ax.scatter(xs, ys, c=vs, s=7, cmap=cfg[4], vmin=cfg[2], vmax=cfg[3], zorder=4, lw=0)
    cb = fig.colorbar(sc, ax=ax, shrink=0.75, pad=0.015, extend="both"); cb.set_label(cfg[1])
ax.set_xlim(umin - M, umax + M); ax.set_ylim(zmin - M, zmax + M); ax.set_aspect("equal", adjustable="box")
ax.set_xlabel("Distancia a lo largo de la sección [m]"); ax.set_ylabel("Cota [m]")
ax.grid(True, color="#E6E6E6", lw=0.6); ax.set_axisbelow(True)
ax.legend(handles=leg + [Line2D([], [], marker="s", color="#404040", ls="", ms=5, label="Collar del barreno")]
          + ([Line2D([], [], ls="", label="* posición aproximada (largo a 6 % del DQ)")] if APROX else [])
          + ([Line2D([], [], marker="o", color="#D0D0D0", ls="", ms=4, label="Sin DI (registro filtrado)")] if VAR == "di" else []),
          loc="upper center", bbox_to_anchor=(0.5, -0.09), ncol=3, fontsize=9.5)
c_ = lambda v, _p=None: (f"{v:.6f}".rstrip("0").rstrip(".") or "0").replace(".", ",")
ax.xaxis.set_major_formatter(FuncFormatter(c_)); ax.yaxis.set_major_formatter(FuncFormatter(c_))
fig.tight_layout(); fig.savefig(OUT, dpi=300, bbox_inches="tight", facecolor="white")
az = np.degrees(np.arctan2(h[0], h[1])) % 180
print("OK", OUT, f"aprox: {sorted(APROX)}; barrenos: {sorted(int(w.hole_id) for w in ws)}; fuera del collar principal: {fuera};", f"{len(ws)} barrenos, rumbo de la sección {az:.0f}°, normal {n.round(3)}, buzamiento normal {np.degrees(np.arcsin(abs(n[2]))):.1f}°")
