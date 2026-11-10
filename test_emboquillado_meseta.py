"""Emboquillado por meseta de PP, cambio de barra y regulación automática de la
percusión (decisión del autor, 2026-11-10).

1. Cambio de barra: registros con PR = 0 sobre la grilla φ + k·L (L = 1,756 m,
   ±6 cm, ≥ 3 uniones) del pozo. Una detención fuera de la grilla no se marca.
2. Regulación automática de la percusión: la caída de PP ≥ 0,25 que se
   recupera (el filtro que antes se llamaba «percusión de empate»).
3. Emboquillado por meseta: sin cambio de barra ni regulación, el primer punto
   desde el cual la PP se mantiene pareja 20 cm (90% a ±15 bar de su mediana)
   sobre el 70% de la PP más frecuente del pozo. Lo anterior es emboquillado.
   Un pozo sin meseta usa el corte fijo de respaldo y se declara.
"""
import numpy as np
import geomech_wizard as gw

L = 1.756


def _pozo(nombre, pp_de, n=500, paradas=()):
    """Pozo de 10 m a 2 cm. `pp_de(largo)` da la PP; en `paradas` la PR es 0."""
    rng = np.random.default_rng(1)
    pts = []
    for i in range(n):
        lar = round(i * 0.02, 3)
        para = any(abs(lar - s) < 0.011 for s in paradas)
        pts.append(gw.MWDPoint(largo=lar, vel=0.0 if para else 1.0 + rng.normal(0, 0.03),
                               pp=pp_de(lar) + rng.normal(0, 2), pa=70.0 + rng.normal(0, 1),
                               pd=100.0 + rng.normal(0, 2), pr=50.0 + rng.normal(0, 1),
                               pf=8.0 + rng.normal(0, 0.1), se=300.0, t=0.0))
    return gw.Well(well_name=nombre, plan_id="CAS_PR01_TH_" + nombre, hole_id=nombre, points=pts)


def _pp_normal(lar):
    if lar < 1.0: return 130.0                       # emboquillado: nivel bajo
    if lar < 1.2: return 130.0 + (lar - 1.0) * 400   # subida
    return 210.0                                     # perforación


def _pp_oscila(lar):
    return 110.0 if int(lar / 0.06) % 2 else 200.0   # nunca se estabiliza


def _reset():
    gw.wells.clear(); gw.clean_filters.clear(); gw.seed_param_registry()


def test_cambio_de_barra_solo_sobre_la_grilla():
    paradas = [0.30 + k * L for k in range(1, 6)] + [4.10]   # 4,10 m: detención fuera de la grilla
    ps = _pozo("B", _pp_normal, paradas=paradas).points
    idx = gw.detectar_cambio_de_barra(ps)
    marcados = {round(ps[i].largo, 2) for i in idx}
    for k in range(1, 6):
        assert any(abs(m - (0.30 + k * L)) < 0.03 for m in marcados), f"falta la unión {k}"
    assert not any(abs(m - 4.10) < 0.03 for m in marcados), "una detención fuera de la grilla no es cambio de barra"


def test_meseta_corta_donde_la_pp_se_estabiliza():
    _reset()
    w = _pozo("M", _pp_normal, paradas=[0.30 + k * L for k in range(1, 6)]); gw.wells["M"] = w
    try:
        gw.activar_di(gw.DI_VARIANTE_CONVENCION)
        res = gw.aplicar_limpieza_estandar()
        corte, modo = gw.inicio_por_pozo["M"]
        assert modo == "meseta" and 1.10 <= corte <= 1.30, (corte, modo)   # sube de 130 a 210 entre 1,0 y 1,2 m
        assert all(p.emboquillado == (p.largo < corte) for p in w.points), "emboquillado = todo lo anterior a la meseta"
        assert all(not p.entrenable for p in w.points if p.emboquillado)
        assert res["emboquillado_modo"] == "meseta" and res["cambio_barra"] >= 5
        gw.compute_di()
        assert all(p.di is None for p in w.points if p.emboquillado), "el emboquillado sale de la serie del DI"
        parada = min(w.points, key=lambda p: abs(p.largo - (0.30 + 2 * L)))
        assert parada.vel == 0 and parada.di is None and not parada.entrenable, "el cambio de barra sale del DI y del entrenamiento"
        # recompute_filters (al borrar otro filtro) conserva el modo meseta
        gw.recompute_filters()
        assert gw.inicio_por_pozo["M"][1] == "meseta" and any(p.emboquillado for p in w.points)
    finally:
        _reset()


def test_sin_meseta_usa_el_respaldo_y_lo_declara():
    _reset()
    w = _pozo("S", _pp_oscila); gw.wells["S"] = w
    try:
        res = gw.aplicar_limpieza_estandar()
        corte, modo = gw.inicio_por_pozo["S"]
        assert modo == "respaldo" and corte == gw.inicio_cut_m
        assert "S" in res["pozos_sin_meseta"]
        assert all(p.emboquillado == (p.largo < gw.inicio_cut_m) for p in w.points)
    finally:
        _reset()


def test_corte_fijo_sigue_disponible():
    _reset()
    w = _pozo("F", _pp_normal); gw.wells["F"] = w
    try:
        gw.apply_inicio_filter(2.0)
        assert gw.emboquillado_modo == "fijo"
        assert all(p.emboquillado == (p.largo < 2.0) for p in w.points)
    finally:
        _reset()
