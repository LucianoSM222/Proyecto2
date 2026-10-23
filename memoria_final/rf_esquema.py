"""F_RF_esquema — versión simple, al estilo de la figura de referencia.
Tres bandas: procesamiento de datos · bosque aleatorio · esquema de validación.
Números reales desde rf_figura_datos.json."""
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle, Ellipse, Polygon

S = "/home/user/Proyecto2/memoria_final"
D = json.load(open("/home/user/Proyecto2/memoria_final/rf_figura_datos.json", encoding="utf-8"))
RF = D["config"]["rf"]
emb = {e["etapa"]: e["quedan"] for e in D["embudo"]}
gk, lo = D["groupkfold"], D["loocv"]

plt.rcParams.update({"font.family": "Carlito", "font.size": 12})
BEIGE, BORDE = "#F0E8D6", "#4A4A4A"
TEAL, TEAL_OSC = "#5B9EA6", "#3F7C84"
ROSA, PERI_A, PERI_B, GRIS = "#F0B5E4", "#9A9EE8", "#AECBF0", "#D9D9D9"
NAVY, MORADO, CYAN = "#1F2D6E", "#9B6FD4", "#7FE0D4"
RAMAS = ["#7EC8E3", "#6FA8DC", "#8E7CC3", "#C27BA0", "#76D7C4"]

fig = plt.figure(figsize=(12.6, 11.4))
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")


def mil(n):
    return f"{int(n):,}".replace(",", ".")


def banda(y, h, titulo, sub=None):
    ax.add_patch(Rectangle((1, y), 98, h, facecolor=BEIGE, edgecolor=BORDE, lw=1.3, zorder=0))
    ax.text(2.5, y + h - 3.0, titulo, fontsize=13, va="center", zorder=5)
    if sub:
        ax.text(2.5, y + h - 6.4, sub, fontsize=13, va="center", zorder=5)


def cilindro(cx, cy, w, h, txt):
    ax.add_patch(Rectangle((cx - w / 2, cy - h / 2), w, h, facecolor=TEAL, edgecolor="none", zorder=3))
    for d in (-h / 2, 0, h / 2):
        ax.add_patch(Ellipse((cx, cy + d), w, h * 0.34, facecolor=TEAL,
                             edgecolor="white", lw=1.4, zorder=4))
    ax.text(cx, cy + h / 2 + 0.1, txt, ha="center", va="center", fontsize=10.5,
            color="white", zorder=6)


def flecha_gruesa(x, y0, y1):
    """Flecha ancha gris, como las del ejemplo."""
    an = 1.9
    ax.add_patch(Polygon([(x - an, y0), (x + an, y0), (x + an, y1 + 1.4),
                          (x + an * 1.75, y1 + 1.4), (x, y1), (x - an * 1.75, y1 + 1.4),
                          (x - an, y1 + 1.4)],
                         closed=True, facecolor="#9A9A9A", edgecolor="#555555", lw=0.8, zorder=5))


def caja(x, y, w, h, txt, fc, fs=11, col="#111111", lw=1.1, ec=BORDE):
    ax.add_patch(Rectangle((x, y), w, h, facecolor=fc, edgecolor=ec, lw=lw, zorder=3))
    for i, ln in enumerate(txt.split("\n")):
        ax.text(x + w / 2, y + h / 2 + (len(txt.split("\n")) - 1) * 1.05 - i * 2.1, ln,
                ha="center", va="center", fontsize=fs, color=col, zorder=4)


# ══════════ BANDA 1 — procesamiento de datos ══════════
banda(66.5, 32.5, "Procesamiento de datos", "Registros MWD de entrada")

ax.add_patch(Rectangle((23, 85.0), 54, 11.5, fill=False, edgecolor=BORDE,
                       lw=1.8, linestyle=(0, (5, 3)), zorder=2))
for i, c in enumerate(D["por_caseron"]):
    cilindro(29.5 + i * 13.0, 90.7, 9.6, 5.0, c["caseron"])
ax.text(79.5, 90.7, f"{mil(emb['total'])} registros\n{len(D['config']['ml_labels'])} variables\n"
        "1 objetivo: UCS", ha="left", va="center", fontsize=11, zorder=6)

flecha_gruesa(50.0, 84.6, 80.4)
caja(23, 75.0, 73, 5.0, f"Limpieza + roca intacta (DI calibrado ≤ 1)  ·  {mil(emb['roca_intacta'])} muestras", ROSA)
ax.text(21.5, 77.5, "Filtro\ngeomecánico", ha="right", va="center", fontsize=11.5, zorder=5)

caja(23, 68.5, 36.5, 5.6, f"{len(D['config']['ml_labels'])} variables MWD\n" +
     " · ".join(D["config"]["ml_labels"]), PERI_B, fs=10.5)
caja(59.5, 68.5, 36.5, 5.6, f"Objetivo\nUCS por litología ({len(D['etiquetas'])} clases)", PERI_A, fs=10.5)

# ══════════ BANDA 2 — el bosque ══════════
banda(26.0, 39.0, "Bosque aleatorio")

rng = np.random.default_rng(42)


def arbol(cx, top, ancho, alto):
    """Árbol esquemático de 4 niveles, SIN cruces: se sortea cuántos hijos tiene
    cada nodo, las hojas se reparten equiespaciadas y cada padre se ubica en la
    media de sus hijos. Es ilustrativo; los números reales del árbol entrenado
    están en la figura detallada."""
    hijos_de = {}
    niveles = [[0]]
    nid = 1
    for k in range(3):
        nxt = []
        for p in niveles[-1]:
            nh = int(rng.integers(2, 4)) if k < 2 else int(rng.integers(1, 3))
            hijos_de[p] = list(range(nid, nid + nh))
            nxt += hijos_de[p]; nid += nh
        niveles.append(nxt)
    pos = {}
    hojas = niveles[-1]
    sep = ancho / max(1, len(hojas) - 1)
    for i, h in enumerate(hojas):
        pos[h] = cx - ancho / 2 + i * sep
    for k in range(len(niveles) - 2, -1, -1):
        for p in niveles[k]:
            pos[p] = float(np.mean([pos[h] for h in hijos_de[p]]))
    paso = alto / 3.0
    for k in range(len(niveles) - 1):
        for p in niveles[k]:
            for h in hijos_de[p]:
                ax.plot([pos[p], pos[h]], [top - k * paso, top - (k + 1) * paso],
                        color=RAMAS[k % len(RAMAS)], lw=1.9, solid_capstyle="round", zorder=3)
    for k, nv in enumerate(niveles):
        for n in nv:
            ax.plot(pos[n], top - k * paso, "o", ms=5.2, color=NAVY, zorder=4)


for j, (cx, et) in enumerate([(21, "Conjunto bootstrap 1"), (50, "Conjunto bootstrap 2"),
                              (79, f"Conjunto bootstrap {RF['n_estimators']}")]):
    caja(cx - 12.5, 57.0, 25, 4.4, et, "white", fs=11)
    arbol(cx, 55.0, 23, 13.0)
    flecha_gruesa(cx, 41.0, 37.6)
    caja(cx - 10.5, 32.0, 21, 4.4, f"Predicción {j + 1 if j < 2 else RF['n_estimators']}", "white", fs=11)

ax.text(64.5, 48.0, ". . .", fontsize=20, color="#555555", ha="center", zorder=5)
ax.plot([21, 21, 79, 79], [32.0, 30.2, 30.2, 32.0], color="#555555", lw=1.1, zorder=3)
ax.plot([50, 50], [30.2, 29.0], color="#555555", lw=1.1, zorder=3)
caja(33, 26.6, 34, 4.6, f"Agregación  ·  mediana de los {RF['n_estimators']} árboles",
     TEAL_OSC, fs=11.5, col="white", ec=TEAL_OSC)

# ══════════ BANDA 3 — validación ══════════
banda(1.5, 23.0, "Esquema de validación")

# GroupKFold por pozo
ax.text(6.0, 19.6, f"Validación cruzada agrupada por pozo\nGroupKFold, k = {gk['n_pliegues']}  ·  "
        f"{mil(D['n_pozos_grupo'])} pozos", fontsize=11, va="center", zorder=5)
nf, x0, w, hgt = gk["n_pliegues"], 6.0, 6.4, 2.1
for it in range(nf):
    yy = 15.0 - it * 2.65
    for k in range(nf):
        ax.add_patch(Rectangle((x0 + k * (w + 0.5), yy), w, hgt,
                               facecolor=CYAN if k == it else MORADO,
                               edgecolor="white", lw=1.0, zorder=3))
    ax.text(x0 + nf * (w + 0.5) + 0.8, yy + hgt / 2, f"{it + 1}ª iteración",
            fontsize=9.5, va="center", zorder=5)
ax.add_patch(Rectangle((6.0, 2.4), 3.0, 1.5, facecolor=MORADO, edgecolor="white", zorder=3))
ax.text(9.6, 3.15, "Fold de ajuste", fontsize=9.5, va="center", zorder=5)
ax.add_patch(Rectangle((24.0, 2.4), 3.0, 1.5, facecolor=CYAN, edgecolor="white", zorder=3))
ax.text(27.6, 3.15, "Fold de prueba", fontsize=9.5, va="center", zorder=5)

# LOOCV por caserón
ax.text(57.0, 19.6, "Validación dejando un caserón fuera (LOOCV-Caserón)\n"
        f"{len(lo['pliegues'])} iteraciones  ·  4 caserones", fontsize=11, va="center", zorder=5)
x0b, wb = 57.0, 8.2
for it, f in enumerate(lo["pliegues"]):
    yy = 15.0 - it * 2.65
    for k in range(4):
        ax.add_patch(Rectangle((x0b + k * (wb + 0.5), yy), wb, hgt,
                               facecolor=CYAN if k == it else MORADO,
                               edgecolor="white", lw=1.0, zorder=3))
    ax.text(x0b + 4 * (wb + 0.5) + 0.8, yy + hgt / 2, f["pliegue"], fontsize=9.5,
            va="center", zorder=5)

caja(57.0, 2.2, 38.0, 4.0,
     (f"R² = {gk['r2_medio']:.3f}  ·  RMSE = {gk['rmse_medio']:.1f} MPa   (por pozo)\n"
      f"R² = {lo['r2_medio_cross_val_score']:.3f}  ·  RMSE = {lo['rmse_medio']:.1f} MPa   (por caserón, {lo['n_definidos']} definidos)").replace(".", ","),
     "white", fs=10.5)

fig.savefig("/home/user/Proyecto2/figuras/F_RF_esquema.png", dpi=300,
            bbox_inches="tight", facecolor="white")
print("F_RF_esquema.png OK")
