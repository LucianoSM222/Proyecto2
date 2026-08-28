"""
test_resultado_ml_sin_bosque.py — Banda y relación ya no revientan mostrando el resultado.

LO REPORTADO: «El modelo Banda -> SE, reporta key error en r2_train».

`poll_ml_task()` —el callback que arma la tarjeta de resultado tras correr
Paso 4— asumía que `task_state["result"]` SIEMPRE tenía la forma que devuelve
`train_rf()`: r2_train, rmse_train, rmsea, cv_r2_mean, n_train, n_excl_disc.
Esa forma es del bosque aleatorio. Cuando el modelo elegido es "banda" o
"relacion", `run_ml_task()` guarda ahí lo que devuelve
`predict_ucs_banda()`/`predict_ucs_relacion()` —n_puntos, escalas, vara,
procedencia— que no tiene ninguna de esas claves. Leer `result["r2_train"]`
sin mirar cuál modelo corrió es exactamente el KeyError reportado.

La corrección no fuerza los dos modelos a la misma forma —tienen semántica
distinta: uno entrena y valida con R², el otro mapea una distribución sobre
una banda calibrada con anclas—. Cada uno tiene su tarjeta.
"""

import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import geomech_wizard as gw

FAILURES = []


def check(cond, label, detail=""):
    if cond:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}" + (f"  → {detail}" if detail else ""))
        FAILURES.append(label)


def section(t):
    print(f"\n{'='*72}\n{t}\n{'='*72}")


def reset():
    gw.seed_attribute_registry(force=True)
    gw.seed_param_registry(force=True)
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    gw.drillholes.clear()
    with gw.task_lock:
        gw.task_state.update(running=False, progress=0, stage="", log=[],
                             error=None, result=None, done=False)


E0, N0, Z0 = 376700.0, 6959000.0, 300.0
LITOS = {"Bht": 128.1, "Kpcli": 180.0, "Brecha_mixta": 111.5}


def _escenario(seed=0):
    reset()
    rng = np.random.default_rng(seed)
    for k, (lito, ucs) in enumerate(LITOS.items()):
        pts = []
        for i in range(120):
            p = gw.MWDPoint(largo=i * 0.2, vel=float(0.9 + rng.normal(0, .03)),
                            pp=200.0, pa=60.0, pd=75.0, pr=45.0, pf=8.0,
                            se=float(330 + rng.normal(0, 15)), t=0.0)
            p.este = E0 + k * 2.0; p.norte = N0 + i * 0.15; p.cota = Z0 - i * 0.12
            p.entrenable = True; p.dominio = p.lito = lito
            pts.append(p)
        gw.wells[f"T{k}"] = gw.Well(well_name=f"T{k}", plan_id="CAS_PR01_TH_P01",
                                    hole_id=str(k), points=pts)
        gw.domains[lito] = {"count": 120, "ucs_lab": ucs, "atributo_id": lito,
                            "alteracion_id": None, "estructura_id": None,
                            "pi_factor": None, "calidad": 1,
                            "fuente_ucs": "prueba", "modo_ucs": "central"}


def _dejar_task_terminada_con(result):
    with gw.task_lock:
        gw.task_state.update(running=False, progress=100, stage="Completado",
                             log=["x"], error=None, result=result, done=True)


# ─────────────────────────────────────────────────────────────────────────────
def banda_no_tiene_r2_train():
    section("Precondición — la forma de banda no trae r2_train")
    _escenario()
    rep = gw.predict_ucs_banda()
    check(rep.get("status") == "ok", "el modelo por banda corre", rep.get("motivo"))
    check("r2_train" not in rep,
          "y su resultado NO trae r2_train: es la forma que rompía al leerse "
          "como si fuera la del bosque", sorted(rep))


def pintar_el_resultado_de_banda_no_revienta():
    section("poll_ml_task — banda ya no reventaba con KeyError")
    _escenario()
    rep = gw.predict_ucs_banda()
    _dejar_task_terminada_con(rep)
    try:
        out = gw.poll_ml_task(1, 0)
    except KeyError as e:
        check(False, "poll_ml_task no revienta leyendo el resultado de banda",
              f"KeyError: {e}")
        return
    check(len(out) == 9, "el callback devuelve sus nueve salidas", len(out))
    badges, msg, toast_open = out[6], out[7], out[8]
    check(badges is not None, "y arma una tarjeta de resultado")
    check("✅" in msg and str(rep["n_puntos"]) in msg,
          "el mensaje declara cuántos puntos quedaron con UCS", msg)
    check("r2" not in msg.lower(),
          "sin prometer un R² que este modelo no calcula", msg)


def pintar_el_resultado_de_relacion_no_revienta():
    section("poll_ml_task — relación directa tampoco revienta")
    _escenario()
    rep = gw.predict_ucs_relacion()
    check(rep.get("status") == "ok", "el modelo por relación corre", rep.get("motivo"))
    check("r2_train" not in rep, "y tampoco trae r2_train", sorted(rep))
    _dejar_task_terminada_con(rep)
    out = gw.poll_ml_task(1, 0)
    check(len(out) == 9, "el callback corre igual", len(out))
    check("✅" in out[7], "con un mensaje de éxito", out[7])


def la_tarjeta_muestra_la_vara_no_un_r2_inventado():
    section("poll_ml_task — la tarjeta de banda/relación no finge un R²")
    _escenario()
    rep = gw.predict_ucs_banda()
    tarjeta = gw._render_ml_result_no_bosque(rep)
    check(tarjeta is not None, "la tarjeta se arma")

    def _textos(x, out=None):
        out = [] if out is None else out
        if isinstance(x, str):
            out.append(x); return out
        if isinstance(x, (list, tuple)):
            for y in x: _textos(y, out)
            return out
        for a in ("children", "title"):
            v = getattr(x, a, None)
            if v is not None: _textos(v, out)
        return out
    txt = " ".join(_textos(tarjeta))
    # "R² in-sample" SÍ puede aparecer una vez, dentro de la explicación de
    # por qué no se reporta — lo que no puede haber es una TARJETA con ese
    # rótulo y un número al lado, que es cómo se ve el bosque. Dos apariciones
    # delatarían que la tarjeta de número se coló también acá.
    check(txt.count("R² in-sample") <= 1,
          "el rótulo de esa métrica no se repite como si fuera una tarjeta de "
          "número: aparece a lo más una vez, dentro de la explicación", txt[:250])
    check("RMSE in-sample" not in txt,
          "y no hay tarjeta de RMSE in-sample tampoco, que es la otra mitad "
          "del par que solo tiene sentido con un modelo entrenado", txt[:200])
    check("bosque" in txt.lower() or "banda" in txt.lower() or "energía" in txt.lower(),
          "y explica en qué consiste el número que sí muestra")
    if rep.get("vara", {}).get("mae_mpa") is not None:
        check(f"{rep['vara']['mae_mpa']:g}" in txt or "Error dejando" in txt,
              "trayendo su propia vara — el error dejando-una-litología-fuera",
              txt[:300])


def el_bosque_sigue_mostrando_su_r2_de_siempre():
    section("poll_ml_task — el camino del bosque NO cambió")
    _escenario()
    stats = {"r2_train": 0.42, "rmse_train": 12.3, "rmsea": 1.1,
             "n_train": 300, "n_excl_disc": 5, "cv_r2_mean": None,
             "cv_r2_std": None, "cv_warning": "CV agrupada requiere ≥3 pozos con etiqueta (hay 2)."}
    _dejar_task_terminada_con(stats)
    out = gw.poll_ml_task(1, 0)
    check("r2_train" in stats, "la forma del bosque sigue intacta", sorted(stats))
    check("0.42" in out[7], "y el mensaje sigue reportando su R² real", out[7])
    check("R² CV agrupada" in out[7] or "sin CV" in out[7],
          "con la lectura de CV agrupada de siempre", out[7])


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    banda_no_tiene_r2_train,
    pintar_el_resultado_de_banda_no_revienta,
    pintar_el_resultado_de_relacion_no_revienta,
    la_tarjeta_muestra_la_vara_no_un_r2_inventado,
    el_bosque_sigue_mostrando_su_r2_de_siempre,
]


def test_resultado_ml_sin_bosque():
    """Punto de entrada para pytest."""
    FAILURES.clear()
    try:
        for t in ALL_TESTS:
            t()
    finally:
        reset()
    assert not FAILURES, f"{len(FAILURES)} comprobación(es) fallida(s): " + "; ".join(FAILURES)


if __name__ == "__main__":
    try:
        for t in ALL_TESTS:
            t()
    finally:
        reset()
    print(f"\n{'='*72}")
    if FAILURES:
        print(f"✗ {len(FAILURES)} FALLA(S):")
        for f in FAILURES:
            print(f"   · {f}")
        sys.exit(1)
    print("✓ RESULTADO ML SIN BOSQUE — todas las verificaciones pasaron.")
    print("=" * 72)
