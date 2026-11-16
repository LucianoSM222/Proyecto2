"""Validación del largo de barra y de los límites de limpieza (2026-11-11).

1. Espaciamiento de muestreo: Δlargo entre registros consecutivos.
2. Periodicidad de las detenciones (PR = 0) SIN suponer el largo de barra:
   a) diferencias entre centros de detenciones del mismo pozo (todas las
      parejas a menos de 4 m): si hay barra, picos en L y 2L;
   b) barrido de L entre 1,20 y 2,40 m: cuántas detenciones alinea la mejor
      grilla φ + k·L de cada pozo (±6 cm, ≥ 3 uniones), contra las mismas
      detenciones recolocadas al azar;
   c) L por pozo: regresión centro = a + L·k sobre las detenciones alineadas.
3. Transitorio alrededor del cambio de barra: cada variable en las muestras
   1..8 antes y después de la detención, relativa a la mediana de las
   muestras 10..20 a cada lado; control: mismas posiciones relativas en
   puntos al azar sin detención.
4. Cuántos registros saca cada límite operacional propuesto.
Uso: python3 validacion_barra.py salida.json
"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw
import cargar_caserones as cc

OUT = sys.argv[1]
TOL, MIN_U, EMB = 0.06, 3, 2.0
cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
for c in cc.CASERONES: cc.cargar_caseron(c, verbose=False)
gw.set_param("barra.margen_antes", 0); gw.set_param("barra.margen_despues", 0)   # detenciones sin margen: el margen es lo que se mide
R = {}
rng = np.random.default_rng(42)

POZOS = []
for wn, w in gw.wells.items():
    ps = sorted(w.points, key=lambda p: p.largo)
    if len(ps) < 50: continue
    lar = np.array([p.largo for p in ps], float)
    v = np.array([p.vel for p in ps], float)
    rachas, i, n = [], 0, len(ps)
    while i < n:
        if v[i] != 0: i += 1; continue
        j = i
        while j + 1 < n and v[j + 1] == 0: j += 1
        rachas.append((i, j, (lar[i] + lar[j]) / 2)); i = j + 1
    POZOS.append((wn, ps, lar, rachas))

# ── 1. espaciamiento ────────────────────────────────────────────────────────
d = np.concatenate([np.diff(lar) for _, _, lar, _ in POZOS])
d = d[d > 0]
med = float(np.median(d))
R["espaciamiento"] = {"n_pasos": int(d.size), "mediana_cm": round(100 * med, 3),
                      "media_cm": round(100 * float(d.mean()), 3),
                      "pct_entre_1_9_y_2_3_cm": round(100 * float(((d >= .019) & (d <= .023)).mean()), 2),
                      "1_5_veces_mediana_cm": round(150 * med, 3),
                      "umbral_vigente_cm": 2.95, "umbral_sobre_mediana": round(0.0295 / med, 3),
                      "pct_pasos_sobre_2_95_cm": round(100 * float((d > .0295).mean()), 3),
                      "histograma_cm": {f"{lo:.1f}-{lo + .1:.1f}": int(((d >= lo / 100) & (d < (lo + .1) / 100)).sum())
                                        for lo in np.arange(1.5, 3.5, 0.1)}}
print("espaciamiento", R["espaciamiento"], flush=True)

# ── 2. periodicidad ─────────────────────────────────────────────────────────
centros = [(np.array([c for (i, j, c) in r if lar[j] >= EMB]), lar[-1]) for _, _, lar, r in POZOS]
dif = []
for x, _ in centros:
    if x.size < 2: continue
    D = np.abs(x[:, None] - x[None, :])[np.triu_indices(x.size, 1)]
    dif.append(D[D < 4.0])
dif = np.concatenate(dif)
bins = np.arange(0.5, 4.0 + 1e-9, 0.01)
h, _ = np.histogram(dif, bins)
top = np.argsort(h)[::-1][:8]
R["diferencias_entre_detenciones"] = {
    "n_parejas": int(dif.size),
    "picos_bin_1cm": [{"desde_m": round(float(bins[k]), 2), "n": int(h[k])} for k in sorted(top)],
    "mejor_pico_1_2_a_2_4_m": None}
sel = (bins[:-1] >= 1.2) & (bins[:-1] < 2.4)
k = np.argmax(np.where(sel, h, -1))
# centroide fino del pico ±3 cm
m = (dif >= bins[k] - 0.03) & (dif < bins[k] + 0.04)
R["diferencias_entre_detenciones"]["mejor_pico_1_2_a_2_4_m"] = {
    "bin_m": round(float(bins[k]), 2), "n": int(h[k]), "media_fina_m": round(float(dif[m].mean()), 4)}
sel2 = (bins[:-1] >= 3.0) & (bins[:-1] < 4.0)
k2 = np.argmax(np.where(sel2, h, -1)); m2 = (dif >= bins[k2] - 0.03) & (dif < bins[k2] + 0.04)
R["diferencias_entre_detenciones"]["segundo_armonico"] = {
    "bin_m": round(float(bins[k2]), 2), "n": int(h[k2]), "media_fina_m": round(float(dif[m2].mean()), 4),
    "mitad_m": round(float(dif[m2].mean()) / 2, 4)}
R["diferencias_entre_detenciones"]["histograma_1_5_a_2_1_m"] = {
    f"{bins[i]:.2f}": int(h[i]) for i in range(len(h)) if 1.5 <= bins[i] < 2.1}
print("diferencias", {k_: v for k_, v in R["diferencias_entre_detenciones"].items() if "histograma" not in k_}, flush=True)


def alineados(x, L):
    if x.size < MIN_U: return 0
    mejor = 0
    for phi in np.mod(x, L):
        en = np.abs(((x - phi + L / 2) % L) - L / 2) <= TOL
        s = int(en.sum())
        if s > mejor and np.unique(np.round((x[en] - x[en][0]) / L)).size >= MIN_U: mejor = s
    return mejor


Ls = np.round(np.arange(1.20, 2.4001, 0.004), 3)
score = np.array([sum(alineados(x, L) for x, _ in centros) for L in Ls])
azar = []
for rep in range(5):
    xs = [(np.sort(rng.uniform(EMB, max(fin, EMB), x.size)), fin) for x, fin in centros]
    azar.append([sum(alineados(x, L) for x, _ in xs) for L in Ls[::10]])
R["barrido_L"] = {"L_m": Ls.tolist(), "alineadas": score.tolist(),
                  "mejor_L_m": float(Ls[score.argmax()]), "mejor_alineadas": int(score.max()),
                  "alineadas_en_1_756": int(score[np.argmin(np.abs(Ls - 1.756))]),
                  "detenciones_fuera_emboquillado": int(sum(x.size for x, _ in centros)),
                  "azar_media": round(float(np.mean(azar)), 1), "azar_max": int(np.max(azar))}
print("barrido", {k_: v for k_, v in R["barrido_L"].items() if k_ not in ("L_m", "alineadas")}, flush=True)

Lest = []
for x, _ in centros:
    if x.size < 4: continue
    L = 1.756; best, fase = 0, None
    for phi in np.mod(x, L):
        en = np.abs(((x - phi + L / 2) % L) - L / 2) <= TOL
        if en.sum() > best: best, fase = int(en.sum()), phi
    en = np.abs(((x - fase + L / 2) % L) - L / 2) <= TOL
    xe = x[en]; kk = np.round((xe - xe[0]) / L)
    if np.unique(kk).size >= 4:
        Lest.append(float(np.polyfit(kk, xe, 1)[0]))
Lest = np.array(Lest)
R["L_por_pozo"] = {"n_pozos": int(Lest.size), "mediana_m": round(float(np.median(Lest)), 4),
                   "media_m": round(float(Lest.mean()), 4), "sd_m": round(float(Lest.std()), 4),
                   "p25_m": round(float(np.percentile(Lest, 25)), 4), "p75_m": round(float(np.percentile(Lest, 75)), 4)}
print("L por pozo", R["L_por_pozo"], flush=True)

# ── 3. transitorio alrededor del cambio de barra ────────────────────────────
VARS = [("PR", "vel"), ("PP", "pp"), ("FP", "pa"), ("DP", "pd"), ("RP", "pr"), ("FLP", "pf")]
OFF = list(range(1, 9))


def perfil(eventos):
    """eventos: lista de (ps, i0, j0). Devuelve mediana de valor/base y % |dev|>10%."""
    acc = {s: {f"-{o}": [] for o in OFF} | {f"+{o}": [] for o in OFF} for s, _ in VARS}
    for ps, i0, j0 in eventos:
        n = len(ps)
        if i0 - 20 < 0 or j0 + 20 >= n: continue
        base_idx = list(range(i0 - 20, i0 - 9)) + list(range(j0 + 10, j0 + 21))
        for s, a in VARS:
            b = np.median([getattr(ps[t], a) for t in base_idx])
            if not b or not np.isfinite(b) or b <= 0: continue
            for o in OFF:
                acc[s][f"-{o}"].append(getattr(ps[i0 - o], a) / b)
                acc[s][f"+{o}"].append(getattr(ps[j0 + o], a) / b)
    out = {}
    for s, _ in VARS:
        out[s] = {k_: {"mediana": round(float(np.median(v)), 3),
                       "pct_desvio_10": round(100 * float(np.mean(np.abs(np.array(v) - 1) > 0.10)), 1)}
                  for k_, v in acc[s].items() if v}
    return out


ev, ctl = [], []
for wn, ps, lar, r in POZOS:
    idx = set(gw.detectar_cambio_de_barra(ps))
    for (i, j, c) in r:
        if i in idx: ev.append((ps, i, j))
    cand = np.where(np.array([p.vel for p in ps]) > 0)[0]
    cand = cand[(cand > 30) & (cand < len(ps) - 30)]
    if cand.size:
        for i in rng.choice(cand, min(3, cand.size), replace=False): ctl.append((ps, int(i), int(i)))
R["transitorio"] = {"n_eventos": len(ev), "n_control": len(ctl),
                    "largo_racha_mediana": float(np.median([j - i + 1 for _, i, j in ev])),
                    "barra": perfil(ev), "control": perfil(ctl)}
print("transitorio listo", len(ev), flush=True)

# ── 4. límites operacionales propuestos ────────────────────────────────────
# Base: lo que queda tras emboquillado por meseta, cambio de barra (sin margen)
# y continuidad, SIN regulación y SIN ningún límite de rango.
gw.set_param("barra.margen_antes", 0); gw.set_param("barra.margen_despues", 0)
gw.emboquillado_modo = "meseta"; gw.apply_inicio_meseta()
pts = list(gw.all_points())
ent = []
for w in gw.wells.values():
    ps = sorted(w.points, key=lambda p: p.largo)
    cb = set(gw.detectar_cambio_de_barra(ps))
    co = set(id(w.points[i]) for i in gw.puntos_tras_salto(w))
    ent += [p for i, p in enumerate(ps) if not p.emboquillado and i not in cb and id(p) not in co]
LIM = {"PR": ("vel", 0.1, 1.5), "PP": ("pp", 90, 225), "FP": ("pa", 20, 150),
       "DP": ("pd", 25, 150), "RP": ("pr", 30, 60), "FLP": ("pf", 2, 10)}
fuera = {s: np.array([not (lo <= getattr(p, a) <= hi) for p in ent]) for s, (a, lo, hi) in LIM.items()}
union = np.any(np.vstack(list(fuera.values())), axis=0)
R["limites"] = {"entrenables_antes": len(ent),
                "por_variable": {s: {"lo": LIM[s][1], "hi": LIM[s][2], "fuera": int(f.sum()),
                                     "pct": round(100 * float(f.mean()), 2),
                                     "bajo": int(sum(getattr(p, LIM[s][0]) < LIM[s][1] for p in ent)),
                                     "sobre": int(sum(getattr(p, LIM[s][0]) > LIM[s][2] for p in ent))}
                                 for s, f in fuera.items()},
                "solo_esa_variable": {s: int((f & ~np.any(np.vstack([g for t, g in fuera.items() if t != s]), axis=0)).sum())
                                      for s, f in fuera.items()},
                "PP_90_230_antes": int(sum(not (90 <= p.pp <= 230) for p in ent)),
                "union_fuera": int(union.sum()), "union_pct": round(100 * float(union.mean()), 2),
                "entrenables_despues": int((~union).sum()),
                "PR_cero_entrenables": int(sum(p.vel == 0 for p in ent)),
                "PR_sobre_10_total": int(sum(p.vel > 10 for p in pts)),
                "PR_sobre_10_en_serie_DI": int(sum(p.vel > 10 for p in pts if not p.emboquillado))}
print("limites", json.dumps(R["limites"], ensure_ascii=False), flush=True)
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1)
