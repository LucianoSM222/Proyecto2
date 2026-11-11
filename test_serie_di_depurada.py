"""El DI se calcula sobre la serie DEPURADA (decisión del autor, 2026-10-22).

Las muestras del emboquillado SALEN de la serie antes de la varianza móvil y
de la estandarización por pozo: no son roca, y dentro de la ventana inflaban la
varianza de la PP. Su DI queda en None. La regulación automática de la
percusión dejó de ser parte de la limpieza (2026-11-11): sus caídas QUEDAN en
la serie.
El rango de PP y la continuidad siguen siendo solo filtros del entrenamiento.
"""
import numpy as np
import geomech_wizard as gw


def _pozo():
    rng = np.random.default_rng(3)
    pts = []
    for i in range(300):                      # 6 m a 2 cm
        pp = (95.0 if i < 50 else 180.0) + rng.normal(0, 2)   # emboquillado: 1 m a PP baja
        if i in (150, 238):                   # dos caídas de regulación: cae y se recupera
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
        emb = [p for p in w.points if p.emboquillado]
        assert gw.inicio_por_pozo["W"][1] == "meseta", "el emboquillado sale de la meseta de PP"
        assert emb and all(p.di is None for p in emb), "el emboquillado no tiene DI"
        assert w.points[150].di is not None and w.points[238].di is not None, \
            "la regulación ya no sale de la serie del DI"
        serie = [p for p in w.points if not p.emboquillado]
        esperado = gw.di_profile(serie, gw.di_config["window"], gw.di_config["params"],
                                 gw.di_config["weights"])
        obtenido = np.array([p.di for p in serie])
        assert np.allclose(obtenido, esperado), "el DI es el de la serie depurada"
        # la calibración usa el mismo z²: misma serie, mismos índices
        z2 = gw._z2_por_param(w.points, gw.di_config["window"], gw.di_config["params"])
        di_z2 = gw._di_desde_z2(z2, gw.di_config["weights"])
        assert np.isnan(di_z2[0]) and not np.isnan(di_z2[150])
        assert np.allclose(di_z2[[i for i, p in enumerate(w.points) if p.di is not None]], obtenido)
    finally:
        gw.wells.clear(); gw.clean_filters.clear()


def test_varianza_movil_con_serie_del_largo_de_la_ventana():
    """Una serie de exactamente `window` registros (14) es más corta que la
    ventana centrada (15): la varianza móvil debe conservar el largo de la
    serie. Antes devolvía 15 valores y `_z2_por_param` reventaba."""
    for n in (14, 15, 16, 40):
        x = np.arange(n, dtype=float) ** 1.5
        mv = gw._moving_variance(x, 7)
        assert mv.shape == (n,), (n, mv.shape)
        for i in (0, n // 2, n - 1):
            seg = x[max(0, i - 7): i + 8]
            assert abs(mv[i] - seg.var()) < 1e-6 * max(1.0, seg.var()), (n, i)


def test_compute_di_no_deja_di_viejo_en_pozos_sin_serie():
    """Un pozo cuya serie depurada queda más corta que la ventana no tiene DI:
    `compute_di` debe dejarlo en None, no conservar el de una pasada anterior."""
    gw.wells.clear(); gw.clean_filters.clear(); gw.seed_param_registry()
    w = _pozo(); gw.wells["W"] = w
    try:
        gw.activar_di(gw.DI_VARIANTE_CONVENCION)
        gw.apply_inicio_filter(0.0); gw.compute_di()
        assert all(p.di is not None for p in w.points)
        gw.apply_inicio_filter(100.0); gw.compute_di()      # todo el pozo es emboquillado
        assert all(p.di is None for p in w.points), "quedó DI de la pasada anterior"
    finally:
        gw.wells.clear(); gw.clean_filters.clear()


def test_guardar_y_cargar_conserva_la_serie_depurada(tmp_path):
    """Tras guardar y cargar, `mascara_serie_di` debe dar la misma serie: la
    marca de emboquillado aplicado viaja en el .gwz."""
    gw.wells.clear(); gw.clean_filters.clear(); gw.seed_param_registry()
    w = _pozo(); gw.wells["W"] = w
    try:
        gw.activar_di(gw.DI_VARIANTE_CONVENCION)
        gw.aplicar_limpieza_estandar(); gw.compute_di()
        antes = gw.mascara_serie_di(gw.wells["W"].points).copy()
        assert not antes.all()
        ruta = str(tmp_path / "p.gwz"); gw.save_project(ruta)
        gw.inicio_aplicado = False
        gw.load_project(ruta)
        assert gw.inicio_aplicado
        assert (gw.mascara_serie_di(gw.wells["W"].points) == antes).all()
    finally:
        gw.wells.clear(); gw.clean_filters.clear()
