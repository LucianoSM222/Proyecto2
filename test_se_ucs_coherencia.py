"""
test_se_ucs_coherencia.py — Coherencia física entre energía específica y UCS
de laboratorio, sobre roca intacta.

Propuesto por el autor como el análisis que de verdad sostiene la
plataforma, y ejecutado ANTES del ML, no después: es un test de validez del
supuesto fundamental. Si la SE de los pozos que caen en litologías con UCS
bien conocido por ensayo no ordena esas litologías por resistencia, entonces
el MWD no está midiendo lo que creemos y ningún modelo lo arregla.

Separa dos preguntas que hoy están confundidas en el R² del modelo:
  · ¿el MWD tiene señal física?        -> esto
  · ¿las etiquetas alcanzan para entrenar? -> el R² y el LOCO-CV

Y entrega un segundo resultado que valida el DI empíricamente: la MISMA
comparación con y sin apartar las discontinuidades. Si apartarlas mejora la
coherencia, el DI deja de ser un índice aplicado por autoridad (Fernández et
al. 2023) y pasa a ser algo que demostró servir en estos datos.

LA TRAMPA que el análisis debe sortear: SE_reacción = (PP + RP + AP) / ROP, y
PP es la ÚNICA variable que el operador manipula — y la sube en roca dura.
Parte de la correlación SE↔UCS podría venir de la RESPUESTA DEL OPERADOR y no
de la roca. Por eso el reporte estratifica por PP y mira ROP por separado:
ROP no se fija directamente, así que si también ordena las litologías, la
señal es de la roca.
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
    gw.attribute_exclusions.clear(); gw.drillholes.clear()
    gw.set_training_caserones(None)


def _mk_pozo(wn, dominio, se_medio, n=60, di_alto_frac=0.0, pp_medio=150.0,
             rop_medio=1.0, seed=0):
    """
    Pozo sintético cuyo SE se controla directamente. `di_alto_frac` marca esa
    fracción de puntos como discontinuidad (DI sobre el umbral).
    """
    rng = np.random.default_rng(seed)
    pts = []
    for i in range(n):
        es_disc = i < int(n * di_alto_frac)
        # En discontinuidad el SE se desploma: la broca avanza sin romper
        # matriz. Es la firma que el DI existe para apartar.
        se = float(rng.normal(se_medio * (0.35 if es_disc else 1.0), se_medio * 0.06))
        p = gw.MWDPoint(largo=i * 0.02, vel=rop_medio, pp=pp_medio, pa=50.0,
                        pd=40.0, pr=30.0, pf=8.0, se=se, t=0.0)
        p.dominio = dominio; p.lito = dominio; p.entrenable = True
        p.di = 3.0 if es_disc else 0.4
        pts.append(p)
    w = gw.Well(well_name=wn, plan_id=f"CAS_PR01_TH_{wn}", hole_id=wn, points=pts)
    w.caseron = "CAS_A"
    gw.wells[wn] = w
    return w


def _escenario_coherente(di_alto_frac=0.0):
    """
    Tres litologías con UCS de laboratorio conocido y SE proporcional: es el
    caso en que la física SÍ se cumple y el reporte debe confirmarlo.
    """
    reset()
    for dom, ucs in (("Kpcsb_sedimentaria", 83.6), ("Bht", 128.1), ("Kpcli", 190.0)):
        gw.domains[dom] = {"ucs_lab": ucs, "atributo_id": dom, "nombre": dom}
    _mk_pozo("W1", "Kpcsb_sedimentaria", se_medio=100.0, di_alto_frac=di_alto_frac, seed=1)
    _mk_pozo("W2", "Bht", se_medio=160.0, di_alto_frac=di_alto_frac, seed=2)
    _mk_pozo("W3", "Kpcli", se_medio=240.0, di_alto_frac=di_alto_frac, seed=3)


# ─────────────────────────────────────────────────────────────────────────────
def coherencia_se_detecta_la_relacion():
    section("SE↔UCS — detecta la coherencia cuando la física se cumple")
    _escenario_coherente()
    rep = gw.se_ucs_coherence_report()
    check(rep["status"] == "ok", "el reporte corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    check(len(rep["dominios"]) == 3, "reporta los tres dominios", len(rep["dominios"]))
    for d in rep["dominios"]:
        check(set(("dominio", "ucs_lab", "se_mediana", "n")) <= set(d),
              "cada dominio trae UCS de lab, SE mediana y n", d); break
    check(rep["rho_spearman"] is not None and rep["rho_spearman"] > 0.9,
          "la correlación de rangos SE↔UCS es fuerte y positiva", rep.get("rho_spearman"))
    check(rep["monotona"] is True,
          "y el orden de SE respeta el orden de UCS (monotonía)", rep.get("monotona"))
    check("coheren" in rep["veredicto"].lower(),
          "el veredicto lo declara en palabras, no solo con un número", rep["veredicto"])


def coherencia_detecta_la_incoherencia():
    section("SE↔UCS — NO da coherencia cuando la física no se cumple")
    reset()
    for dom, ucs in (("Kpcsb_sedimentaria", 83.6), ("Bht", 128.1), ("Kpcli", 190.0)):
        gw.domains[dom] = {"ucs_lab": ucs, "atributo_id": dom, "nombre": dom}
    # SE al REVÉS del UCS: la roca más dura sale con menos energía específica.
    _mk_pozo("W1", "Kpcsb_sedimentaria", se_medio=240.0, seed=1)
    _mk_pozo("W2", "Bht", se_medio=160.0, seed=2)
    _mk_pozo("W3", "Kpcli", se_medio=100.0, seed=3)
    rep = gw.se_ucs_coherence_report()
    check(rep["status"] == "ok", "el reporte corre igual")
    check(rep["rho_spearman"] < 0, "la correlación sale NEGATIVA", rep.get("rho_spearman"))
    check(rep["monotona"] is False, "y la monotonía se rompe")
    check("incoheren" in rep["veredicto"].lower() or "invert" in rep["veredicto"].lower(),
          "el veredicto lo dice claramente, no lo suaviza", rep["veredicto"])


def apartar_discontinuidades_mejora():
    section("SE↔UCS — apartar las discontinuidades MEJORA la coherencia (valida el DI)")
    # 40% de los puntos son discontinuidad, con SE desplomado: ensucian la
    # relación si no se apartan.
    _escenario_coherente(di_alto_frac=0.4)
    rep = gw.se_ucs_coherence_report()
    check(rep["status"] == "ok", "el reporte corre")
    if rep["status"] != "ok":
        return
    check("sin_apartar_discontinuidades" in rep,
          "el reporte trae la MISMA comparación sin apartar discontinuidades",
          list(rep))
    comp = rep["sin_apartar_discontinuidades"]
    check("se_mediana_por_dominio" in comp or "dominios" in comp,
          "con sus propias medianas por dominio", list(comp))
    check("di_mejora_coherencia" in rep,
          "y el veredicto explícito sobre si el DI ayudó", list(rep))
    # Apartar discontinuidades debe reducir la dispersión dentro del dominio.
    check(rep["cv_medio_intra_dominio"] <= comp["cv_medio_intra_dominio"] + 1e-9,
          "la dispersión intra-dominio baja al apartar las discontinuidades",
          (rep["cv_medio_intra_dominio"], comp["cv_medio_intra_dominio"]))


def controla_el_confundimiento_de_pp():
    section("SE↔UCS — controla el confundimiento del operador (PP) y mira ROP")
    _escenario_coherente()
    rep = gw.se_ucs_coherence_report()
    check("estratos_pp" in rep,
          "estratifica por PP: PP es la ÚNICA variable que el operador manipula, "
          "y la sube en roca dura", list(rep))
    check("rop" in rep,
          "y reporta ROP por separado, que el operador NO fija directamente",
          list(rep))
    check("advertencia_pp" in rep and rep["advertencia_pp"],
          "el reporte declara el riesgo de confundimiento, no lo omite",
          rep.get("advertencia_pp"))


def aparta_dominios_de_estructura():
    section("SE↔UCS — un dominio de FALLA no es roca intacta: queda fuera")
    _escenario_coherente()
    # Dominio compuesto donde predomina una estructura (A.5). Hereda el
    # ucs_lab de la litología, pero por definición NO es roca intacta: es
    # justo lo contrario, y mezclarlo destruye el análisis.
    gw.domains["Bht::CAS:FM1"] = {"ucs_lab": 128.1, "atributo_id": "Bht",
                                  "estructura_id": "FM1", "nombre": "Bht::CAS:FM1"}
    _mk_pozo("W4", "Bht::CAS:FM1", se_medio=600.0, seed=9)   # SE disparatado
    rep = gw.se_ucs_coherence_report()
    doms = [d["dominio"] for d in rep["dominios"]]
    check("Bht::CAS:FM1" not in doms,
          "el dominio con estructura NO entra al análisis de roca intacta", doms)
    check("n_dominios_estructura_apartados" in rep,
          "y el reporte declara cuántos apartó", list(rep))
    check(rep["n_dominios_estructura_apartados"] >= 1,
          "contándolos, no descartándolos en silencio",
          rep.get("n_dominios_estructura_apartados"))
    check(rep["rho_spearman"] > 0.9,
          "apartándolos, la coherencia real vuelve a verse", rep.get("rho_spearman"))


def excluye_rop_no_fisica():
    section("SE↔UCS — ROP tendiendo a 0 hace explotar SE: se excluye por límite físico")
    _escenario_coherente()
    # Un puñado de puntos con la broca detenida: ROP ~0 y SE astronómico.
    w = gw.wells["W2"]
    for i in range(5):
        p = gw.MWDPoint(largo=99 + i * 0.02, vel=1e-9, pp=150.0, pa=50.0, pd=40.0,
                        pr=30.0, pf=8.0, se=(150.0 + 30.0 + 50.0) / (1e-9 + 1e-9), t=0.0)
        p.dominio = "Bht"; p.lito = "Bht"; p.entrenable = True; p.di = 0.4
        w.points.append(p)

    rep = gw.se_ucs_coherence_report()
    check("n_puntos_rop_no_fisica" in rep,
          "el reporte declara cuántos puntos excluyó por ROP no física", list(rep))
    check(rep["n_puntos_rop_no_fisica"] >= 5,
          "y los cuenta, no los descarta en silencio", rep.get("n_puntos_rop_no_fisica"))
    bht = next(d for d in rep["dominios"] if d["dominio"] == "Bht")
    check(bht["se_mediana"] < 1e4,
          "la SE del dominio no queda contaminada por la broca detenida",
          bht["se_mediana"])
    check(rep["rho_spearman"] > 0.9, "y la coherencia real se sigue viendo",
          rep.get("rho_spearman"))
    # El límite es FÍSICO y trazable, no un percentil (prohibido en el proyecto).
    check(hasattr(gw, "ROP_MIN_FISICA"), "el umbral vive en una constante declarada")


def sin_datos_lo_declara():
    section("SE↔UCS — sin datos suficientes lo declara, no inventa")
    reset()
    rep = gw.se_ucs_coherence_report()
    check(rep["status"] == "sin_datos", "sin dominios con UCS lo declara", rep.get("status"))
    check(rep.get("motivo"), "y explica qué falta")

    # Un solo dominio: no hay nada que ordenar.
    reset()
    gw.domains["Bht"] = {"ucs_lab": 128.1, "atributo_id": "Bht", "nombre": "Bht"}
    _mk_pozo("W1", "Bht", se_medio=160.0, seed=1)
    rep = gw.se_ucs_coherence_report()
    check(rep["status"] == "sin_datos",
          "con un solo dominio no se puede hablar de coherencia", rep.get("status"))
    check("2" in (rep.get("motivo") or "") or "dos" in (rep.get("motivo") or "").lower(),
          "y dice que hacen falta al menos dos", rep.get("motivo"))


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    coherencia_se_detecta_la_relacion,
    coherencia_detecta_la_incoherencia,
    apartar_discontinuidades_mejora,
    controla_el_confundimiento_de_pp,
    aparta_dominios_de_estructura,
    excluye_rop_no_fisica,
    sin_datos_lo_declara,
]


def test_se_ucs_coherencia():
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
    print("✓ COHERENCIA SE↔UCS — todas las verificaciones pasaron.")
    print("=" * 72)
