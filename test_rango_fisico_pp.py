"""Rango físico de PP (`pp.min_bar`–`pp.max_bar`) como filtro de limpieza.

En MPC entraban al entrenamiento ~13.000 registros con PP de 0 a 10 bar y ROP
de 3 a 10 m/min: la sarta avanzando sin percutir. El rango estaba declarado en
el perfil y ningún filtro lo aplicaba.
"""
import geomech_wizard as gw


def _pt(largo, pp):
    return gw.MWDPoint(largo=largo, vel=1.0, pp=pp, pa=60.0, pd=75.0, pr=45.0,
                       pf=8.0, se=300.0, t=0.0)


def test_rango_fisico_pp():
    gw.wells.clear(); gw.clean_filters.clear(); gw.seed_param_registry()
    pps = [5.0, 89.9, 90.0, 150.0, 230.0, 230.1]
    w = gw.Well(well_name="W", plan_id="CAS_PR01_TH_W", hole_id="W",
                points=[_pt(5 + i * 0.02, v) for i, v in enumerate(pps)])
    gw.wells["W"] = w
    try:
        f = gw.add_rango_fisico_pp_filter()
        assert [p.entrenable for p in w.points] == [False, False, True, True, True, False]
        assert f["removed"] == 3 and f["method"] == "rango_fisico"
        # recompute_filters lo reaplica aunque se haya borrado de la lista
        gw.clean_filters.clear(); gw.recompute_filters(0.0)
        assert [p.entrenable for p in w.points] == [False, False, True, True, True, False]
    finally:
        gw.wells.clear(); gw.clean_filters.clear()
