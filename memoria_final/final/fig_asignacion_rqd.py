"""Vista de cómo se asigna el RQD de sondaje a un barreno MWD (un par real de
la calibración a 5 m): (a) geometría 3D — tramos de testigo coloreados por RQD,
esfera de alcance de 5 m alrededor del centro del intervalo, barrenos vecinos,
registro MWD más cercano y ventana del barreno del mismo largo que el intervalo;
(b) DI a lo largo de esa ventana y regla de Deere que da el RQD equivalente.
Uso: python3 fig_asignacion_rqd.py proyecto_final.gwz SONDAJE DESDE salida.png"""
import sys, os
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import geomech_wizard as gw, cargar_caserones as cc
GWZ, SON, DESDE, OUT = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
gw.load_project(GWZ)
D = "/home/user/Proyecto2/test_data/reales/MPC Sondajes"
FILES = {"header": "MPC_header.csv", "survey": "MPC_survey.csv", "lithology": "MPC_lithology.csv",
         "structure": "MPC_structure.csv", "geomec": "MPC_geomec.csv", "density": "MPC_density.csv"}
if not gw.drillholes:
    gw.load_drillhole_csvs({k: open(os.path.join(D, v), "rb").read() for k, v in FILES.items()})
    gw.refresh_drillhole_selection()
RAD = 5.0; UMB = gw.di_threshold
IV = gw._intervalos_rqd_sondaje()
iv = next(i for i in IV if i["sondaje"] == SON and abs(i["desde"] - DESDE) < 1e-6)
par = next(p for p in gw.rqd_calibration_pairs(radio_m=RAD)["pares"] if p["sondaje"] == SON and abs(p["desde"] - DESDE) < 1e-6)
w = gw.wells[par["pozo"]]; ps = sorted(w.points, key=lambda p: p.largo)
L = np.array([p.largo for p in ps]); XYZ = np.array([[p.este, p.norte, p.cota] for p in ps])
DI = np.array([np.nan if p.di is None else p.di for p in ps])
lc = par["largo_mwd_m"]; media = max(iv["largo_m"], 0.2) / 2
k = int(np.argmin(np.abs(L - lc))); win = (L >= lc - media) & (L <= lc + media)
O = iv["centro"]; rel = lambda X: X - O                     # coordenadas relativas al centro del intervalo
plt.rcParams.update({"font.family": "Carlito", "font.size": 11, "axes.labelcolor": "#404040", "legend.frameon": False})
fig = plt.figure(figsize=(17, 7.6))
ax = fig.add_axes([0.0, 0.0, 0.50, 0.90], projection="3d")
cm = plt.cm.RdYlGn; nrm = plt.Normalize(0, 100)
for i in [i for i in IV if i["sondaje"] == SON and np.linalg.norm(i["centro"] - O) < 14]:
    a, b = rel(i["a"]), rel(i["b"]); sel = i is iv
    ax.plot(*zip(a, b), color=cm(nrm(i["rqd"])), lw=9 if sel else 6, solid_capstyle="butt", zorder=3)
    ax.text(*(rel(i["centro"]) + np.array([0.6, 0.6, 0])), f"{i['rqd']:.0f} %".replace(".", ","), fontsize=8.5, color="#262626")
u, v = np.mgrid[0:2 * np.pi:28j, 0:np.pi:16j]
ax.plot_wireframe(RAD * np.cos(u) * np.sin(v), RAD * np.sin(u) * np.sin(v), RAD * np.cos(v), color="#7F7F7F", lw=0.35, alpha=0.5)
for wn2, w2 in gw.wells.items():
    Q = np.array([[p.este, p.norte, p.cota] for p in w2.points])
    if not len(Q) or np.min(np.linalg.norm(Q - O, axis=1)) > RAD: continue
    Q = Q[np.argsort([p.largo for p in w2.points])]; R_ = rel(Q)
    R_ = np.where((np.abs(R_) <= 8).all(1)[:, None], R_, np.nan)
    ax.plot(R_[:, 0], R_[:, 1], R_[:, 2], color="#4472C4" if wn2 == par["pozo"] else "#BFBFBF", lw=1.6 if wn2 == par["pozo"] else 0.9, zorder=2)
Rw = rel(XYZ[win]); ax.plot(Rw[:, 0], Rw[:, 1], Rw[:, 2], color="#000000", lw=5, zorder=5)
pk = rel(XYZ[k]); ax.scatter(*pk, s=120, marker="*", color="#FFC000", edgecolor="black", zorder=6)
ax.scatter(0, 0, 0, s=50, color="#C00000", zorder=6)
ax.plot([0, pk[0]], [0, pk[1]], [0, pk[2]], "--", color="#C00000", lw=1.4)
ax.text(*(pk / 2 + np.array([0, 0, 0.8])), f"{par['distancia_m']:.2f} m".replace(".", ","), color="#C00000", fontsize=10, weight="bold")
ax.set_xlim(-8, 8); ax.set_ylim(-8, 8); ax.set_zlim(-8, 8); ax.set_box_aspect((1, 1, 1))
ax.set_xlabel("Este relativo [m]"); ax.set_ylabel("Norte relativo [m]"); ax.set_zlabel("Cota relativa [m]")
ax.view_init(elev=18, azim=-58)
from matplotlib.lines import Line2D
ax.legend(handles=[Line2D([], [], color=cm(nrm(80)), lw=6, label=f"Sondaje {SON}: tramos de testigo (color = RQD)"),
                   Line2D([], [], marker="o", color="#C00000", ls="", label="Centro del intervalo de testigo"),
                   Line2D([], [], color="#7F7F7F", lw=0.8, label=f"Alcance de {RAD:.0f} m (esfera de búsqueda)"),
                   Line2D([], [], marker="*", color="#FFC000", mec="black", ls="", ms=12, label="Registro MWD más cercano (uno a uno)"),
                   Line2D([], [], color="#000000", lw=4, label=f"Ventana del barreno: {iv['largo_m']:.0f} m, igual al intervalo".replace(".", ",")),
                   Line2D([], [], color="#4472C4", lw=1.6, label=f"Barreno apareado {par['pozo']}"),
                   Line2D([], [], color="#BFBFBF", lw=1, label=f"Otros barrenos con registros dentro de {RAD:.0f} m")],
          loc="upper left", fontsize=9.5, bbox_to_anchor=(0.0, 1.0))
fig.text(0.01, 0.97, "(a) Asignación del intervalo de testigo al barreno", fontsize=12, color="#262626")
# (b) DI en la ventana y regla de Deere
b = fig.add_axes([0.57, 0.14, 0.41, 0.72])
m = (L >= lc - media - 2.5) & (L <= lc + media + 2.5)
b.axvspan(lc - media, lc + media, color="#F2F2F2", zorder=0, label=f"Ventana ({iv['largo_m']:.0f} m)".replace(".", ","))
b.plot(L[m], DI[m], color="#262626", lw=1.1, zorder=3)
Lw, Dw = L[win], DI[win]; ok = np.isfinite(Dw) & (Dw <= UMB)
d = np.diff(ok.astype(int)); ini = list(np.flatnonzero(d == 1) + 1); fin = list(np.flatnonzero(d == -1))
if ok[0]: ini = [0] + ini
if ok[-1]: fin = fin + [len(ok) - 1]
for a_, c_ in zip(ini, fin):
    largo = Lw[c_] - Lw[a_]
    b.axvspan(Lw[a_], Lw[c_], ymin=0, ymax=0.06, color="#70AD47" if largo >= gw.RQD_TRAMO_MIN_M else "#ED7D31", zorder=2)
b.fill_between(Lw, UMB, Dw, where=np.isfinite(Dw) & (Dw > UMB), color="#C00000", alpha=0.3, zorder=1)
b.axhline(UMB, color="#C00000", ls="--", lw=1); b.axvline(lc, color="#FFC000", lw=2)
b.set_xlabel(f"Profundidad a lo largo del barreno {par['pozo']} [m]"); b.set_ylabel("DI")
b.spines[["top", "right"]].set_visible(False); b.grid(True, axis="y", color="#E6E6E6")
coma = FuncFormatter(lambda x, _p=None: (f"{x:.6f}".rstrip("0").rstrip(".") or "0").replace(".", ","))
b.xaxis.set_major_formatter(coma); b.yaxis.set_major_formatter(coma); b.set_ylim(0, max(2.0, np.nanmax(DI[m]) * 1.1))
b.legend(handles=[Line2D([], [], color="#F2F2F2", lw=10, label=f"Ventana de {iv['largo_m']:.0f} m centrada en el registro más cercano".replace(".", ",")),
                  Line2D([], [], color="#FFC000", lw=2, label="Registro más cercano"),
                  Line2D([], [], color="#C00000", ls="--", label="Umbral DI = 1"),
                  Line2D([], [], color="#70AD47", lw=6, label="Tramo con DI ≤ 1 de 10 cm o más (cuenta)"),
                  Line2D([], [], color="#ED7D31", lw=6, label="Tramo con DI ≤ 1 menor a 10 cm (no cuenta)")],
         loc="upper left", fontsize=9.5)
b.set_title("(b) RQD equivalente del MWD en la ventana (regla de Deere sobre el DI)", loc="left", fontsize=12, color="#262626")
txt = (f"RQD testigo ({SON}, {iv['desde']:.0f}–{iv['hasta']:.0f} m): {iv['rqd']:.1f} %\n"
       f"RQD equivalente MWD: {par['rqd_mwd']:.1f} %\n"
       f"= 100 × (suma de tramos con DI ≤ 1 y ≥ 10 cm) / {iv['largo_m']:.0f} m").replace(".", ",")
b.text(0.99, 0.97, txt, transform=b.transAxes, ha="right", va="top", fontsize=10.5, bbox=dict(fc="white", ec="#BFBFBF"))
fig.savefig(OUT, dpi=220, facecolor="white"); print("OK", OUT, par)
