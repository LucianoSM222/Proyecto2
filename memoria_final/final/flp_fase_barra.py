"""¿El DI se concentra en las uniones de barra? Para cada registro de la serie
del DI se mide su posición dentro de la barra (distancia desde el último cambio
de barra, 0-1,756 m) y se promedia, por tramo de 10 cm: % de DI > 1 y aporte
de cada presión a DI² (peso · z²). También la tendencia de la FLP con la
profundidad y el salto en cada unión.
Uso: python3 flp_fase_barra.py proyecto_final.gwz salida.json"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw, cargar_caserones as cc
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
gw.load_project(sys.argv[1])
W = gw.di_config["weights"]; s = sum(W.values()); PAR = tuple(W)
L = gw.LARGO_BARRA_M; bins = np.arange(0, L + 1e-9, 0.1)
fase_all, di_all, ap_all = [], [], {k: [] for k in PAR}
pend, saltos, flp_ini, flp_fin = [], [], [], []
for wn, w in gw.wells.items():
    ps = sorted(w.points, key=lambda p: p.largo)
    gw.set_param("barra.margen_despues", 0); det = sorted(gw.detectar_cambio_de_barra(ps)); gw.reset_param("barra.margen_despues")
    if len(det) < 3: continue
    lar = np.array([p.largo for p in ps]); uniones = []
    for i in det:
        if not uniones or lar[i] - uniones[-1] > 0.5: uniones.append(lar[i])
    uniones = np.array(uniones)
    z2 = gw._z2_por_param(ps, gw.di_config["window"], PAR)
    if z2 is None: continue
    di = np.sqrt(sum(W[k] / s * z2[k] for k in PAR))
    k_ = np.searchsorted(uniones, lar, side="right") - 1
    ok = (k_ >= 0) & np.isfinite(di)
    fase = lar - uniones[np.clip(k_, 0, None)]
    ok &= fase < L
    fase_all.append(fase[ok]); di_all.append(di[ok])
    for k in PAR: ap_all[k].append((W[k] / s * z2[k])[ok])
    # FLP: nivel medio por barra y salto en cada unión
    pf = np.array([p.pf for p in ps]); v = np.array([p.vel for p in ps])
    niveles = []
    for a, b in zip(uniones[:-1], uniones[1:]):
        m = (lar > a + 0.1) & (lar < b - 0.05) & (v > 0)
        if m.sum() > 20:
            niveles.append(np.median(pf[m]))
            seg = pf[m]; flp_ini.append(np.median(seg[:10])); flp_fin.append(np.median(seg[-10:]))
    if len(niveles) >= 3:
        pend.append(np.polyfit(np.arange(len(niveles)) * L, niveles, 1)[0])
fa = np.concatenate(fase_all); da = np.concatenate(di_all)
idx = np.digitize(fa, bins) - 1
R = {"n": int(fa.size), "bins_m": bins[:-1].round(2).tolist(),
     "pct_di_sobre_1": [round(100 * float((da[idx == i] > 1).mean()), 2) for i in range(len(bins) - 1)],
     "aporte_medio": {k: [round(float(np.concatenate(ap_all[k])[idx == i].mean()), 3) for i in range(len(bins) - 1)] for k in PAR},
     "pct_global_di_sobre_1": round(100 * float((da > 1).mean()), 2),
     "flp_pendiente_bar_por_m": {"mediana": round(float(np.median(pend)), 3), "p25": round(float(np.percentile(pend, 25)), 3),
                                  "p75": round(float(np.percentile(pend, 75)), 3), "barrenos": len(pend)},
     "flp_dentro_de_barra": {"inicio_mediana": round(float(np.median(flp_ini)), 2), "fin_mediana": round(float(np.median(flp_fin)), 2),
                              "subida_mediana": round(float(np.median(np.array(flp_fin) - np.array(flp_ini))), 2)}}
json.dump(R, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in R.items() if k not in ("aporte_medio",)}, ensure_ascii=False))
for k in PAR: print(k, R["aporte_medio"][k])
