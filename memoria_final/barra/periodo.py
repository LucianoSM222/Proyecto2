"""¿Las caídas de percusión de empate se repiten cada largo de barra (1,756 m)?"""
import sys, json, time
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw, cargar_caserones as cc
OUT = sys.argv[1]; t0 = time.time()
L = gw.LARGO_BARRA_M
cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
for c in cc.CASERONES: cc.cargar_caseron(c, verbose=False)
ORD = {wn: sorted(w.points, key=lambda p: p.largo) for wn, w in gw.wells.items()}
print("carga", round(time.time() - t0), "L =", L, flush=True)
R = {"L": L}
MARC = {u: {wn: np.array([ps[i].largo for i in gw.detectar_percusion_de_empate(ps, u)]) for wn, ps in ORD.items()}
        for u in (0.10, 0.15, 0.20, 0.25)}
LMAX = {wn: ps[-1].largo for wn, ps in ORD.items() if ps}


def coherencia(marcas, Lp, min_n=4):
    """Largo medio del vector resultante de las fases 2π·x/L, cada pozo con su propia
    fase, ponderado por n. 1 = todas las marcas sobre la rejilla."""
    num = den = azar = 0.0
    for x in marcas.values():
        if x.size < min_n: continue
        num += abs(np.exp(2j * np.pi * x / Lp).sum()); den += x.size; azar += np.sqrt(x.size)
    return (num / den, (np.sqrt(np.pi) / 2) * azar / den) if den else (None, None)


Ls = np.round(np.arange(1.60, 1.95, 0.001), 3)
R["barrido"] = {"L": Ls.tolist()}
for u in (0.25, 0.15):
    c = [coherencia(MARC[u], x)[0] for x in Ls]
    R["barrido"][str(u)] = c
    k = int(np.argmax(c)); i0 = int(np.argmin(abs(Ls - L)))
    print(f"u={u}: mejor L={Ls[k]} coh={c[k]:.3f} | L={L}: {c[i0]:.3f} | azar {coherencia(MARC[u], L)[1]:.3f}", flush=True)


def fase(x):
    return (np.angle(np.exp(2j * np.pi * x / L).sum()) / (2 * np.pi) * L) % L


def dist(x, phi):
    d = (x - phi) % L
    return np.minimum(d, L - d)


for u in (0.25, 0.15, 0.10):
    ds = []
    for wn, x in MARC[u].items():
        ref = MARC[0.25][wn]
        if ref.size < 4 or x.size == 0: continue
        ds.append(dist(x, fase(ref)))
    d = np.concatenate(ds)
    R[f"dist_{u}"] = {"n": int(d.size), "pct_10cm": round(100 * float(np.mean(d <= 0.10)), 1),
                      "pct_5cm": round(100 * float(np.mean(d <= 0.05)), 1),
                      "azar_10cm": round(100 * 0.20 / L, 1), "azar_5cm": round(100 * 0.10 / L, 1),
                      "hist": np.histogram(d, bins=np.arange(0, L / 2 + 0.02, 0.02))[0].tolist()}
    print(u, {k: v for k, v in R[f"dist_{u}"].items() if k != "hist"}, flush=True)
R["teorico_uniones"] = int(sum(np.floor(l / L) for l in LMAX.values()))
R["n_marcas"] = {str(u): int(sum(v.size for v in MARC[u].values())) for u in MARC}
R["pozos_con_4_marcas"] = int(sum(1 for x in MARC[0.25].values() if x.size >= 4))
print("teórico", R["teorico_uniones"], R["n_marcas"], "pozos≥4", R["pozos_con_4_marcas"], flush=True)
json.dump(R, open(OUT, "w"), indent=1, default=float)
