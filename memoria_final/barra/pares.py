import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np, geomech_wizard as gw, cargar_caserones as cc
cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
for c in cc.CASERONES: cc.cargar_caseron(c, verbose=False)
ORD = {wn: sorted(w.points, key=lambda p: p.largo) for wn, w in gw.wells.items()}
M = {}
for u in (0.10, 0.15, 0.20, 0.25):
    M[str(u)] = {wn: [round(ps[i].largo, 3) for i in gw.detectar_percusion_de_empate(ps, u)] for wn, ps in ORD.items()}
M["lmax"] = {wn: ps[-1].largo for wn, ps in ORD.items() if ps}
M["pp"] = {wn: [[round(p.largo, 3), p.pp] for p in ps] for wn, ps in ORD.items()}
json.dump(M, open(sys.argv[1], "w"))
L = gw.LARGO_BARRA_M
for u in ("0.25", "0.15"):
    d = []
    for x in M[u].values():
        x = np.array(x)
        if x.size < 2: continue
        dd = x[None, :] - x[:, None]; d.extend(dd[(dd > 0.05) & (dd < 6)].tolist())
    h, e = np.histogram(d, bins=np.arange(0.05, 6.0, 0.05))
    top = sorted(zip(h, e[:-1]), reverse=True)[:8]
    print(u, "pares", len(d), "picos:", [(round(b + .025, 3), c) for c, b in top])
    for k in (1, 2, 3):
        sel = np.array(d); w = sel[(sel > k * L - 0.30) & (sel < k * L + 0.30)]
        hh, ee = np.histogram(w, bins=np.arange(k * L - 0.30, k * L + 0.31, 0.02))
        print(f"   cerca de {k}L: moda {ee[np.argmax(hh)] + .01:.3f}  n±30cm={w.size}  n±10cm={int(np.sum(abs(w - k*L) <= 0.10))}")
