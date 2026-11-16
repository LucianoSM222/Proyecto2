"""Tabla de filtros por etapa con conteos EXCLUSIVOS: cada registro excluido se
asigna a un solo motivo, en el orden emboquillado, cambio de barra (detención
y margen), equipo sin perforar, continuidad, sin DI calculable (pozo con serie
más corta que la ventana), y luego —solo entrenamiento— roca fuera de rango.
Uso: python3 resumen_filtros.py salida.json"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
from collections import Counter
import numpy as np
import geomech_wizard as gw
import cargar_caserones as cc
cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
for c in cc.CASERONES: cc.cargar_caseron(c, verbose=False)
res = gw.aplicar_limpieza_estandar()
lim = gw.limites_equipo(); tope = gw.get_param("limites.pr_max_di"); W = gw.di_config["window"]
C = Counter(); eq = Counter(); roca = Counter(); n = 0; cortos = []
for wn, w in gw.wells.items():
    ps = sorted(w.points, key=lambda p: p.largo); n += len(ps)
    gw.set_param("barra.margen_despues", 0); det = set(gw.detectar_cambio_de_barra(ps))
    gw.reset_param("barra.margen_despues"); cb = set(gw.detectar_cambio_de_barra(ps))
    co = {id(w.points[i]) for i in gw.puntos_tras_salto(w)}
    m = gw.mascara_serie_di(w.points); corto = int(m.sum()) < W
    if corto: cortos.append(wn)
    for i, p in enumerate(ps):
        if p.emboquillado: C["emboquillado"] += 1; continue
        if i in det: C["barra_detencion"] += 1; continue
        if i in cb: C["barra_margen"] += 1; continue
        e = ("PR = 0" if p.vel <= 0 else "PR > 10" if p.vel > tope else "PP < 90" if p.pp < lim["PP"][1]
             else "FP < 20" if p.pa < lim["FP"][1] else "FLP > 10" if p.pf > lim["FLP"][2] else None)
        if e: C["equipo"] += 1; eq[e] += 1; continue
        if id(p) in co: C["continuidad"] += 1; continue
        if corto: C["sin_di"] += 1; continue
        C["serie_di"] += 1
        if not p.entrenable:
            C["roca"] += 1
            for s in ("PR", "PP", "FP", "DP", "RP", "FLP"):
                a, lo, hi = lim[s]
                if not (lo <= getattr(p, a) <= hi): roca[s + (" bajo" if getattr(p, a) < lo else " sobre")] += 1
        else: C["entrenable"] += 1
cortes = [c for c, mo in gw.inicio_por_pozo.values() if mo == "meseta"]
R = {"total": n, "conteo": dict(C), "equipo_detalle": dict(eq), "roca_detalle": dict(roca), "pozos_cortos": cortos,
     "emboquillado": {"corte_mediano_m": float(np.median(cortes)), "corte_medio_m": float(np.mean(cortes)),
                      "corte_p_max_m": float(np.max(cortes)), "pozos_meseta": len(cortes),
                      "pozos_respaldo": len(gw.inicio_por_pozo) - len(cortes),
                      "histograma_m": {f"{lo:.1f}-{lo+.5:.1f}": int(sum(lo <= c < lo + .5 for c in cortes)) for lo in np.arange(0, 6, .5)}},
     "limites": {s: [lo, hi] for s, (a, lo, hi) in lim.items()}, "entrenables_app": sum(1 for p in gw.all_points() if p.entrenable)}
json.dump(R, open(sys.argv[1], "w"), ensure_ascii=False, indent=1); print(json.dumps(R, ensure_ascii=False))
