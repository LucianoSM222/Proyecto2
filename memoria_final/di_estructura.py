"""DI del pozo PCC_0042_PR01_TH_P20_H12 contra el modelo geológico,
con énfasis en lo estructural. Solo carga PCC_0042."""
import sys, os, time, json
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Patch
import geomech_wizard as gw
import cargar_caserones as cc

S = "/home/user/Proyecto2/memoria_final"
POZO = "PCC_0042_PR01_TH_P20_H12"
t0 = time.time()
cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
cc.cargar_caseron("PCC_0042", verbose=False)
gw.classify_all_wells_cached(); gw.build_domain_index(); gw.compute_di()
# DI calibrado a 5 m, con los pesos que produjo final_calc.py sobre los 4 caserones
_FIN = json.load(open(f"{S}/final/final.json", encoding="utf-8"))["di_vigente"]
gw.create_di_variant("calibrada_RQD_5m", _FIN["pesos"], window=_FIN["window"], threshold=_FIN["umbral"])
gw.activar_di("calibrada_RQD_5m"); gw.compute_di()
UMBRAL = gw.di_threshold
print(f"carga OK umbral={UMBRAL} t={time.time()-t0:.0f}s", flush=True)

w = gw.wells[POZO]
pts = sorted(w.points, key=lambda p: p.largo)
lar = np.array([p.largo for p in pts])
di = np.array([p.di if p.di is not None else np.nan for p in pts])
lito = [p.lito for p in pts]
est = [p.estructura for p in pts]
pp = np.array([p.pp for p in pts]); pd_ = np.array([p.pd for p in pts])
pr = np.array([p.pr for p in pts]); pf = np.array([p.pf for p in pts])


def tramos(serie):
    """(inicio, fin, valor) de cada tramo contiguo; ignora None."""
    out, prev, ini = [], "\0", 0
    for i, v in enumerate(list(serie) + ["\0"]):
        if v != prev:
            if prev not in ("\0", None):
                out.append((lar[ini], lar[min(i, len(lar) - 1)], prev))
            ini, prev = i, v
    return out


tr_lito = tramos(lito)
tr_est = [t for t in tramos(est) if t[2]]
# fronteras estructurales = entradas y salidas de cada tramo con estructura
fronteras = sorted({round(x, 3) for t in tr_est for x in (t[0], t[1])})

# picos de DI con la constante del proyecto
idx = np.flatnonzero(np.nan_to_num(di, nan=-1) > UMBRAL)
picos = []
if idx.size:
    grupo = [idx[0]]
    for i in idx[1:]:
        if lar[i] - lar[grupo[-1]] >= gw.DI_PICOS_MIN_GAP_M:
            picos.append(grupo); grupo = [i]
        else:
            grupo.append(i)
    picos.append(grupo)
picos_l = [float(lar[g[int(np.argmax(di[g]))]]) for g in picos]
picos_di = [float(np.nanmax(di[g])) for g in picos]

# delta de cada pico a la frontera estructural mas cercana
deltas = []
if fronteras:
    fa = np.array(fronteras)
    for pl in picos_l:
        j = int(np.argmin(np.abs(fa - pl)))
        deltas.append(round(float(pl - fa[j]), 3))

dentro_est = [bool(any(a <= pl <= b for a, b, _ in tr_est)) for pl in picos_l]
largo_est = sum(b - a for a, b, _ in tr_est)
n_sobre = int(np.nansum(di > UMBRAL))
DAT = {
    "pozo": POZO, "umbral_DI": UMBRAL, "min_gap_m": gw.DI_PICOS_MIN_GAP_M,
    "largo_m": round(float(lar[-1]), 2), "n_puntos": len(pts),
    "n_muestras_sobre_umbral": n_sobre,
    "pct_sobre_umbral": round(100.0 * n_sobre / len(pts), 2),
    "n_picos": len(picos_l), "picos_m": [round(x, 2) for x in picos_l],
    "picos_di": [round(x, 2) for x in picos_di],
    "tramos_litologia": [(round(a, 2), round(b, 2), c) for a, b, c in tr_lito],
    "tramos_estructura": [(round(a, 2), round(b, 2), c) for a, b, c in tr_est],
    "largo_con_estructura_m": round(largo_est, 2),
    "pct_largo_con_estructura": round(100.0 * largo_est / float(lar[-1]), 2),
    "fronteras_estructurales_m": fronteras,
    "delta_pico_a_frontera_m": deltas,
    "picos_dentro_de_zona_estructural": int(sum(dentro_est)),
    "di_max": round(float(np.nanmax(di)), 2), "di_mediana": round(float(np.nanmedian(di)), 3),
}
# ── contexto: ¿qué dice el modelo del resto del caserón? ──
col = np.array([w.points[0].este, w.points[0].norte, w.points[0].cota], dtype=np.float64)
con_est, sin_est, ests_cas, vecinos = 0, 0, {}, []
for wn2, w2 in gw.wells.items():
    es = {p.estructura for p in w2.points if p.estructura}
    if es:
        con_est += 1
        for e in es: ests_cas[e] = ests_cas.get(e, 0) + 1
        p0 = w2.points[0]
        d = float(np.linalg.norm(np.array([p0.este, p0.norte, p0.cota]) - col))
        vecinos.append((d, wn2, sorted(es)))
    else:
        sin_est += 1
vecinos.sort()
DAT["contexto_caseron"] = {
    "caseron": "PCC_0042", "n_pozos": len(gw.wells),
    "pozos_con_estructura": con_est, "pozos_sin_estructura": sin_est,
    "pct_con_estructura": round(100.0 * con_est / len(gw.wells), 1),
    "estructuras_presentes": ests_cas,
    "pozo_con_estructura_mas_cercano": (
        {"pozo": vecinos[0][1], "distancia_collar_m": round(vecinos[0][0], 1),
         "estructuras": vecinos[0][2]} if vecinos else None)}
print("CONTEXTO:", DAT["contexto_caseron"], flush=True)
json.dump(DAT, open(f"{S}/di_estructura_datos.json", "w"), ensure_ascii=False, indent=2)
print(json.dumps({k: v for k, v in DAT.items() if k not in ("fronteras_estructurales_m",)},
                 ensure_ascii=False, indent=1), flush=True)

# ───────────────────────── figura ─────────────────────────
plt.rcParams.update({"font.family": "Liberation Sans", "font.size": 9})
COL_LITO = {"Bht": "#2C5F8A", "Brecha_mixta": "#C77B2E", "Kpcli": "#2E7D5B", "Kpcls": "#A33B3B"}
PAL_EST = ["#7B2D8E", "#D4A017", "#1F9E9E", "#B5446E", "#5A6E3C"]
ests = sorted({c for _, _, c in tr_est})
COL_EST = {e: PAL_EST[i % len(PAL_EST)] for i, e in enumerate(ests)}
ROJO = "#A33B3B"

VEC = DAT["contexto_caseron"]["pozo_con_estructura_mas_cercano"]
vn = VEC["pozo"] if VEC else None
if vn:
    pv = sorted(gw.wells[vn].points, key=lambda q: q.largo)
    lv = np.array([q.largo for q in pv])
    dv = np.array([q.di if q.di is not None else np.nan for q in pv])
    ev = [q.estructura for q in pv]
    tv, prev, ini = [], "\0", 0
    for i, v in enumerate(ev + ["\0"]):
        if v != prev:
            if prev not in ("\0", None):
                tv.append((lv[ini], lv[min(i, len(lv) - 1)], prev))
            ini, prev = i, v
    tr_est_vec = [t for t in tv if t[2]]
else:
    tr_est_vec = []

nfil = 4 if vn else 3
fig, axes = plt.subplots(nfil, 1, figsize=(13.5, 11.6 if vn else 9.6), sharex=True,
                         gridspec_kw={"height_ratios": [1.0, 2.3, 1.6, 1.7][:nfil]})


def fondo(ax):
    for a, b, l in tr_lito:
        ax.axvspan(a, b, color=COL_LITO.get(l, "#888888"), alpha=0.12, zorder=0, lw=0)
    for a, b, e in tr_est:
        ax.axvspan(a, b, facecolor=COL_EST[e], alpha=0.26, hatch="//",
                   edgecolor=COL_EST[e], lw=0, zorder=1)
        ax.axvline(a, color=COL_EST[e], lw=1.1, ls="--", zorder=2)
        ax.axvline(b, color=COL_EST[e], lw=1.1, ls="--", zorder=2)


# A — franja del modelo geológico
ax = axes[0]; fondo(ax)
ax.set_ylim(0, 1); ax.set_yticks([])
for a, b, l in tr_lito:
    if b - a > 1.2:
        ax.text((a + b) / 2, 0.70, l, ha="center", va="center", fontsize=8.5,
                color=COL_LITO.get(l, "#333"), fontweight="bold", zorder=4)
for a, b, e in tr_est:
    ax.text((a + b) / 2, 0.26, e, ha="center", va="center", fontsize=8,
            color=COL_EST[e], fontweight="bold", zorder=4,
            bbox=dict(boxstyle="round,pad=0.18", facecolor="white", alpha=0.85, edgecolor="none"))
if not tr_est:
    ax.text(float(lar[-1]) / 2, 0.30,
            "El modelo geológico NO asigna ninguna estructura a este tiro",
            ha="center", va="center", fontsize=10, fontweight="bold", color=ROJO, zorder=5,
            bbox=dict(boxstyle="round,pad=0.35", facecolor="white", edgecolor=ROJO, lw=1.2))
ax.set_ylabel("Modelo\ngeológico", fontsize=9)
ax.set_title(f"DI del pozo {POZO} contra el modelo geológico — énfasis estructural",
             fontsize=12.5, fontweight="bold", pad=10)

# B — DI
ax = axes[1]; fondo(ax)
ax.plot(lar, di, "-", color="#1a1a1a", lw=0.85, zorder=3)
ax.axhline(UMBRAL, color=ROJO, ls="--", lw=1.2, zorder=4)
ax.fill_between(lar, UMBRAL, di, where=(di > UMBRAL), color=ROJO, alpha=0.25, zorder=2)
for pl, pv, dd in zip(picos_l, picos_di, dentro_est):
    ax.plot(pl, pv, "v", ms=7, color=ROJO if dd else "#333333",
            markeredgecolor="white", markeredgewidth=0.7, zorder=6)
ax.set_ylabel("DI (índice de discontinuidad)", fontsize=9)
ax.grid(alpha=0.25, lw=0.6)
ax.text(0.005, 0.96, (f"DI calibrado a 5 m (PP {gw.di_config['weights']['pp']:.2f} · RP {gw.di_config['weights']['pr']:.2f} · "
        f"DP {gw.di_config['weights']['pd']:.2f} · FP {gw.di_config['weights']['pf']:.2f})   ·   umbral {UMBRAL:g}   ·   ventana {gw.di_config['window']} muestras "
        f"= {gw.DI_VENTANA_CM:g} cm   ·   picos fusionados a {gw.DI_PICOS_MIN_GAP_M:g} m").replace(".", ","),
        transform=ax.transAxes, va="top", fontsize=8, color="#444444")

# C — las cuatro presiones del DI
ax = axes[2]; fondo(ax)
for arr, nom, col in [(pp, "PP", "#2C5F8A"), (pd_, "DP", "#C77B2E"),
                      (pr, "RP", "#2E7D5B"), (pf, "FP", "#7B2D8E")]:
    ax.plot(lar, arr, "-", lw=0.7, color=col, label=nom, zorder=3)
ax.set_ylabel("Presiones del DI (bar)", fontsize=9)
ax.set_xlabel("Profundidad a lo largo del pozo (m)", fontsize=10)
ax.grid(alpha=0.25, lw=0.6)
ax.legend(fontsize=8, ncol=4, loc="upper right", framealpha=0.9)
ax.set_xlim(0, float(lar[-1]))

if vn:
    axv = axes[3]
    for a, b, e in tr_est_vec:
        axv.axvspan(a, b, facecolor=COL_EST.get(e, "#7B2D8E"), alpha=0.30, hatch="//",
                    edgecolor=COL_EST.get(e, "#7B2D8E"), lw=0, zorder=1)
        axv.axvline(a, color=COL_EST.get(e, "#7B2D8E"), lw=1.1, ls="--", zorder=2)
        axv.axvline(b, color=COL_EST.get(e, "#7B2D8E"), lw=1.1, ls="--", zorder=2)
        axv.text((a + b) / 2, axv.get_ylim()[1], e, ha="center", va="top", fontsize=8,
                 fontweight="bold", color=COL_EST.get(e, "#7B2D8E"), zorder=5)
    axv.plot(lv, dv, "-", color="#1a1a1a", lw=0.85, zorder=3)
    axv.axhline(UMBRAL, color=ROJO, ls="--", lw=1.2, zorder=4)
    axv.fill_between(lv, UMBRAL, dv, where=(dv > UMBRAL), color=ROJO, alpha=0.25, zorder=2)
    axv.set_ylabel("DI del pozo vecino", fontsize=9)
    axv.set_xlabel("Profundidad a lo largo del pozo (m)", fontsize=10)
    axv.grid(alpha=0.25, lw=0.6)
    axv.text(0.005, 0.95, f"{vn} — a {VEC['distancia_collar_m']:.1f} m de collar del anterior. "
             f"AQUÍ la malla sí dibuja {', '.join(VEC['estructuras'])}.",
             transform=axv.transAxes, va="top", fontsize=8.2, fontweight="bold", color="#444444")
    axes[2].set_xlabel("")

h = ([Patch(facecolor=COL_LITO[l], alpha=0.45, label=f"Litología: {l}")
      for l in sorted({l for _, _, l in tr_lito}) if l in COL_LITO] +
     [Patch(facecolor=COL_EST[e], alpha=0.55, hatch="//", edgecolor=COL_EST[e],
            label=f"Estructura: {e}") for e in ests] +
     [Patch(facecolor=COL_EST.get(e, "#7B2D8E"), alpha=0.55, hatch="//",
            edgecolor=COL_EST.get(e, "#7B2D8E"), label=f"Estructura (pozo vecino): {e}")
      for e in sorted({c for _, _, c in tr_est_vec})] +
     [plt.Line2D([], [], color=ROJO, ls="--", label=f"Umbral DI = {UMBRAL:g}")] +
     ([plt.Line2D([], [], marker="v", ls="", color=ROJO, label="Pico de DI dentro de zona estructural"),
       plt.Line2D([], [], marker="v", ls="", color="#333333", label="Pico de DI fuera de zona estructural")]
      if tr_est else
      [plt.Line2D([], [], marker="v", ls="", color="#333333", label="Pico de DI (ninguno cae en zona estructural)")]))
axes[0].legend(handles=h, loc="upper left", bbox_to_anchor=(0, -0.08), ncol=4,
               fontsize=7.6, framealpha=0.92)

ctx = DAT["contexto_caseron"]
if tr_est:
    cuerpo = (f"El modelo asigna estructura a {DAT['largo_con_estructura_m']:.1f} m "
              f"({DAT['pct_largo_con_estructura']:.1f}% del tiro); "
              f"{DAT['picos_dentro_de_zona_estructural']} de los {DAT['n_picos']} picos caen "
              "dentro de esas zonas. Las franjas rayadas son zonas estructurales de la malla.")
else:
    vec = ctx["pozo_con_estructura_mas_cercano"]
    cuerpo = ("El modelo geológico no asigna NINGUNA estructura a este tiro: sus 35,93 m son "
              f"Kpcli continuo. En el mismo caserón, {ctx['pozos_con_estructura']} de los "
              f"{ctx['n_pozos']} pozos ({ctx['pct_con_estructura']:.1f}%) sí cruzan estructura "
              + (f"—el más cercano, {vec['pozo']}, a {vec['distancia_collar_m']:.1f} m de collar "
                 f"({', '.join(vec['estructuras'])})—. " if vec else "— ") +
              f"El contraste es el resultado: el MWD registra {DAT['n_picos']} picos de "
              "discontinuidad donde la malla interpolada no dibuja nada.")
fig.text(0.5, -0.025,
         f"Pozo de {DAT['largo_m']:.1f} m, {DAT['n_puntos']} registros, DI máximo {DAT['di_max']:.2f}. "
         f"{n_sobre} muestras superan el umbral ({DAT['pct_sobre_umbral']:.1f}%), agrupadas en "
         f"{DAT['n_picos']} picos. " + cuerpo + " Elaboración propia.",
         ha="center", fontsize=8.2, color="#555555", wrap=True)
fig.tight_layout(rect=[0, 0.02, 1, 1])
fig.savefig("/home/user/Proyecto2/figuras/F_DI_vs_estructura.png", dpi=300,
            bbox_inches="tight", facecolor="white")
print("figura OK", flush=True)
