"""
test_s8_discriminador.py — Sesión 8: discriminador fractura / contacto y RQD_MWD.

NO es un DI nuevo. El DI ya detecta DÓNDE hay una discontinuidad; esta sesión
clasifica QUÉ es cada pico que el DI ya encontró. El DI sigue siendo la
variable de trabajo del resto del pipeline y esta sesión no lo toca.

Firmas físicas, definidas por el autor:

  · ZONA FRACTURADA — el dámper CAE, la percusión cae, la velocidad aumenta.
    La broca entra en vacío: no hay macizo que amortiguar ni contra el cual
    percutir, y el avance se dispara.

  · CONTACTO — el dámper NO CAE, la percusión se DESESTABILIZA (sube o baja,
    con varianza no esperada), la rotación varía fuerte, la velocidad pierde
    su patrón. Hay roca a ambos lados: lo que cambia es cuál.

Lo que no cumple ninguna de las dos firmas queda INDETERMINADO. No hay
default silencioso: un pico sin firma clara se declara como tal.

RQD_MWD por definición de Deere: porcentaje del metraje en tramos continuos
de 10 cm o más SIN discontinuidad. Indicador AGREGADO por pozo y por caserón,
orientado a tronadura.

Etiquetas de contraste: las estructuras logueadas de la tabla de sondaje
(fractura) y los contactos derivados de los límites de la tabla de litología
que generó P2 (contacto).
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


# ─── Constructores de escenario ──────────────────────────────────────────────
PASO_M = 0.02          # ~2 cm entre registros, como el MWD real
E0, N0, Z0 = 376700.0, 6959000.0, 300.0


def _well_base(wn, n=600, seed=0):
    """
    Pozo tranquilo: roca homogénea, sin eventos. Todo lo que después se vea en
    la firma de un pico viene de lo que le inyectemos encima, no del fondo.
    """
    rng = np.random.default_rng(seed)
    pts = []
    for i in range(n):
        largo = i * PASO_M
        p = gw.MWDPoint(
            largo=largo,
            vel=float(0.90 + rng.normal(0, 0.010)),
            pp=float(200.0 + rng.normal(0, 1.5)),
            pa=float(60.0 + rng.normal(0, 0.8)),
            pd=float(75.0 + rng.normal(0, 0.8)),
            pr=float(45.0 + rng.normal(0, 0.6)),
            pf=float(8.0 + rng.normal(0, 0.1)),
            se=0.0, t=0.0)
        p.este = E0; p.norte = N0; p.cota = Z0 - largo
        p.se = (p.pp + p.pr + p.pa) / max(p.vel, 1e-6)
        p.di = 0.4
        p.entrenable = True
        p.dominio = "Bht"; p.lito = "Bht"
        pts.append(p)
    w = gw.Well(well_name=wn, plan_id=f"CAS_PR01_TH_{wn}", hole_id=wn, points=pts)
    w.caseron = "CAS_A"
    gw.wells[wn] = w
    return w


def _idx(w, largo):
    return int(round(largo / PASO_M))


def _inyecta_fractura(w, largo, media_ancho_m=0.10):
    """Dámper CAE, percusión cae, velocidad aumenta. Y el DI marca el pico."""
    i0, i1 = _idx(w, largo - media_ancho_m), _idx(w, largo + media_ancho_m)
    for i in range(max(0, i0), min(len(w.points), i1 + 1)):
        p = w.points[i]
        p.pd *= 0.55          # el dámper cae
        p.pp *= 0.80          # la percusión cae
        p.vel *= 1.45         # la velocidad aumenta
        p.se = (p.pp + p.pr + p.pa) / max(p.vel, 1e-6)
        p.di = 2.4            # el DI ya lo había detectado


def _inyecta_contacto(w, largo, media_ancho_m=0.10, seed=99):
    """
    Dámper NO cae, percusión se desestabiliza, rotación varía fuerte, la
    velocidad pierde su patrón. Hay roca a los dos lados.
    """
    rng = np.random.default_rng(seed)
    i0, i1 = _idx(w, largo - media_ancho_m), _idx(w, largo + media_ancho_m)
    for i in range(max(0, i0), min(len(w.points), i1 + 1)):
        p = w.points[i]
        p.pd *= float(1.0 + rng.normal(0, 0.01))    # se mantiene
        p.pp *= float(1.0 + rng.normal(0, 0.14))    # varianza no esperada
        p.pr *= float(1.0 + rng.normal(0, 0.18))    # rotación varía fuerte
        p.vel *= float(1.0 + rng.normal(0, 0.16))   # pierde el patrón
        p.se = (p.pp + p.pr + p.pa) / max(p.vel, 1e-6)
        p.di = 2.6


def _sondaje(hid, este, norte, cota, estructuras_m=(), contactos=()):
    """
    Sondaje vertical sintético con estructuras logueadas y tramos de litología
    cuyos límites P2 convierte en contactos derivados.
    """
    dh = gw.DrillHole(holeid=hid, x_utm=este, y_utm=norte, z_utm=cota, length=20.0)
    dh.trace = [(0.0, este, norte, cota), (20.0, este, norte, cota - 20.0)]
    dh.structures = [{"from": d, "to": d, "codigo": "FALLA", "atributo_id": "FM",
                      "tipo": "logueada"} for d in estructuras_m]
    lito = []
    prev = 0.0
    for depth, unidad in contactos:
        lito.append({"from": prev, "to": depth, "unidad": unidad})
        prev = depth
    if lito:
        lito.append({"from": prev, "to": 20.0, "unidad": "Kpcli"})
    dh.lithology = lito
    gw.drillholes[hid] = dh
    return dh


# ─────────────────────────────────────────────────────────────────────────────
def firma_de_fractura():
    section("8 — Firma de zona fracturada: dámper cae, percusión cae, velocidad sube")
    reset()
    w = _well_base("W1", seed=1)
    _inyecta_fractura(w, 6.00)

    picos = gw.discriminate_peaks(w)
    check(len(picos) >= 1, "el pico que el DI ya detectó llega al discriminador", len(picos))
    if not picos:
        return
    pk = min(picos, key=lambda p: abs(p["largo"] - 6.00))
    check(abs(pk["largo"] - 6.00) < 0.3, "y está donde se inyectó", pk["largo"])
    check(pk["clase"] == "fractura", "se clasifica como FRACTURA", pk)
    sig = pk["firma"]
    check(sig["delta_pd_rel"] < 0, "la firma registra que el dámper CAE", sig["delta_pd_rel"])
    check(sig["delta_pp_rel"] < 0, "que la percusión cae", sig["delta_pp_rel"])
    check(sig["delta_vel_rel"] > 0, "y que la velocidad aumenta", sig["delta_vel_rel"])
    check(pk.get("evidencia"), "la clasificación viene con su evidencia, no sola", pk.get("evidencia"))


def firma_de_contacto():
    section("8 — Firma de contacto: dámper NO cae, todo lo demás se desestabiliza")
    reset()
    w = _well_base("W2", seed=2)
    _inyecta_contacto(w, 6.00)

    picos = gw.discriminate_peaks(w)
    check(len(picos) >= 1, "el pico llega al discriminador", len(picos))
    if not picos:
        return
    pk = min(picos, key=lambda p: abs(p["largo"] - 6.00))
    check(pk["clase"] == "contacto", "se clasifica como CONTACTO", pk)
    sig = pk["firma"]
    check(abs(sig["delta_pd_rel"]) < gw.DISC_CAIDA_REL,
          "la firma registra que el dámper NO cae", sig["delta_pd_rel"])
    check(sig["cv_pp_rel"] > 1.0, "que la percusión se desestabiliza", sig["cv_pp_rel"])
    check(sig["cv_pr_rel"] > 1.0, "que la rotación varía fuerte", sig["cv_pr_rel"])
    check(sig["cv_vel_rel"] > 1.0, "y que la velocidad pierde su patrón", sig["cv_vel_rel"])


def sin_firma_queda_indeterminado():
    section("8 — Un pico sin firma clara queda INDETERMINADO, no se le inventa clase")
    reset()
    w = _well_base("W3", seed=3)
    # DI alto pero sin ninguna de las dos firmas: nada cae, nada se desestabiliza.
    for i in range(_idx(w, 5.9), _idx(w, 6.1) + 1):
        w.points[i].di = 2.5

    picos = gw.discriminate_peaks(w)
    check(len(picos) >= 1, "el pico se procesa igual", len(picos))
    if not picos:
        return
    pk = min(picos, key=lambda p: abs(p["largo"] - 6.00))
    check(pk["clase"] == "indeterminado",
          "y se declara indeterminado en vez de caer a un default", pk["clase"])
    check(pk.get("motivo"), "explicando qué firma faltó", pk.get("motivo"))


def dos_clases_en_el_mismo_pozo():
    section("8 — Los dos eventos en un mismo pozo se separan")
    reset()
    w = _well_base("W4", n=900, seed=4)
    _inyecta_fractura(w, 4.00)
    _inyecta_contacto(w, 12.00, seed=41)

    picos = gw.discriminate_peaks(w)
    por_largo = {round(p["largo"]): p["clase"] for p in picos}
    check(any(abs(p["largo"] - 4.0) < 0.3 and p["clase"] == "fractura" for p in picos),
          "el de 4 m sale fractura", por_largo)
    check(any(abs(p["largo"] - 12.0) < 0.3 and p["clase"] == "contacto" for p in picos),
          "el de 12 m sale contacto", por_largo)

    rep = gw.discriminate_all()
    check(rep["status"] == "ok", "el reporte agregado corre", rep.get("motivo"))
    check(rep["conteo"]["fractura"] >= 1 and rep["conteo"]["contacto"] >= 1,
          "y cuenta las dos clases", rep.get("conteo"))
    check("indeterminado" in rep["conteo"],
          "declarando también los indeterminados, no los esconde", list(rep["conteo"]))


def etiquetas_de_sondaje():
    section("8 — Contraste contra las etiquetas de sondaje (estructuras y contactos P2)")
    reset()
    w = _well_base("W5", n=900, seed=5)
    _inyecta_fractura(w, 4.00)
    _inyecta_contacto(w, 12.00, seed=51)
    # Sondaje vertical a 1,5 m del pozo: estructura logueada a 4 m de
    # profundidad y cambio de unidad a 12 m.
    _sondaje("DH1", E0 + 1.5, N0, Z0, estructuras_m=(4.0,), contactos=((12.0, "Bht"),))
    gw.refresh_drillhole_contacts()

    rep = gw.discriminator_report(radio_m=3.0)
    check(rep["status"] == "ok", "el contraste corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    check(rep["n_pares"] >= 2, "aparea los picos con las etiquetas cercanas", rep.get("n_pares"))
    check("matriz" in rep, "y arma la matriz de confusión", list(rep))
    check(rep["cobertura"]["picos_sin_etiqueta"] is not None,
          "declarando cuántos picos quedaron SIN etiqueta cercana",
          rep.get("cobertura"))
    check(rep["radio_m"] == 3.0, "y con qué radio se apareó", rep.get("radio_m"))
    aciertos = rep.get("aciertos")
    check(aciertos is not None and aciertos >= 1,
          "acierta al menos la fractura y el contacto inyectados",
          f"aciertos={aciertos} matriz={rep.get('matriz')}")


def sin_etiquetas_no_hay_matriz():
    section("8 — Sin sondaje cerca: se declara, no se fabrica una matriz")
    reset()
    w = _well_base("W6", seed=6)
    _inyecta_fractura(w, 6.00)
    # Sondaje a 300 m: fuera de cualquier radio razonable.
    _sondaje("DH_lejos", E0 + 300.0, N0, Z0, estructuras_m=(6.0,))

    rep = gw.discriminator_report(radio_m=3.0)
    check(rep["status"] == "sin_etiquetas",
          "el reporte se declara sin etiquetas", rep.get("status"))
    check(rep.get("matriz") is None,
          "y NO entrega matriz de confusión inventada", rep.get("matriz"))
    check(rep.get("motivo"), "explicando por qué", rep.get("motivo"))


def rqd_mwd_por_definicion_de_deere():
    section("8 — RQD_MWD: % del metraje en tramos continuos ≥ 10 cm sin discontinuidad")
    reset()
    # Pozo de 6,00 m (300 puntos a 2 cm). Dos discontinuidades: uno de los
    # tramos resultantes mide menos de 10 cm y NO debe sumar.
    w = _well_base("W7", n=300, seed=7)
    for i in range(_idx(w, 2.00), _idx(w, 2.06) + 1):   # discontinuidad ancha
        w.points[i].di = 2.5
    for i in range(_idx(w, 2.10), _idx(w, 2.16) + 1):   # deja un hueco de ~4 cm
        w.points[i].di = 2.5

    r = gw.rqd_mwd_well(w)
    check(r is not None, "se calcula", r)
    if r is None:
        return
    check(0.0 <= r["rqd_mwd"] <= 100.0, "es un porcentaje", r["rqd_mwd"])
    check(r["tramo_min_m"] == gw.RQD_TRAMO_MIN_M,
          "con el umbral de Deere de 10 cm declarado", r.get("tramo_min_m"))
    check(r["n_tramos_descartados"] >= 1,
          "y descarta el tramo de 4 cm que quedó entre las dos discontinuidades",
          r.get("n_tramos_descartados"))
    # El metraje descontado es el de las discontinuidades más el tramo corto:
    # el RQD tiene que quedar por debajo del 100% pero claramente alto.
    check(80.0 <= r["rqd_mwd"] < 100.0,
          "el valor cae donde manda la construcción del pozo", r["rqd_mwd"])

    # Pozo sin ninguna discontinuidad: RQD 100%.
    w2 = _well_base("W8", n=300, seed=8)
    r2 = gw.rqd_mwd_well(w2)
    check(abs(r2["rqd_mwd"] - 100.0) < 1e-6,
          "un pozo sin discontinuidades da RQD_MWD = 100%", r2["rqd_mwd"])


def rqd_mwd_agregado():
    section("8 — RQD_MWD agregado por pozo y por caserón")
    reset()
    for k in range(3):
        w = _well_base(f"WA{k}", n=400, seed=10 + k)
        for i in range(_idx(w, 3.0), _idx(w, 3.1) + 1):
            w.points[i].di = 2.5
    rep = gw.rqd_mwd_report()
    check(rep["status"] == "ok", "el reporte corre", rep.get("motivo"))
    check(len(rep["pozos"]) == 3, "hay un valor por pozo", len(rep.get("pozos", [])))
    check("CAS_A" in rep["caserones"], "y un agregado por caserón", list(rep.get("caserones", {})))
    cas = rep["caserones"]["CAS_A"]
    check(cas["n_pozos"] == 3, "que declara sobre cuántos pozos se agregó", cas)
    check("rqd_mwd" in cas and 0 <= cas["rqd_mwd"] <= 100,
          "con el RQD del caserón", cas.get("rqd_mwd"))
    check("orientado a tronadura" in (rep.get("uso") or "").lower(),
          "declarando que es indicador agregado orientado a tronadura", rep.get("uso"))


def el_di_sigue_siendo_la_variable_de_trabajo():
    section("8 — Esta sesión NO toca el DI ni el modelo de caracterización")
    reset()
    w = _well_base("W9", seed=9)
    _inyecta_fractura(w, 6.00)
    gw.discriminate_peaks(w)
    gw.rqd_mwd_report()
    check(gw.di_config_is_default(),
          "la configuración del DI sigue en sus valores de convención",
          gw.di_config_summary())
    check(gw.di_config["window"] == 14 and gw.di_threshold == 1.5,
          "ventana 14 y umbral 1,5 intactos",
          (gw.di_config["window"], gw.di_threshold))
    check(gw.ML_FEATURES == ["vel", "pp", "pa", "pd", "pr", "pf", "se"],
          "y ML_FEATURES intacto: el discriminador es posterior, no un predictor",
          gw.ML_FEATURES)


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    firma_de_fractura,
    firma_de_contacto,
    sin_firma_queda_indeterminado,
    dos_clases_en_el_mismo_pozo,
    etiquetas_de_sondaje,
    sin_etiquetas_no_hay_matriz,
    rqd_mwd_por_definicion_de_deere,
    rqd_mwd_agregado,
    el_di_sigue_siendo_la_variable_de_trabajo,
]


def test_s8_discriminador():
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
    print("✓ SESIÓN 8 — todas las verificaciones pasaron.")
    print("=" * 72)
