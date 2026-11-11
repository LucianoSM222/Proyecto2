"""Límites operacionales del equipo, margen del cambio de barra y limpieza sin
regulación automática de la percusión (decisión del autor, 2026-11-11).

1. Límites del equipo (entrenamiento): PR 0,1–1,5 m/min, PP 90–230 bar,
   FP 20–150, DP 25–150, RP 30–80, FLP 2–10 bar. Un registro fuera de
   cualquiera de ellos no entrena. PR = 0 queda fuera por construcción.
   PP 230 y RP 80 salen de la meseta más alta sostenida 5 m (225,1 y 81 bar).
2. Serie del DI: lo que es del EQUIPO sale desde el inicio —PR = 0, PP bajo el
   mínimo, FP bajo el mínimo, PR sobre 10 m/min—; lo que puede ser ROCA se
   queda aunque esté fuera de rango (PR alta, RP alta, DP, FLP).
3. Cambio de barra con margen: `barra.margen_antes` registros antes y
   `barra.margen_despues` después de la detención salen junto con ella
   (0 y 2 en MPC: el transitorio aparece al reanudar, no al detenerse).
4. La regulación automática de la percusión (filtro 2) no es parte de la
   limpieza estándar.
"""
import numpy as np
import geomech_wizard as gw

L = 1.756


def _pt(largo, **kw):
    base = dict(vel=1.0, pp=200.0, pa=70.0, pd=100.0, pr=45.0, pf=8.0, se=300.0, t=0.0)
    base.update(kw)
    return gw.MWDPoint(largo=largo, **base)


def _reset():
    gw.wells.clear(); gw.clean_filters.clear(); gw.seed_param_registry(force=True)


def test_limites_del_equipo_solo_entrenamiento():
    _reset()
    casos = [dict(), dict(vel=0.0), dict(vel=0.09), dict(vel=1.6), dict(pp=230.5),
             dict(pp=89.0), dict(pa=19.0), dict(pa=151.0), dict(pd=24.0), dict(pd=151.0),
             dict(pr=29.0), dict(pr=81.0), dict(pf=1.9), dict(pf=10.1),
             dict(vel=0.1, pp=90.0, pa=20.0, pd=25.0, pr=30.0, pf=2.0),
             dict(vel=1.5, pp=230.0, pa=150.0, pd=150.0, pr=80.0, pf=10.0)]
    w = gw.Well(well_name="W", plan_id="CAS_PR01_TH_W", hole_id="W",
                points=[_pt(5 + i * 0.02, **c) for i, c in enumerate(casos)])
    gw.wells["W"] = w
    try:
        f = gw.add_limites_equipo_filter()
        esperado = [True] + [False] * 13 + [True, True]
        assert [p.entrenable for p in w.points] == esperado
        assert f["removed"] == 13 and f["method"] == "rango_fisico"
        assert f["por_variable"]["PR"] == 3 and f["por_variable"]["RP"] == 2
        # alias histórico: el nombre viejo sigue funcionando
        gw.clean_filters.clear()
        for p in w.points: p.entrenable = True
        assert gw.add_rango_fisico_pp_filter()["removed"] == 13
        # recompute_filters lo reaplica aunque se haya borrado de la lista
        gw.clean_filters.clear(); gw.recompute_filters(0.0)
        assert [p.entrenable for p in w.points] == esperado
    finally:
        _reset()


def _pozo_barra(n=600):
    rng = np.random.default_rng(5)
    paradas = [0.30 + k * L for k in range(2, 7)]
    pts = []
    for i in range(n):
        lar = round(i * 0.02, 3)
        para = any(abs(lar - s) < 0.011 for s in paradas)
        pts.append(_pt(lar, vel=0.0 if para else 1.0 + rng.normal(0, .03),
                       pp=(120.0 if lar < 1.0 else 210.0) + rng.normal(0, 2),
                       pd=100 + rng.normal(0, 3), pr=45 + rng.normal(0, 1),
                       pf=8 + rng.normal(0, .2)))
    pts[400].vel = 12.0                       # cavidad: PR sobre el tope del DI
    return gw.Well(well_name="B", plan_id="CAS_PR01_TH_B", hole_id="B", points=pts), paradas


def test_margen_del_cambio_de_barra():
    _reset()
    w, paradas = _pozo_barra()
    ps = w.points
    try:
        assert gw.get_param("barra.margen_antes") == 0 and gw.get_param("barra.margen_despues") == 2
        gw.set_param("barra.margen_despues", 0)
        sin = set(gw.detectar_cambio_de_barra(ps))
        gw.reset_param("barra.margen_despues")
        con = set(gw.detectar_cambio_de_barra(ps))
        assert sin and all(ps[i].vel == 0 for i in sin)
        assert con > sin and len(con - sin) == 2 * len(paradas)
        for i in sin:
            assert {i + 1, i + 2} <= con and i - 1 not in con
        gw.set_param("barra.margen_antes", 1)
        assert len(set(gw.detectar_cambio_de_barra(ps)) - con) == len(paradas)
    finally:
        _reset()


def test_limpieza_estandar_sin_regulacion_y_tope_pr_del_di():
    _reset()
    w, _ = _pozo_barra(); gw.wells["B"] = w
    try:
        gw.activar_di(gw.DI_VARIANTE_CONVENCION)
        res = gw.aplicar_limpieza_estandar()
        metodos = {f["method"] for f in gw.clean_filters}
        assert "percusion_empate" not in metodos, "la regulación ya no es parte de la limpieza"
        assert "percusion_empate" not in res
        assert {"cambio_barra", "rango_fisico", "continuidad"} <= metodos
        assert all(not p.entrenable for p in w.points if p.vel == 0 or p.vel > 1.5)
        gw.compute_di()
        assert w.points[400].di is None, "PR sobre 10 m/min sale de la serie del DI"
        # ROCA: fuera de rango pero con DI (solo sale del entrenamiento)
        w.points[450].pr = 95.0; w.points[452].vel = 6.0
        w.points[461].pd = 200.0; w.points[463].pf = 14.0
        # EQUIPO: sale de la serie del DI
        w.points[470].vel = 0.0        # detención fuera de la grilla de barra
        w.points[480].pp = 40.0        # sin percusión efectiva
        w.points[490].pa = 5.0         # sin empuje
        gw.recompute_filters(); gw.add_cambio_barra_filter(); gw.compute_di()
        for i in (450, 452, 461, 463):
            assert w.points[i].di is not None and not w.points[i].entrenable, i
        for i in (470, 480, 490):
            assert w.points[i].di is None and not w.points[i].entrenable, i
    finally:
        _reset()
