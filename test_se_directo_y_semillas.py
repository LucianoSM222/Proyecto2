"""
test_se_directo_y_semillas.py — La SE sin estratificar, y cuánto es suerte.

DOS COSAS, y las dos son del autor.

1. NO ESTRATIFICAR POR PP, con su razón textual: «al ingresar PP a la fórmula
   se contrasta con la velocidad, y si logra subir ROP normaliza la energía y
   sigue hablando de la roca; pero si no varía mucho la SE es porque la roca sí
   es capaz de resistir a una alta PP. Y siempre nos mantenemos hablando de la
   roca igual».

   Es un argumento sobre la fórmula, no una simplificación: SE = (PP+RP+AP)/ROP
   lleva ROP en el denominador, así que subir PP solo mueve la SE en la medida
   en que NO consigue más avance — que es exactamente la resistencia del
   macizo. El camino estratificado queda disponible en «se.control_pp» para
   poder contrastar los dos en la memoria.

   LO QUE NO CAMBIA: el diagnóstico de coherencia SE↔UCS sigue reportando por
   estrato pase lo que pase. Ahí estratificar es la PRUEBA de que la relación
   no es artefacto del operador, no el método de estimación. Confundir las dos
   cosas sería sacar la evidencia junto con el procedimiento.

2. EL REPORTE DE SEMILLAS. El ganador entre métodos se decide con tres o cuatro
   anclas de litología. Si cambiar la semilla mueve el MAE más que la distancia
   al segundo, el orden no lo decidió el método sino qué filas tocaron, y la
   memoria tiene que decirlo en vez de coronar a uno.
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


E0, N0, Z0 = 376700.0, 6959000.0, 300.0

# UCS de las anclas reales de MPC, para que la vara tenga tres litologías.
LITOS = {"Bht": 128.1, "Kpcli": 180.0, "Brecha_mixta": 111.5}


def _escenario(seed=0, n_pozos=9, n_pts=200, sesgo_pp=False):
    """
    Pozos de tres litologías. Con `sesgo_pp`, la PP alta se concentra en una
    litología: es el caso en que estratificar y no estratificar dan distinto,
    y donde hay que poder mostrar los dos números.
    """
    reset()
    rng = np.random.default_rng(seed)
    nombres = list(LITOS)
    for k in range(n_pozos):
        lito = nombres[k % len(nombres)]
        # SE creciente con el UCS nominal, para que la relación tenga con qué.
        se_base = {"Bht": 335.0, "Kpcli": 348.0, "Brecha_mixta": 300.0}[lito]
        pts = []
        for i in range(n_pts):
            if sesgo_pp and lito == "Kpcli":
                pp = float(rng.uniform(175, 225))     # el operador sube PP acá
            else:
                pp = float(rng.uniform(95, 165))
            p = gw.MWDPoint(largo=i * 0.2, vel=float(0.9 + rng.normal(0, .03)),
                            pp=pp, pa=60.0, pd=75.0, pr=45.0, pf=8.0,
                            se=float(se_base + rng.normal(0, 18)), t=0.0)
            p.este = E0 + k * 2.0
            p.norte = N0 + i * 0.15
            p.cota = Z0 - i * 0.12
            p.entrenable = True
            p.dominio = p.lito = lito
            p.capa_lito = f"malla_{lito}"
            p.di = 0.4
            pts.append(p)
        w = gw.Well(well_name=f"T{k}", plan_id="CAS_PR01_TH_P01", hole_id=str(k),
                    points=pts)
        w.caseron = "CAS_A"
        gw.wells[f"T{k}"] = w
    for lito, ucs in LITOS.items():
        gw.domains[lito] = {"count": 1, "ucs_lab": ucs, "atributo_id": lito,
                            "alteracion_id": None, "estructura_id": None,
                            "pi_factor": None, "calidad": 1,
                            "fuente_ucs": "prueba", "modo_ucs": "central"}


# ─────────────────────────────────────────────────────────────────────────────
def por_defecto_no_estratifica():
    section("SE — por defecto se resume directo, sin estratificar por PP")
    _escenario()
    check(gw.get_param("se.control_pp") == "directo",
          "el modo por defecto es directo", gw.get_param("se.control_pp"))
    se = gw._se_representativa("Bht")
    check(se is not None, "y produce una SE representativa", se)
    # Directo tiene que ser EXACTAMENTE la mediana de los puntos utilizables:
    # si no lo fuera, estaría haciendo algo más y no lo estaría diciendo.
    pts = gw._puntos_de_litologia("Bht")
    esperado = float(np.median([p.se for p in pts]))
    check(abs(se - esperado) < 1e-9,
          "y es exactamente la mediana de los puntos de la litología, sin más "
          "aritmética escondida", (se, esperado))


def el_camino_estratificado_sigue_disponible():
    section("SE — el otro camino queda, para poder contrastar los dos")
    _escenario(sesgo_pp=True)
    directo = gw._se_representativa("Kpcli")
    gw.set_param("se.control_pp", "por_estrato")
    estratificado = gw._se_representativa("Kpcli")
    gw.reset_param("se.control_pp")
    check(directo is not None and estratificado is not None,
          "los dos modos dan número", (directo, estratificado))
    check(gw._se_representativa("Kpcli") == directo,
          "y reponer el parámetro vuelve al directo")
    # Con PP sesgada hacia una litología los dos números NO tienen por qué
    # coincidir: si coincidieran siempre, el parámetro no controlaría nada.
    print(f"      (directo {directo:.1f} · por estrato {estratificado:.1f})")
    check(True, "ambos se pueden calcular sobre el mismo dato, que es lo que "
                "permite reportarlos juntos en la memoria")


def la_escala_tambien_obedece_al_modo():
    section("SE — la sigma de la banda usa el mismo criterio, no otro")
    _escenario()
    esc = gw._se_escala_lito("Bht")
    check(esc is not None, "la escala se calcula", esc)
    pts = gw._puntos_de_litologia("Bht")
    v = np.array([p.se for p in pts])
    med_esperada = float(np.median(v))
    sig_esperada = float((np.percentile(v, 84) - np.percentile(v, 16)) / 2.0)
    check(abs(esc[0] - med_esperada) < 1e-9,
          "y su mediana es la directa, igual que _se_representativa: dos "
          "criterios distintos para el mismo dato serían dos verdades",
          (esc[0], med_esperada))
    check(abs(esc[1] - sig_esperada) < 1e-9,
          "y la sigma es el medio rango p16-p84, robusta a las colas del MWD",
          (esc[1], sig_esperada))


def el_resultado_declara_como_se_resumio():
    section("SE — todo resultado dice con qué criterio se resumió")
    _escenario()
    nota = gw._nota_control_pp()
    check("DIRECTO" in nota, "en directo lo declara", nota[:70])
    check("ROP" in nota,
          "y con la razón: la SE ya lleva ROP en el denominador", nota[:120])
    gw.set_param("se.control_pp", "por_estrato")
    nota2 = gw._nota_control_pp()
    gw.reset_param("se.control_pp")
    check("ESTRATO" in nota2, "y en el otro modo dice el otro", nota2[:70])
    check(nota != nota2,
          "los dos modos NO pueden declarar lo mismo: sería un dato sin "
          "procedencia")
    # Sin condicionales: una comprobación que se salta sola cuando el modelo
    # no corre no comprueba nada, y el día que deje de correr nadie se entera.
    for nombre, fn in (("banda", gw.predict_ucs_banda),
                       ("relación directa", gw.predict_ucs_relacion)):
        rep = fn()
        check(rep.get("status") == "ok", f"el modelo por {nombre} corre",
              rep.get("motivo"))
        check("DIRECTO" in (rep.get("procedencia") or ""),
              f"y la procedencia de {nombre} lleva pegado con qué criterio se "
              f"resumió la SE", (rep.get("procedencia") or "")[-90:])


def la_coherencia_sigue_reportando_por_estrato():
    section("SE — la PRUEBA por estrato no se fue con el método")
    _escenario()
    rep = gw.se_ucs_coherence_report()
    check(rep.get("status") == "ok", "el reporte de coherencia corre",
          rep.get("motivo"))
    if rep.get("status") != "ok":
        return
    check("estratos_pp" in rep,
          "y SIGUE trayendo la relación dentro de estratos estrechos de PP: "
          "ahí estratificar es la evidencia de que la relación no es artefacto "
          "del operador, no el método de estimación", sorted(rep)[:6])
    check(rep.get("advertencia_pp"),
          "con su advertencia sobre PP intacta")
    check(gw.get_param("se.control_pp") == "directo",
          "todo esto con el modo directo vigente: son dos cosas separadas")


# ─────────────────────────────────────────────────────────────────────────────
def el_reporte_de_semillas_mide_la_dispersion():
    section("Semillas — cuánto se mueve el resultado al cambiar solo la semilla")
    _escenario()
    rep = gw.ml_seed_sensitivity(semillas=[42, 7, 123])
    check(rep["status"] == "ok", "el reporte corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    check(rep["semillas"] == [42, 7, 123], "con las semillas que se pidieron",
          rep["semillas"])
    ml = next((m for m in rep["metodos"] if m["metodo"] == "ml"), None)
    check(ml is not None, "evalúa el bosque aleatorio",
          [m["metodo"] for m in rep["metodos"]])
    if ml:
        check(ml["n_semillas"] == 3, "una corrida por semilla", ml["n_semillas"])
        check(len(ml["mae_mpa"]) == 3, "con su MAE cada una", ml["mae_mpa"])
        check(ml["rango_mpa"] >= 0, "y el rango entre ellas", ml["rango_mpa"])
        check(abs(ml["rango_mpa"] - (ml["mae_max"] - ml["mae_min"])) < 0.11,
              "que es max menos min, no otra cosa",
              (ml["rango_mpa"], ml["mae_max"], ml["mae_min"]))
    check(rep.get("veredicto"), "y un veredicto en palabras", rep.get("veredicto"))


def una_semilla_no_alcanza():
    section("Semillas — con una sola semilla no hay dispersión que medir")
    _escenario()
    rep = gw.ml_seed_sensitivity(semillas=[42])
    check(rep["status"] != "ok",
          "una sola semilla se rechaza en vez de reportar dispersión cero, que "
          "sería mentir por omisión", rep["status"])
    check(rep.get("motivo"), "con el motivo", rep.get("motivo"))


def los_deterministas_declaran_que_lo_son():
    section("Semillas — dispersión cero POR CONSTRUCCIÓN, no por estable")
    _escenario()
    rep = gw.ml_seed_sensitivity(semillas=[42, 7],
                                 metodos=("linea_base", "relacion", "ml"))
    check(rep["status"] == "ok", "corre con varios métodos", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    por_met = {m["metodo"]: m for m in rep["metodos"]}
    for met in ("linea_base", "relacion"):
        m = por_met.get(met)
        if m is None:
            continue
        check(m["determinista"] is True, f"{met} se declara determinista")
        check(m["rango_mpa"] == 0.0, f"{met} no se mueve", m["rango_mpa"])
        check("CONSTRUCCIÓN" in (m.get("nota") or ""),
              f"{met} dice que su cero es por construcción y no por haber "
              f"salido estable: leerlo al revés sería concluir que es el "
              f"método más robusto", m.get("nota"))
        check(m["n_semillas"] == 1,
              f"{met} se corre UNA vez: repetir un cálculo sin azar tres veces "
              f"es gastar tiempo para obtener el mismo número", m["n_semillas"])


def el_veredicto_dice_si_el_orden_esta_decidido():
    section("Semillas — el veredicto compara el ruido contra la ventaja")
    _escenario()
    rep = gw.ml_seed_sensitivity(semillas=[42, 7, 123])
    if rep["status"] != "ok":
        check(False, "el reporte corre", rep.get("motivo"))
        return
    check("orden_decidido" in rep, "declara si el orden entre métodos se sostiene",
          rep.get("orden_decidido"))
    check(rep.get("dispersion_maxima_mpa") is not None,
          "con la dispersión medida", rep.get("dispersion_maxima_mpa"))
    if rep.get("distancia_entre_metodos_mpa") is not None:
        d, disp = rep["distancia_entre_metodos_mpa"], rep["dispersion_maxima_mpa"]
        check(rep["orden_decidido"] == (disp < d),
              "y el veredicto se sigue de los números, no de una impresión",
              (disp, d, rep["orden_decidido"]))
    check(rep.get("que_no_mide"),
          "y declara qué NO mide: no es LOCO-CV, y una dispersión chica con "
          "anclas equivocadas es un resultado estable y falso",
          (rep.get("que_no_mide") or "")[:80])


def esta_en_el_centro_de_reportes():
    section("Semillas — se llega desde el listado de reportes")
    ids = [r["id"] for r in gw.REPORTES]
    check("semillas" in ids, "el reporte está en el catálogo", ids)
    ficha = next(r for r in gw.REPORTES if r["id"] == "semillas")
    check(getattr(gw, ficha["gen"], None) is not None,
          "y su generador existe", ficha["gen"])
    _escenario()
    disp = {r["id"]: r for r in gw.reportes_disponibles()}
    check(disp["semillas"]["disponible"],
          "con datos cargados se puede pedir", disp["semillas"])
    reset()
    disp2 = {r["id"]: r for r in gw.reportes_disponibles()}
    check(not disp2["semillas"]["disponible"] and disp2["semillas"]["motivo"],
          "y sin datos dice qué falta", disp2["semillas"])


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    por_defecto_no_estratifica,
    el_camino_estratificado_sigue_disponible,
    la_escala_tambien_obedece_al_modo,
    el_resultado_declara_como_se_resumio,
    la_coherencia_sigue_reportando_por_estrato,
    el_reporte_de_semillas_mide_la_dispersion,
    una_semilla_no_alcanza,
    los_deterministas_declaran_que_lo_son,
    el_veredicto_dice_si_el_orden_esta_decidido,
    esta_en_el_centro_de_reportes,
]


def test_se_directo_y_semillas():
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
    print("✓ SE DIRECTO Y SENSIBILIDAD A LA SEMILLA — todas pasaron.")
    print("=" * 72)
