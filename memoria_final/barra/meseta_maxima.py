"""Meseta estable más alta de PP y de RP sostenida al menos 5 m, y registros
sobre cada tope candidato. Meseta: ventana de 5 m de registros de perforación
(sin emboquillado, cambio de barra ni PR = 0) con el 90% dentro de ±banda de
su mediana (PP ±15 bar, la del emboquillado; RP ±10 bar).
Uso: python3 meseta_maxima.py salida.json"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw
import cargar_caserones as cc
cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
for c in cc.CASERONES: cc.cargar_caseron(c, verbose=False)
gw.emboquillado_modo = "meseta"; gw.apply_inicio_meseta()
TRAMO = 5.0
VARS = {"PP": ("pp", 15.0), "RP": ("pr", 10.0)}
mes = {s: [] for s in VARS}; todo = {s: [] for s in VARS}
for wn, w in gw.wells.items():
    ps = sorted(w.points, key=lambda p: p.largo)
    cb = set(gw.detectar_cambio_de_barra(ps))
    sel = [p for i, p in enumerate(ps) if not p.emboquillado and i not in cb and p.vel > 0]
    if len(sel) < 50: continue
    lar = np.array([p.largo for p in sel])
    for s, (a, banda) in VARS.items():
        x = np.array([getattr(p, a) for p in sel], float); todo[s].append(x)
        mejor = None
        for i in range(0, len(sel), 10):
            j = np.searchsorted(lar, lar[i] + TRAMO)
            if j >= len(sel) or j - i < 150: continue      # 5 m completos, sin huecos grandes
            seg = x[i:j]; med = float(np.median(seg))
            if np.mean(np.abs(seg - med) <= banda) >= 0.90 and (mejor is None or med > mejor[0]):
                mejor = (med, float(lar[i]))
        if mejor: mes[s].append((mejor[0], wn, mejor[1]))
R = {}
for s in VARS:
    x = np.concatenate(todo[s]); m = sorted(mes[s], reverse=True); v = np.array([t[0] for t in m])
    topes = (220, 225, 228, 230, 232, 235) if s == "PP" else (60, 65, 70, 75, 80, 90, 100)
    R[s] = {"registros": int(x.size), "pozos_con_meseta_5m": len(m),
            "meseta_mas_alta": [{"mediana_bar": round(a, 1), "pozo": b, "desde_m": round(c, 2)} for a, b, c in m[:8]],
            "meseta_mas_alta_por_pozo": {"max": round(float(v.max()), 1), "p_mediana": round(float(np.median(v)), 1)},
            "pozos_con_meseta_sobre": {str(t): int((v > t).sum()) for t in topes},
            "registros_sobre": {str(t): [int((x > t).sum()), round(100 * float((x > t).mean()), 2)] for t in topes},
            "maximo_registrado": round(float(x.max()), 1)}
json.dump(R, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
print(json.dumps(R, ensure_ascii=False, indent=1))
