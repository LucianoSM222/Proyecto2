"""El DI se calcula sobre la serie DEPURADA (decisión del autor, 2026-10-22).

Las muestras del emboquillado y las de percusión de empate SALEN de la serie
antes de la varianza móvil y de la estandarización por pozo: no son roca, y
dentro de la ventana inflaban la varianza de la PP. Su DI queda en None.
El rango de PP y la continuidad siguen siendo solo filtros del entrenamiento.
"""
import numpy as np
import geomech_wizard as gw


def _pozo():
    rng = np.random.default_rng(3)
    pts = []
    for i in range(300):                      # 6 m a 2 cm
        pp = 180.0 + rng.normal(0, 2)
        if i in (150, 238):                   # dos empates: cae y se recupera
            pp = 100.0
        pts.append(gw.MWDPoint(largo=i * 0.02, vel=1.0, pp=pp, pa=60.0,
                               pd=100.0 + rng.normal(0, 3), pr=50.0 + rng.normal(0, 1),
                               pf=8.0 + rng.normal(0, 0.2), se=300.0, t=0.0))
    return gw.Well(well_name="W", plan_id="CAS_PR01_TH_W", hole_id="W", points=pts)


def test_di_sobre_serie_depurada():
    gw.wells.clear(); gw.clean_filters.clear(); gw.seed_param_registry()
    w = _pozo(); gw.wells["W"] = w
    try:
        gw.apply_inicio_filter(2.0)           # estado propio: otro test puede dejar otro corte
        gw.activar_di(gw.DI_VARIANTE_CONVENCION)
        gw.aplicar_limpieza_estandar()
        gw.compute_di()
        emb = [p for p in w.points if p.largo < gw.inicio_cut_m]
        assert emb and all(p.di is None for p in emb), "el emboquillado no tiene DI"
        assert w.points[150].di is None and w.points[238].di is None, "el empate no tiene DI"
        serie = [p for i, p in enumerate(w.points)
                 if p.largo >= gw.inicio_cut_m and i not in (150, 238)]
        esperado = gw.di_profile(serie, gw.di_config["window"], gw.di_config["params"],
                                 gw.di_config["weights"])
        obtenido = np.array([p.di for p in serie])
        assert np.allclose(obtenido, esperado), "el DI es el de la serie depurada"
        # la calibración usa el mismo z²: misma serie, mismos índices
        z2 = gw._z2_por_param(w.points, gw.di_config["window"], gw.di_config["params"])
        di_z2 = gw._di_desde_z2(z2, gw.di_config["weights"])
        assert np.isnan(di_z2[150]) and np.isnan(di_z2[0])
        assert np.allclose(di_z2[[i for i, p in enumerate(w.points) if p.di is not None]], obtenido)
    finally:
        gw.wells.clear(); gw.clean_filters.clear()
