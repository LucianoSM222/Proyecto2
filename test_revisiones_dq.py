"""Revisiones del DQ y registros MWD repetidos (2026-11-15).

Caso real: el plan PCS_1043_PR01_TH_P07 tiene dos revisiones del DQ (14 y 23 de
marzo). Para los barrenos 5, 12 y 17 la revisión del 14 coincide EXACTAMENTE con
el largo perforado y la del 23 no; el programa solo contrastaba la más reciente
y terminaba ubicando H5 y H12 con el collar de OTRO plan (P16 y P18) y
descartando H17.

1. Una revisión anterior del MISMO plan que cumple la coherencia de largo gana a
   cualquier plan hermano.
2. Con dos registros MWD del mismo barreno, se usa el que tiene posición
   coherente en su propio plan; entre los coherentes, el de más registros
   (H13: 1.043 muestras desde 0 m, contra 256 desde 11,3 m).
"""
import geomech_wizard as gw

E0, N0, Z0 = 376700.0, 6959000.0, 300.0
lu = lambda e, n, z: {"este": e, "norte": n, "cota": z}


def _mw(plan, hole, largo_max, n, desde=0.0):
    pts = []
    paso = (largo_max - desde) / max(n - 1, 1)
    for i in range(n):
        pts.append(gw.MWDPoint(largo=desde + i * paso, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                               pr=45.0, pf=8.0, se=340.0, t=0.0))
    for p in pts:
        p.t = p.largo / largo_max
    return {"plan_id": plan, "hole_id": hole, "largo_max": largo_max, "puntos": pts}


def _reset():
    gw.seed_param_registry(force=True)
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear(); gw.drillholes.clear()
    gw.global_center = None


def _tiro(collar, largo):
    return {"collar": lu(*collar), "final_pt": lu(collar[0], collar[1], collar[2] + largo)}


def test_revision_anterior_del_mismo_plan_gana_al_hermano():
    _reset()
    viejo = {"plan_id": "P07", "fecha": "2026-03-14", "fname": "DQ_P07_0314",
             "tiros": {"5": _tiro((E0, N0, Z0), 29.64)}}
    nuevo = {"plan_id": "P07", "fecha": "2026-03-23", "fname": "DQ_P07_0323",
             "tiros": {"5": _tiro((E0, N0, Z0), 34.21)}}
    hermano = {"plan_id": "P16", "fecha": "2026-03-20", "fname": "DQ_P16",
               "tiros": {"5": _tiro((E0 - 22, N0 + 15, Z0), 29.70)}}
    dq, rep = gw.merge_dq_siblings([viejo, nuevo, hermano])
    assert dq["P07"]["tiros"]["5"]["final_pt"]["cota"] == Z0 + 34.21, "la vigente sigue siendo la más reciente"
    counts = gw.match_and_place_wells(dq, {"P07_H5": [_mw("P07", "5", 29.64, 300)]})
    w = gw.wells["P07_H5"]
    assert w.origin == "matched", w.origin
    assert abs(w.collar["este"] - E0) < 1e-6, "el collar es el de P07, no el del hermano P16"
    assert abs(w.final_pt["cota"] - (Z0 + 29.64)) < 1e-6, "con la revisión que coincide con lo perforado"
    assert counts["fallback"] == 0


def test_revision_anterior_recupera_un_barreno_descartado():
    _reset()
    viejo = {"plan_id": "P07", "fecha": "2026-03-14", "fname": "a", "tiros": {"17": _tiro((E0, N0, Z0), 9.69)}}
    nuevo = {"plan_id": "P07", "fecha": "2026-03-23", "fname": "b", "tiros": {"17": _tiro((E0, N0, Z0), 50.0)}}
    dq, _ = gw.merge_dq_siblings([viejo, nuevo])
    gw.match_and_place_wells(dq, {"P07_H17": [_mw("P07", "17", 9.69, 100)]})
    assert "P07_H17" in gw.wells and gw.wells["P07_H17"].origin == "matched"


def test_dos_registros_mwd_se_usa_el_coherente_con_mas_datos():
    _reset()
    viejo = {"plan_id": "P07", "fecha": "2026-03-14", "fname": "a", "tiros": {"13": _tiro((E0, N0, Z0), 21.11)}}
    nuevo = {"plan_id": "P07", "fecha": "2026-03-23", "fname": "b", "tiros": {"13": _tiro((E0, N0, Z0), 26.04)}}
    dq, _ = gw.merge_dq_siblings([viejo, nuevo])
    completo = _mw("P07", "13", 21.11, 1043)
    tramo = _mw("P07", "13", 26.04, 256, desde=11.34)
    gw.match_and_place_wells(dq, {"P07_H13": [tramo, completo]})
    w = gw.wells["P07_H13"]
    assert len(w.points) == 1043, "se usa el registro completo, no el tramo final"
    assert min(p.largo for p in w.points) == 0.0
    assert abs(w.final_pt["cota"] - (Z0 + 21.11)) < 1e-6, "con la revisión del DQ que le corresponde"
