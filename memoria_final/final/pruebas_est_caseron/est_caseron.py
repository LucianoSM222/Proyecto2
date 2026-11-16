"""PRUEBA: DI con la varianza móvil estandarizada contra el CASERÓN en vez del
barreno. Parchea en memoria _z2_por_param y di_profile_serie; no toca el código."""
import numpy as np
PAR5 = ("pp", "pr", "pd", "pf", "pa")
MV, STATS = {}, {}

def preparar(gw, caseron_de):
    """Varianza móvil de cada registro (sobre la serie del DI de su barreno) y
    media/desviación por caserón y presión."""
    MV.clear(); STATS.clear(); acum = {}
    _orig = getattr(gw, "_di_profile_serie_orig", gw.di_profile_serie)
    for w in gw.wells.values():
        ps = w.points; m = gw.mascara_serie_di(ps)
        if int(m.sum()) < gw.di_config["window"]: continue
        sub = [p for p, k in zip(ps, m) if k]; cas = caseron_de(w)
        for k in PAR5:
            mv = gw._moving_variance(np.array([getattr(p, k) for p in sub], float), gw.di_config["window"] // 2)
            for p, v in zip(sub, mv): MV.setdefault(id(p), {})[k] = v
            acum.setdefault((cas, k), []).append(mv)
        for p in sub: MV[id(p)]["cas"] = cas
    for (cas, k), lst in acum.items():
        a = np.concatenate(lst); STATS[(cas, k)] = (float(a.mean()), float(a.std()) or 1e-9)

def z2(points, params):
    out = {k: np.full(len(points), np.nan) for k in params}
    for i, p in enumerate(points):
        r = MV.get(id(p))
        if r is None: continue
        for k in params:
            mu, sd = STATS[(r["cas"], k)]; out[k][i] = ((r[k] - mu) / sd) ** 2
    return out

def parchear(gw):
    if not hasattr(gw, "_di_profile_serie_orig"):
        gw._di_profile_serie_orig = gw.di_profile_serie; gw._z2_orig = gw._z2_por_param
    def _z2_por_param(points, window, params):
        o = z2(points, params)
        return o if np.isfinite(o[params[0]]).sum() >= window else None
    def di_profile_serie(points, window, params=None, weights=None):
        params = params or gw.di_config["params"]; weights = weights or gw.di_config["weights"]
        tw = sum(weights.get(k, 0) for k in params) or 1.0
        o = z2(points, params)
        if np.isfinite(o[params[0]]).sum() < window: return None
        return np.sqrt(sum(weights.get(k, 0) / tw * o[k] for k in params))
    gw._z2_por_param = _z2_por_param; gw.di_profile_serie = di_profile_serie
