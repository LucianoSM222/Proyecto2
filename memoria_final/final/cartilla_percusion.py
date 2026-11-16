"""Cartilla de soporte a la perforación de un abanico: sección con la PP
recomendada por tramo de 5 m, curvas PR y DE(PEP) contra PP por litología,
tabla de PP recomendada y ranking de tramos de perforación.
Reusa la sección de fig_seccion_abanico.py (carga, plano, mallas).
Uso: python3 cartilla_percusion.py CASERON ABANICO percusion_recomendada.json salida.png [sin_barrenos]
Variables: EXCLUIR=17,18  FUENTE=1.2"""
import sys, os, json
AQUI = os.path.dirname(os.path.abspath(__file__))
CAS, AB, RJ, OUT = sys.argv[1:5]; SIN_B = len(sys.argv) > 5 and sys.argv[5] == "sin_barrenos"
os.environ.setdefault("FUENTE", "1.2")
src = open(os.path.join(AQUI, "fig_seccion_abanico.py"), encoding="utf-8").read()
sys.argv = ["fig_seccion_abanico.py", "fresco", CAS, AB, "pep", OUT, "todo"]
exec(src[:src.index("# barrenos")])           # carga, plano y mallas: fig, ax, ws, uv, leg, K, ...
gw.classify_all_wells_cached()                 # litología de cada registro (la carga fresca no la asigna)
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
R = json.load(open(RJ, encoding="utf-8"))["litologias"]
dec = lambda x, n=1: f"{x:.{n}f}".replace(".", ",")
PPREC = {l: d["recomendada"]["pp"] for l, d in R.items()}
lit_sec = [l for l in orden if l in R and (codigo == orden.index(l)).any()]
vals = sorted({PPREC[l] for l in lit_sec})
PAL = ["#002060", "#00897B", "#C00000", "#FF8C00", "#404040"]
COLPP = {v: PAL[i % len(PAL)] for i, v in enumerate(vals)}
quien = {v: ", ".join(NOM_L.get(l, l).split(" (")[0] for l in lit_sec if PPREC[l] == v) for v in vals}

# ── tramos de 5 m: PP recomendada = la más baja entre los dominios del tramo ──
mixtos = []
if not SIN_B:
    for w in ws:
        pts = sorted(w.points, key=lambda p: p.largo)
        Q = uv(np.array([[p.este, p.norte, p.cota] for p in pts])); Lg = np.array([p.largo for p in pts])
        ax.plot(Q[:, 0], Q[:, 1], "-", color="#BFBFBF", lw=0.8, zorder=1)
        for a in np.arange(0, Lg[-1] + 1e-9, 5.0):
            k = np.flatnonzero((Lg >= a) & (Lg < a + 5.0))
            if k.size < 2: continue
            lits = {pts[i].lito for i in k if pts[i].lito in PPREC}
            if not lits: continue
            pp = min(PPREC[l] for l in lits)
            seg = Q[k[0]:k[-1] + 2] if k[-1] + 1 < len(Q) else Q[k[0]:k[-1] + 1]
            ax.plot(seg[:, 0], seg[:, 1], "-", color=COLPP.get(pp, "#808080"), lw=3.2 * K, solid_capstyle="butt", zorder=4)
            if len(lits) > 1:
                mid = Q[k[len(k) // 2]]; mixtos.append(mid)
        ax.plot(Q[0, 0], Q[0, 1], "s", color="#404040", ms=4, zorder=5)
        ax.text(Q[-1, 0], Q[-1, 1], " " + w.hole_id + ("*" if w.hole_id in APROX else "") + " ", fontsize=8.5 * K,
                color="#404040", ha="left" if Q[-1, 0] >= Q[0, 0] else "right", va="center", zorder=6)
    if mixtos:
        M_ = np.array(mixtos); ax.plot(M_[:, 0], M_[:, 1], "o", ms=4.5, mfc="white", mec="#262626", mew=0.9, zorder=5)
else:
    # sin barrenos: cada dominio rotulado con su PP recomendada
    for l in lit_sec:
        i = orden.index(l); sel = (codigo == i)
        X, Z = GU.ravel()[sel], GZ.ravel()[sel]
        vis = (X > umin - M + 2) & (X < umax + M - 2) & (Z > zmin - M + 2) & (Z < zmax + M - 2)
        if not vis.any(): continue
        X, Z = X[vis], Z[vis]; j = np.argmin((X - X.mean()) ** 2 + (Z - Z.mean()) ** 2)
        ax.text(X[j], Z[j], f"{NOM_L.get(l, l).split(' (')[0]}\nPP {dec(PPREC[l])} bar", ha="center", va="center",
                fontsize=10.5 * K, weight="bold", color="#262626", zorder=7,
                bbox=dict(fc="white", ec=COLPP[PPREC[l]], lw=2, alpha=0.9, pad=0.4))
ax.set_xlim(umin - M, umax + M); ax.set_ylim(zmin - M, zmax + M); ax.set_aspect("equal", adjustable="box")
ax.set_xlabel("Distancia [m]"); ax.set_ylabel("Cota [m]"); ax.grid(True, color="#E6E6E6", lw=0.6); ax.set_axisbelow(True)
_pts = ["Norte", "Noreste", "Este", "Sureste", "Sur", "Suroeste", "Oeste", "Noroeste"]
_dir = lambda az_: _pts[int(((az_ + 22.5) % 360) // 45)]
_az = np.degrees(np.arctan2(h[0], h[1])) % 360
ax.annotate("← " + _dir(_az + 180), xy=(0.0, -0.075), xycoords="axes fraction", ha="left", va="top", fontsize=11 * K, weight="bold", color="#404040")
ax.annotate(_dir(_az) + " →", xy=(1.0, -0.075), xycoords="axes fraction", ha="right", va="top", fontsize=11 * K, weight="bold", color="#404040")
c_ = lambda v, _p=None: (f"{v:.6f}".rstrip("0").rstrip(".") or "0").replace(".", ",")
ax.xaxis.set_major_formatter(FuncFormatter(c_)); ax.yaxis.set_major_formatter(FuncFormatter(c_))
hand = list(leg)
if not SIN_B:
    hand += [Line2D([], [], color=COLPP[v], lw=5, label=f"PP {dec(v)} bar ({quien[v]})") for v in vals]
    hand += [Line2D([], [], marker="o", ls="", mfc="white", mec="#262626", label="Tramo con más de un dominio (PP más baja)"),
             Line2D([], [], marker="s", color="#404040", ls="", label="Collar del barreno")]
ax.legend(handles=hand, loc="upper center", bbox_to_anchor=(0.5, -0.11), ncol=2, fontsize=9 * K)
ax.set_title(("PP recomendada por tramo de 5 m" if not SIN_B else "PP recomendada por dominio") + f" · {CAS} · abanico {AB}",
             loc="left", fontsize=12 * K, color="#262626", weight="bold")

# ── panel derecho ──
fig.set_size_inches(22, 12.5)
ax.set_position([0.04, 0.22, 0.50, 0.72])
a1 = fig.add_axes([0.62, 0.69, 0.35, 0.25]); a2 = fig.add_axes([0.62, 0.43, 0.35, 0.20]); at = fig.add_axes([0.58, 0.02, 0.41, 0.36]); at.axis("off")
for l in lit_sec:
    cu = R[l]["curva"]; x = [c["pp"] for c in cu]; col = COL_L.get(l, "#808080"); rec = R[l]["recomendada"]
    a1.plot(x, [c["pr_mediana"] for c in cu], "-o", color=col, ms=3.5, lw=1.4, label=NOM_L.get(l, l).split(" (")[0])
    a2.plot(x, [c["pep_sd"] for c in cu], "-o", color=col, ms=3.5, lw=1.4)
    a1.plot(rec["pp"], rec["pr_mediana"], "*", ms=17, color=col, mec="black", mew=0.8, zorder=5)
    a2.plot(rec["pp"], rec["pep_sd"], "*", ms=17, color=col, mec="black", mew=0.8, zorder=5)
a1.axhspan(1.0, 1.2, color="#70AD47", alpha=0.18, lw=0, label="PR objetivo 1,0–1,2 m/min")
a1.set_ylabel("PR mediana [m/min]"); a2.set_ylabel("Desv. est. PEP\n[bar·min/m]"); a2.set_xlabel("PP [bar]  (tramos de 5 bar)")
a1.set_title("Respuesta de la PR a la percusión (roca continua, 4 caserones) · estrella = PP recomendada", loc="left", fontsize=11 * K, weight="bold", color="#262626")
a1.legend(fontsize=8.5 * K, loc="upper left", ncol=2)
for a in (a1, a2):
    a.grid(True, color="#E6E6E6"); a.spines[["top", "right"]].set_visible(False)
    a.xaxis.set_major_formatter(FuncFormatter(c_)); a.yaxis.set_major_formatter(FuncFormatter(c_)); a.tick_params(labelsize=9 * K)
a1.tick_params(labelbottom=False)

def tabla(axt, filas, cab, y0, alto, titulo):
    axt.text(0, y0 + 0.012, titulo, transform=axt.transAxes, fontsize=11 * K, weight="bold", color="#262626", va="bottom")
    t = axt.table(cellText=filas, colLabels=cab, bbox=[0, y0 - alto, 1, alto], cellLoc="center", colWidths=[0.22, 0.22] + [0.56 / (len(cab) - 2)] * (len(cab) - 2))
    t.auto_set_font_size(False); t.set_fontsize(8.6 * K)
    for (r, c), cel in t.get_celld().items():
        cel.set_edgecolor("black"); cel.set_linewidth(0.6)
        if r == 0 or c == 0:
            cel.set_facecolor("#1F4E79"); cel.get_text().set_color("white"); cel.get_text().set_weight("bold")
        else:
            cel.set_facecolor("#DDEBF7" if r % 2 else "white")
f1 = []
for l in lit_sec:
    r = R[l]["recomendada"]
    f1.append([NOM_L.get(l, l).split(" (")[0], dec(r["pp"]), dec(r["pr_mediana"], 2), dec(r["pep_mediana"], 0), dec(r["pep_sd"], 0),
               f"{r['n']:,}".replace(",", "."), "sí" if R[l]["candidatos"] else "no (más cercano)"])
tabla(at, f1, ["Dominio", "PP [bar]", "PR esperada\n[m/min]", "PEP\nmediana", "Desv. est.\nPEP", "Registros", "Alcanza PR\n1,0–1,2"],
      0.97, 0.06 * (len(f1) + 1) + 0.02, "Percusión recomendada por dominio")
f2 = []
for l in lit_sec:
    rk = R[l]["ranking"][:3]
    if not rk:
        f2.append([NOM_L.get(l, l).split(" (")[0], "sin tramos", "—", "—", "—", "—", "—"]); continue
    for i, t_ in enumerate(rk, 1):
        f2.append([NOM_L.get(l, l).split(" (")[0] + f" #{i}", t_["barreno"].replace("_PR01_TH_", " ").replace("_PR03_TH_", " ").replace("_CL01_TH_", " ").replace("_PR01_", " "),
                   f"{dec(t_['desde_m'], 0)}–{dec(t_['desde_m'] + 5, 0)}", dec(t_["pp"]), dec(t_["pr"], 2), dec(t_["pep"], 0), dec(100 * t_["cv_pep"], 1)])
y2 = 0.97 - (0.06 * (len(f1) + 1) + 0.02) - 0.1
tabla(at, f2, ["Dominio", "Barreno", "Tramo [m]", "PP [bar]", "PR [m/min]", "PEP", "CV PEP [%]"], y2, 0.055 * (len(f2) + 1),
      "Ranking de perforaciones: tramos de 5 m con PR 1,0–1,2 y PEP más pareja")
at.text(0, y2 - 0.055 * (len(f2) + 1) - 0.03, "Criterio: entre los tramos de PP cuya PR mediana queda en 1,0–1,2 m/min se elige el de menor varianza de PEP.\n"
        "Si un tramo de 5 m cruza varios dominios, se usa la PP más baja. Curvas históricas del equipo (registros entrenables con DI ≤ 1);\n"
        "la PP es la variable que decide el operador, no una propiedad de la roca.", transform=at.transAxes, fontsize=8 * K, color="#404040", va="top", wrap=True)
fig.savefig(OUT, dpi=200, facecolor="white"); print("OK", OUT)
