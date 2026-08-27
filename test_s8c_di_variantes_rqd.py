"""
test_s8c_di_variantes_rqd.py — Pasos 1 y 2.

PASO 1 · DI CALIBRABLE SIN ROMPER LA CONVENCIÓN.
CLAUDE.md fija el DI de Fernández et al. 2023 —ventana 14, pesos PP 0,35 ·
DP 0,25 · FP 0,20 · RP 0,20, umbral 1,5— como convención inmutable. Para poder
calibrar los pesos contra el RQD de los sondajes sin violarla, el DI de la
convención queda INTOCADO como referencia y se agregan VARIANTES con nombre
propio, cada una con sus pesos, su ventana y su umbral. Conviven, se comparan,
y la de convención no se puede editar ni borrar. `p.di` sigue siendo siempre
el de la convención; las variantes viven aparte, en el pozo.

PASO 2 · RQD DE SONDAJE PROPAGADO AL MWD, CON SU PROCEDENCIA.
Cada punto MWD puede recibir el RQD del sondaje más cercano, pero SIEMPRE con
el nombre del sondaje y la distancia a la que estaba. Sobre los datos reales
la distancia mediana de un punto MWD al intervalo de RQD más cercano es de
26,1 m: una etiqueta así no puede circular como si fuera medida en el mismo
lugar. Fuera del radio no se etiqueta, y se cuenta cuántos quedaron sin
etiqueta.
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
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    gw.drillholes.clear(); gw.set_training_caserones(None)
    gw.seed_di_variants(force=True)


E0, N0, Z0 = 376700.0, 6959000.0, 300.0
PASO = 0.02


def _pozo(wn, este, norte=N0, n=600, seed=0, picos_en=()):
    rng = np.random.default_rng(seed)
    pts = []
    for i in range(n):
        largo = i * PASO
        p = gw.MWDPoint(largo=largo,
                        vel=float(0.90 + rng.normal(0, 0.01)),
                        pp=float(200.0 + rng.normal(0, 1.5)),
                        pa=float(60.0 + rng.normal(0, 0.8)),
                        pd=float(75.0 + rng.normal(0, 0.8)),
                        pr=float(45.0 + rng.normal(0, 0.6)),
                        pf=float(8.0 + rng.normal(0, 0.1)),
                        se=340.0, t=0.0)
        p.este = este; p.norte = norte; p.cota = Z0 - largo
        p.entrenable = True; p.dominio = "Bht"; p.lito = "Bht"
        pts.append(p)
    # Eventos: sube la varianza del dámper en una ventana, que es lo que el DI
    # mide. Se inyectan sobre pd para poder distinguir una variante que pesa
    # mucho el dámper de otra que no lo pesa nada.
    for lp in picos_en:
        i0, i1 = int((lp - 0.15) / PASO), int((lp + 0.15) / PASO)
        for i in range(max(0, i0), min(n, i1 + 1)):
            pts[i].pd *= float(1.0 + rng.normal(0, 0.25))
    w = gw.Well(well_name=wn, plan_id=f"CAS_PR01_TH_{wn}", hole_id=wn, points=pts)
    w.caseron = "CAS_A"
    gw.wells[wn] = w
    return w


def _sondaje(hid, este, norte=N0, tramos_rqd=()):
    dh = gw.DrillHole(holeid=hid, x_utm=este, y_utm=norte, z_utm=Z0, length=20.0)
    dh.trace = [(0.0, este, norte, Z0), (20.0, este, norte, Z0 - 20.0)]
    dh.geomec = [{"from": a, "to": b, "rqd": r, "rmr": None}
                 for a, b, r in tramos_rqd]
    gw.drillholes[hid] = dh
    return dh


# ─── PASO 1 ──────────────────────────────────────────────────────────────────
def la_convencion_no_se_puede_tocar():
    section("1 — La variante de convención existe y es de solo lectura")
    reset()
    v = gw.di_variant(gw.DI_VARIANTE_CONVENCION)
    check(v is not None, "la variante de convención está registrada",
          list(gw.di_variantes))
    if v is None:
        return
    check(v["window"] == 14 and v["threshold"] == 1.5,
          "con la ventana 14 y el umbral 1,5 de la convención",
          (v.get("window"), v.get("threshold")))
    check(v["weights"] == {"pp": 0.35, "pr": 0.20, "pd": 0.25, "pf": 0.20},
          "y los pesos de Fernández et al. 2023", v.get("weights"))
    check(v.get("solo_lectura") is True, "marcada como de solo lectura")
    check("fernández" in (v.get("fuente") or "").lower()
          or "fernandez" in (v.get("fuente") or "").lower(),
          "declarando su fuente", v.get("fuente"))
    for fn, etiqueta in ((lambda: gw.update_di_variant(gw.DI_VARIANTE_CONVENCION,
                                                       threshold=2.0), "editarla"),
                         (lambda: gw.delete_di_variant(gw.DI_VARIANTE_CONVENCION),
                          "borrarla")):
        try:
            fn()
            check(False, f"{etiqueta} tiene que fallar")
        except gw.DIVarianteProtegida as e:
            check(True, f"{etiqueta} se rechaza: {str(e)[:60]}")
        except Exception as e:
            check(False, f"{etiqueta} falla con el error equivocado", repr(e))
    v2 = gw.di_variant(gw.DI_VARIANTE_CONVENCION)
    check(v2["threshold"] == 1.5, "y queda intacta después del intento",
          v2.get("threshold"))


def crear_y_borrar_variantes():
    section("1 — Crear, editar y borrar variantes propias")
    reset()
    gw.create_di_variant("prueba", window=20,
                         weights={"pp": 0.25, "pr": 0.25, "pd": 0.40, "pf": 0.10},
                         threshold=1.2, fuente="calibración de prueba")
    v = gw.di_variant("prueba")
    check(v is not None and v["window"] == 20, "se crea con sus parámetros", v)
    check(abs(sum(v["weights"].values()) - 1.0) < 1e-9,
          "los pesos quedan normalizados a 1", v["weights"])
    gw.update_di_variant("prueba", threshold=1.8)
    check(gw.di_variant("prueba")["threshold"] == 1.8, "se puede editar")
    gw.delete_di_variant("prueba")
    check(gw.di_variant("prueba") is None, "y borrar")
    # Nombre repetido y pesos inválidos se rechazan ANTES de tocar el registro.
    gw.create_di_variant("x", weights={"pd": 1.0})
    try:
        gw.create_di_variant("x", weights={"pd": 1.0})
        check(False, "un nombre repetido tiene que fallar")
    except ValueError:
        check(True, "un nombre repetido se rechaza")
    try:
        gw.create_di_variant("y", weights={"pd": 0.0, "pp": 0.0})
        check(False, "pesos todos en cero tienen que fallar")
    except ValueError:
        check(True, "pesos todos en cero se rechazan")
    check(gw.di_variant("y") is None, "y el registro no queda a medias")


def la_variante_no_pisa_el_di_de_convencion():
    section("1 — Calcular una variante NO toca p.di")
    reset()
    _pozo("W1", E0, picos_en=(4.0, 8.0))
    gw.compute_di()
    di_antes = [p.di for p in gw.wells["W1"].points]
    gw.create_di_variant("solo_damper", window=14,
                         weights={"pd": 1.0}, threshold=1.5,
                         fuente="prueba: todo el peso al dámper")
    gw.compute_di_variant("solo_damper")
    di_despues = [p.di for p in gw.wells["W1"].points]
    check(di_antes == di_despues, "p.di queda idéntico tras calcular la variante")
    vals = gw.di_variant_values(gw.wells["W1"], "solo_damper")
    check(vals is not None and len(vals) == len(di_antes),
          "la variante se guarda en el pozo, no en el punto",
          None if vals is None else len(vals))
    check(not np.allclose(vals, np.array(di_antes)),
          "y da valores DISTINTOS: pesos distintos, perfil distinto")
    check(gw.di_config_is_default(), "la configuración global sigue en convención",
          gw.di_config_summary())


def los_picos_se_pueden_pedir_por_variante():
    section("1 — Los picos se pueden pedir con la variante que se quiera")
    reset()
    _pozo("W1", E0, picos_en=(4.0, 8.0))
    gw.compute_di()
    gw.create_di_variant("solo_damper", weights={"pd": 1.0}, threshold=1.5)
    gw.compute_di_variant("solo_damper")
    pk_conv = gw.di_peaks(gw.wells["W1"])
    pk_var = gw.di_peaks(gw.wells["W1"], variante="solo_damper")
    check(isinstance(pk_var, list), "di_peaks acepta una variante", type(pk_var))
    check(pk_conv != pk_var or len(pk_var) > 0,
          "y devuelve los picos de ESA variante",
          (len(pk_conv), len(pk_var)))
    # Pedir una variante que no se calculó no puede devolver los de convención
    # en silencio.
    try:
        gw.di_peaks(gw.wells["W1"], variante="inexistente")
        check(False, "una variante inexistente tiene que fallar")
    except KeyError:
        check(True, "una variante inexistente se rechaza en vez de caer a la convención")


# ─── PASO 2 ──────────────────────────────────────────────────────────────────
def rqd_propagado_lleva_su_procedencia():
    section("2 — El RQD propagado viaja con su sondaje y su distancia")
    reset()
    _pozo("W_cerca", E0 + 1.0, n=400)
    _pozo("W_lejos", E0 + 200.0, n=400)
    _sondaje("DH1", E0, tramos_rqd=((0.0, 4.0, 90.0), (4.0, 8.0, 45.0)))

    rep = gw.propagate_drillhole_rqd(radio_m=10.0)
    check(rep["status"] == "ok", "la propagación corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    p = gw.wells["W_cerca"].points[10]
    check(p.rqd_sondaje is not None, "el punto cercano recibe RQD", p.rqd_sondaje)
    check(p.rqd_sondaje_origen == "DH1", "declarando de qué sondaje sale",
          p.rqd_sondaje_origen)
    check(p.rqd_sondaje_dist_m is not None and p.rqd_sondaje_dist_m <= 10.0,
          "y a qué distancia estaba", p.rqd_sondaje_dist_m)
    lejos = gw.wells["W_lejos"].points[10]
    check(lejos.rqd_sondaje is None,
          "el punto lejano NO recibe nada: fuera del radio no se etiqueta",
          lejos.rqd_sondaje)
    check(rep["n_sin_etiqueta"] > 0,
          "y los que quedan sin etiqueta se cuentan", rep.get("n_sin_etiqueta"))
    check(rep["radio_m"] == 10.0, "el radio usado se declara", rep.get("radio_m"))
    check(rep.get("advertencia"),
          "con la advertencia de que la distancia no es cero", rep.get("advertencia"))
    # El RQD asignado es el del tramo que corresponde a esa profundidad.
    somero = gw.wells["W_cerca"].points[10]        # ~0,2 m
    hondo = gw.wells["W_cerca"].points[300]        # ~6,0 m
    check(somero.rqd_sondaje == 90.0 and hondo.rqd_sondaje == 45.0,
          "y cada punto toma el tramo de SU profundidad, no el del collar",
          (somero.rqd_sondaje, hondo.rqd_sondaje))


def sin_rqd_no_se_inventa():
    section("2 — Sin sondajes con RQD se declara, no se rellena")
    reset()
    _pozo("W1", E0)
    rep = gw.propagate_drillhole_rqd()
    check(rep["status"] == "sin_datos", "el estado lo dice", rep.get("status"))
    check(rep.get("motivo"), "con el motivo", rep.get("motivo"))
    check(all(p.rqd_sondaje is None for p in gw.wells["W1"].points),
          "y ningún punto queda con un RQD inventado")


def pares_de_calibracion():
    section("2 — Pares de calibración: un RQD_MWD contra un RQD de sondaje")
    reset()
    for k in range(4):
        _pozo(f"W{k}", E0 + k * 1.0, n=600, seed=k, picos_en=(3.0, 7.0))
    gw.compute_di()
    _sondaje("DH1", E0 + 1.5, tramos_rqd=((0.0, 6.0, 85.0), (6.0, 12.0, 55.0)))

    pares = gw.rqd_calibration_pairs(radio_m=10.0)
    check(pares["status"] == "ok", "se arman los pares", pares.get("motivo"))
    if pares["status"] != "ok":
        return
    check(len(pares["pares"]) >= 1, "hay al menos un par", len(pares["pares"]))
    p0 = pares["pares"][0]
    for k in ("rqd_mwd", "rqd_sondaje", "sondaje", "n_puntos_mwd", "n_pozos",
              "pozo", "distancia_m"):
        check(k in p0, f"cada par trae {k}", list(p0))
    # UNO A UNO: cada intervalo se aparea con UN punto MWD, no con una nube.
    check(all(p["n_pozos"] == 1 for p in pares["pares"]),
          "cada par usa UN solo pozo: el del punto más cercano al centro medido",
          [p["n_pozos"] for p in pares["pares"][:5]])
    check(all(p["distancia_m"] <= 10.0 for p in pares["pares"]),
          "y la distancia a ese punto viaja con el par",
          [p["distancia_m"] for p in pares["pares"][:5]])
    check(pares.get("distancia_m") and "mediana" in pares["distancia_m"],
          "el reporte resume a qué distancia quedaron los apareos",
          pares.get("distancia_m"))
    check(pares["variante"] == gw.DI_VARIANTE_CONVENCION,
          "por defecto se calibra contra el DI de convención", pares.get("variante"))
    check(pares.get("agrupado_por") == "sondaje",
          "y los pares se pueden agrupar por sondaje, que es la unidad de "
          "validación dejando-uno-fuera", pares.get("agrupado_por"))
    # Con una variante distinta el RQD_MWD cambia; el del sondaje no.
    gw.create_di_variant("solo_damper", weights={"pd": 1.0}, threshold=1.5)
    gw.compute_di_variant("solo_damper")
    pares_v = gw.rqd_calibration_pairs(radio_m=10.0, variante="solo_damper")
    check(pares_v["status"] == "ok", "corre con una variante", pares_v.get("motivo"))
    if pares_v["status"] == "ok" and pares_v["pares"]:
        check([x["rqd_sondaje"] for x in pares_v["pares"]]
              == [x["rqd_sondaje"] for x in pares["pares"]],
              "el RQD del sondaje no cambia con la variante")


def el_rqd_no_es_predictor():
    section("2 — El RQD propagado NO entra como predictor del modelo")
    reset()
    _pozo("W1", E0)
    _sondaje("DH1", E0, tramos_rqd=((0.0, 10.0, 80.0),))
    gw.propagate_drillhole_rqd()
    check(gw.ML_FEATURES == ["vel", "pp", "pa", "pd", "pr", "pf", "se"],
          "ML_FEATURES intacto", gw.ML_FEATURES)
    check(not any("rqd" in f.lower() for f in gw.ML_FEATURES),
          "RQD no se coló entre las predictoras: la convención lo prohíbe igual "
          "que al RMR")


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    la_convencion_no_se_puede_tocar,
    crear_y_borrar_variantes,
    la_variante_no_pisa_el_di_de_convencion,
    los_picos_se_pueden_pedir_por_variante,
    rqd_propagado_lleva_su_procedencia,
    sin_rqd_no_se_inventa,
    pares_de_calibracion,
    el_rqd_no_es_predictor,
]


def test_s8c_di_variantes_rqd():
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
    print("✓ PASOS 1 y 2 — todas las verificaciones pasaron.")
    print("=" * 72)
