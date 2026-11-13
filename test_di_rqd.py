"""
test_di_rqd.py — ¿Qué tan bien describe el DI al macizo?

ESTE ARCHIVO CAMBIÓ DE PREGUNTA, por corrección del autor.

Antes probaba la "validación independiente DI ↔ RQD": el DI medio por CASERÓN
contra el RQD del Excel geomecánico, esperando anticorrelación. Ese contraste
no era factible —un promedio de caserón contra otro promedio de caserón, con
cinco caserones, no valida nada— y tenía el encuadre invertido.

EL ENCUADRE CORRECTO: lo único verídico es el TESTIGO. El RQD de sondaje no es
una segunda fuente con la que contrastar; es el PATRÓN que ajusta los pesos
para que el MWD calcule RQD, y es ese cálculo extrapolado el que después vale
en todo el caserón.

Así que la pregunta ya no es "¿coinciden dos fuentes?" sino "¿cuánto se
aparta, EN PUNTOS DE RQD, lo que calcula el MWD de lo que midió el testigo?".
Esa es la vara honesta: si el error medio son 12 puntos de RQD, eso es lo que
el modelo puede prometer y nada más.

Se conserva la prueba de spearman_rho, que sigue siendo la base de todo lo
demás.
"""

import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import geomech_wizard as gw


def _reset_state():
    gw.seed_attribute_registry(force=True)
    gw.seed_di_variants(force=True)
    gw.seed_param_registry(force=True)
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    gw.drillholes.clear()


E0, N0, Z0 = 376700.0, 6959000.0, 300.0
PASO = 0.02


def test_spearman_known_cases():
    """rho de Spearman contra casos con resultado conocido."""
    assert abs(gw.spearman_rho([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) - 1.0) < 1e-9
    assert abs(gw.spearman_rho([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) + 1.0) < 1e-9
    # Monótona pero no lineal: Spearman sigue dando 1.
    assert abs(gw.spearman_rho([1, 2, 3, 4], [1, 4, 9, 16]) - 1.0) < 1e-9
    # Menos de dos pares no define correlación.
    assert gw.spearman_rho([1.0], [2.0]) is None


def _pozo(wn, este, n, seed, zonas_malas):
    rng = np.random.default_rng(seed)
    pts = []
    for i in range(n):
        p = gw.MWDPoint(largo=i * PASO,
                        vel=float(0.9 + rng.normal(0, 0.01)),
                        pp=float(200.0 + rng.normal(0, 1.0)),
                        pa=float(60.0 + rng.normal(0, 0.5)),
                        pd=float(75.0 + rng.normal(0, 0.5)),
                        pr=float(45.0 + rng.normal(0, 0.4)),
                        pf=float(8.0 + rng.normal(0, 0.08)),
                        se=340.0, t=0.0)
        p.este = este; p.norte = N0; p.cota = Z0 - i * PASO
        p.entrenable = True; p.dominio = p.lito = "Bht"
        pts.append(p)
    for a, b in zonas_malas:
        for i in range(int(a / PASO), min(n, int(b / PASO) + 1)):
            pts[i].pd *= float(1.0 + rng.normal(0, 0.35))
    w = gw.Well(well_name=wn, plan_id=f"CAS_PR01_TH_{wn}", hole_id=wn, points=pts)
    w.caseron = "CAS_A"
    gw.wells[wn] = w
    return w


def _sondaje(hid, este, tramos):
    dh = gw.DrillHole(holeid=hid, x_utm=este, y_utm=N0, z_utm=Z0, length=30.0)
    dh.trace = [(0.0, este, N0, Z0), (30.0, este, N0, Z0 - 30.0)]
    dh.geomec = [{"from": a, "to": b, "rqd": r, "rmr": None} for a, b, r in tramos]
    gw.drillholes[hid] = dh
    return dh


def _escenario(n_sitios=3):
    _reset_state()
    zonas = [(3.0, 6.0), (12.0, 15.0)]
    for k in range(n_sitios):
        este = E0 + k * 60.0
        _pozo(f"W{k}", este + 1.0, n=1200, seed=10 + k, zonas_malas=zonas)
        tramos = []
        for t0 in range(0, 21, 3):
            malo = any(abs(t0 - a) < 1e-9 for a, _ in zonas)
            tramos.append((float(t0), float(t0 + 3), 30.0 if malo else 95.0))
        _sondaje(f"DH{k}", este, tramos)
    gw.compute_di()


def test_indicador_mide_apartamiento_en_puntos_de_rqd():
    """El indicador entrega el error EN PUNTOS DE RQD, que es lo que el
    modelo puede prometer, y no una correlación suelta."""
    _escenario()
    try:
        ind = gw.di_quality_indicator(radio_m=15.0)
        assert ind["status"] == "ok", ind.get("motivo")
        for k in ("mae_rqd", "rmse_rqd", "sesgo_rqd", "rho", "n_pares",
                  "n_sondajes", "veredicto", "encuadre"):
            assert k in ind, f"falta {k}: {sorted(ind)}"
        assert ind["mae_rqd"] >= 0.0
        assert ind["rmse_rqd"] >= ind["mae_rqd"] - 1e-9, \
            "el RMSE no puede ser menor que el MAE"
        assert ind["n_pares"] > 0 and ind["n_sondajes"] > 0
        # El encuadre tiene que decir que el testigo es el patrón, no un
        # contraste independiente: es la corrección que originó este cambio.
        assert "patrón" in ind["encuadre"] or "patron" in ind["encuadre"]
    finally:
        _reset_state()


def test_sin_sondajes_declara_en_vez_de_inventar():
    """Sin testigo no hay vara: se declara y no se entrega un número."""
    _reset_state()
    try:
        _pozo("W1", E0, n=600, seed=1, zonas_malas=[])
        gw.compute_di()
        ind = gw.di_quality_indicator()
        assert ind["status"] != "ok"
        assert ind.get("motivo"), "sin datos hay que decir por qué"
        assert "mae_rqd" not in ind, "no se entrega error sin con qué compararlo"
    finally:
        _reset_state()


def test_el_veredicto_distingue_ordenar_de_medir():
    """
    Un DI puede ORDENAR bien los sectores y aun así MEDIR mal el RQD. El
    veredicto tiene que separar las dos cosas: sirven para decisiones
    distintas —ranquear sectores contra entregar un número—.
    """
    _escenario()
    try:
        ind = gw.di_quality_indicator(radio_m=15.0)
        assert ind["status"] == "ok"
        v = ind["veredicto"].upper()
        assert any(t in v for t in ("DESCRIBE BIEN", "ORDENA BIEN",
                                    "NO DESCRIBE", "NO CONCLUYENTE")), ind["veredicto"]
    finally:
        _reset_state()
