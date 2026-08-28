"""
test_banda_ucs.py — La UCS por punto sale de la BANDA, no de un valor suelto.

EL PLANTEO, en palabras del autor:

    «los modelos deben estar hechos con la banda, pues si se le aplica un valor
    específico va a aprender el número. Sin embargo la realidad es que dentro
    de una misma litología hay rangos de UCS, e incluso a veces se pueden
    escapar de la banda debido a alteraciones. Se podría considerar el valor
    específico de UCS y relacionarlo con la mediana de la SE, y con ello buscar
    la dispersión de la banda sin restringir que una que otra vez se escape.»

Es la respuesta correcta al hallazgo crítico de la auditoría. El objetivo era
la CONSTANTE del dominio —varianza intra-dominio 7e-22, línea base con R²
1,000000 exacto— y con una constante no hay nada que aprender. Mapear la
distribución de SE sobre la banda de UCS le devuelve variación real al
objetivo.

EL MAPEO, y su convención declarada:

    z(p)   = (SE(p) − SE_mediana_lito) / σ_SE_lito
    UCS(p) = UCS_central_lito + z(p) · σ_UCS_lito

Un punto en la SE mediana de su litología recibe exactamente el valor central.
Uno con SE extrema se va lejos, y PUEDE salirse de la banda: eso no se acota,
porque salirse es justamente la señal de alteración que se quiere ver.

DOS BANDAS DISTINTAS, Y NO DAN LO MISMO. Bht documenta una banda de confianza
(100–145, del ajuste Hoek-Brown) y una dispersión observada (64,5–296,9, el
scatter real de las probetas). La que describe «cuánto varía la roca dentro de
la unidad» es la DISPERSIÓN; la de confianza describe cuán bien se conoce la
media, que es otra pregunta. Usar la de confianza aplastaría la variación a un
quinto de la real.

LO QUE ESTE MÉTODO NO HACE, y hay que decirlo: no mejora el error de
dejar-una-litología-fuera. Esa vara mide el valor CENTRAL, y la dispersión no
ayuda ahí. Lo que cambia es que el mapa deja de ser parches planos y que los
apartamientos se vuelven visibles. Son dos bienes distintos.

Y NO SIRVE PARA EL ML. Si la etiqueta es f(SE), y las predictoras del ML
excluyen SE pero incluyen PP, RP, AP y ROP —que determinan SE exactamente—, el
bosque aprendería f y sería una copia peor de la relación directa. Circularidad
lavada a través de la identidad. El ML se queda con la etiqueta central.
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
    gw.seed_di_variants(force=True)
    gw.seed_param_registry(force=True)
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    gw.drillholes.clear(); gw.attribute_exclusions.clear()
    gw.set_training_caserones(None)


E0, N0, Z0 = 376700.0, 6959000.0, 300.0


def _escenario(seed=0):
    """Tres litologías con anclas reales de MPC y SE que las ordena."""
    reset()
    rng = np.random.default_rng(seed)
    anclas = {"Bht": 128.1, "Kpcli": 180.0, "Brecha_mixta": 111.5}
    for k, (lito, ucs) in enumerate(anclas.items()):
        for w_i in range(4):
            pts = []
            for i in range(250):
                pp = float(rng.choice([110.0, 150.0, 200.0]))
                se = ucs * 2.4 + rng.normal(0, 25.0)
                rop = max(0.05, 2.2 - ucs / 180.0 + rng.normal(0, 0.05))
                pa = float(60.0 + rng.normal(0, 3))
                pr = float(se * rop - pp - pa)
                p = gw.MWDPoint(largo=i * 0.02, vel=rop, pp=pp, pa=pa,
                                pd=float(75 + rng.normal(0, 4)), pr=pr,
                                pf=float(8 + rng.normal(0, .5)),
                                se=(pp + pr + pa) / rop, t=0.0)
                p.este = E0 + k * 40.0 + w_i * 3.0
                p.norte = N0; p.cota = Z0 - i * 0.02
                p.entrenable = True; p.dominio = lito; p.lito = lito; p.di = 0.4
                pts.append(p)
            wn = f"{lito}_W{w_i}"
            w = gw.Well(well_name=wn, plan_id=f"CAS_PR01_TH_{lito}",
                        hole_id=wn, points=pts)
            w.caseron = "CAS_A"
            gw.wells[wn] = w
        gw.domains[lito] = {"count": 1000, "ucs_lab": ucs, "atributo_id": lito,
                            "alteracion_id": None, "estructura_id": None,
                            "pi_factor": None, "calidad": 1,
                            "fuente_ucs": "prueba", "modo_ucs": "central"}
    return anclas


# ─────────────────────────────────────────────────────────────────────────────
def la_dispersion_manda_sobre_la_banda_de_confianza():
    section("Banda — la dispersión observada, no la banda de confianza")
    reset()
    bht = gw.attr_registry["Bht"]
    esc = gw.ucs_escala(bht)
    check(esc["status"] == "ok", "Bht tiene escala de UCS", esc.get("motivo"))
    if esc["status"] != "ok":
        return
    # Bht: banda de confianza 100-145 (σ≈11) contra dispersión 64,5-296,9
    # (σ≈58) y cv documentado 0,57 (σ≈73). La de confianza describe cuán bien
    # se conoce la MEDIA; la dispersión, cuánto varía la ROCA.
    check(esc["sigma"] > 30.0,
          "y usa la dispersión: una σ de ~11 sería la banda de confianza, que "
          "aplastaría la variación real a un quinto", esc["sigma"])
    check(any(t in esc["fuente"].lower()
              for t in ("variación", "dispersión", "desviación", "banda")),
          "declarando de dónde salió el ancho", esc["fuente"])
    # Brecha_mixta documenta sd directo: tiene que usarlo.
    bm = gw.ucs_escala(gw.attr_registry["Brecha_mixta"])
    check(abs(bm["sigma"] - 23.6) < 1e-6,
          "Brecha_mixta usa su desviación estándar documentada", bm["sigma"])


def sin_banda_se_deriva_y_se_declara():
    section("Banda — una litología sin banda no queda fuera: se deriva y se dice")
    reset()
    # Kpcli YA NO sirve de ejemplo: el autor confirmó su rango (150-230), y la
    # σ medida resultó 20,0 contra la 20,2 que la derivación había estimado
    # —buena señal para las unidades que sigan sin banda—. Se usa Ka_caliza,
    # que tiene ancla (60 MPa) y ningún rango documentado.
    esc = gw.ucs_escala(gw.attr_registry["Ka_caliza"])
    check(esc["status"] == "ok",
          "Ka_caliza tiene ancla (60) pero ninguna banda: igual recibe escala",
          esc.get("motivo"))
    if esc["status"] != "ok":
        return
    check(esc["derivada"],
          "marcada como DERIVADA, no como medida: quien la lea tiene que saber "
          "que ese ancho no salió de probetas de esta unidad", esc["fuente"])
    # Y una que SÍ tiene banda no se marca como derivada.
    k = gw.ucs_escala(gw.attr_registry["Kpcli"])
    check(not k["derivada"] and abs(k["sigma"] - 20.0) < 1e-6,
          "Kpcli, con su rango 150-230 confirmado, da σ=20,0 medida",
          (k["sigma"], k["derivada"]))
    check(esc["sigma"] > 0, "con una escala utilizable", esc["sigma"])
    check("deriv" in esc["fuente"].lower() or "cv" in esc["fuente"].lower(),
          "y el motivo dice cómo se obtuvo", esc["fuente"])
    # Sin ancla no hay nada que escalar: se declara en vez de inventar.
    esc2 = gw.ucs_escala(gw.attr_registry["DL"])
    check(esc2["status"] != "ok", "sin ancla no hay escala", esc2.get("status"))
    check(esc2.get("motivo"), "con su motivo", esc2.get("motivo"))


def el_valor_por_punto_sale_de_la_banda():
    section("Banda — cada medición cae según su SE dentro de la banda de su unidad")
    _escenario()
    rep = gw.predict_ucs_banda()
    check(rep["status"] == "ok", "la predicción por banda corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    for lito, ancla in (("Bht", 128.1), ("Kpcli", 180.0)):
        vals = np.array([p.ucs_ml for w in gw.wells.values() for p in w.points
                         if p.lito == lito and p.ucs_ml is not None])
        check(len(vals) > 500, f"{lito}: predicho en todos sus puntos", len(vals))
        check(abs(float(np.median(vals)) - ancla) < 6.0,
              f"{lito}: la MEDIANA se queda en el ancla ({ancla})",
              round(float(np.median(vals)), 1))
        check(float(vals.std()) > 5.0,
              f"{lito}: y VARÍA — ya no es la constante del dominio",
              round(float(vals.std()), 1))


def algunos_puntos_se_escapan_de_la_banda():
    section("Banda — se permite escapar: es la señal de alteración")
    _escenario()
    gw.predict_ucs_banda()
    fuera = [p for w in gw.wells.values() for p in w.points
             if p.banda_check in ("sobre", "bajo")]
    check(fuera,
          "hay puntos por fuera de la banda de su unidad: acotarlos borraría "
          "justo lo que se quiere ver", len(fuera))
    dentro = [p for w in gw.wells.values() for p in w.points
              if p.banda_check == "dentro"]
    check(len(dentro) > len(fuera),
          "pero son la minoría: la mayoría cae dentro, que es lo esperable "
          "si el mapeo es sano", (len(dentro), len(fuera)))
    vals = [p.ucs_ml for w in gw.wells.values() for p in w.points
            if p.ucs_ml is not None]
    check(min(vals) >= 0.0 and max(vals) <= 450.0,
          "el único acote que queda es el físico 0-450 MPa",
          (round(min(vals), 1), round(max(vals), 1)))


def un_punto_sin_litologia_igual_recibe_valor():
    section("Banda — sin litología no hay banda: cae a la curva global")
    _escenario()
    w = next(iter(gw.wells.values()))
    for p in w.points[:40]:
        p.lito = None; p.dominio = None
    rep = gw.predict_ucs_banda()
    check(rep["status"] == "ok", "corre igual", rep.get("motivo"))
    huerfanos = [p for p in w.points[:40] if p.ucs_ml is not None]
    check(len(huerfanos) == 40,
          "los puntos sin litología reciben UCS por la curva global: es el caso "
          "de los tiros piloto, donde la litología todavía no se conoce",
          len(huerfanos))
    check(all(p.banda_check == "sin_banda" for p in huerfanos),
          "marcados como sin banda de referencia")
    check(rep.get("n_sin_banda") == 40,
          "y el reporte declara cuántos fueron", rep.get("n_sin_banda"))


def la_vara_no_usa_la_banda_de_la_propia_litologia():
    section("Banda — dejar-una-fuera no puede usar la banda de la excluida")
    _escenario()
    r = gw.leave_one_lithology_out("banda")
    check(r["status"] == "ok", "la vara corre para el método de banda",
          r.get("motivo"))
    if r["status"] != "ok":
        return
    check(r["n_litologias"] == 3, "tres pliegues", r["n_litologias"])
    check(r["mae_mpa"] > 0,
          "y el error NO es cero: si usara la banda de la litología excluida "
          "para predecirla, acertaría por construcción y la vara no valdría "
          "nada", r["mae_mpa"])
    comp = gw.compare_ucs_methods()
    metodos = {m["metodo"] for m in comp["metodos"]}
    check("banda" in metodos, "y compite con los demás bajo la misma vara",
          sorted(metodos))


def la_se_no_fisica_queda_fuera():
    """
    EL DEFECTO QUE ESTE TEST EXISTE PARA IMPEDIR, encontrado sobre datos
    reales: SE = (PP+RP+AP)/ROP, y con ROP tendiendo a cero llegaba a
    3,5e11 bar·min/m. No es una medición, es una división por casi cero.

    Con esos puntos dentro, en el estrato bajo de PP más del 16% de la muestra
    era absurda, la σ robusta de SE explotaba a 3,3e10, y el mapeo devolvía el
    valor CENTRAL para todos los puntos. El síntoma era sutil: la σ del
    resultado parecía sana, pero p10 = p90 = ancla exactamente.

    El reporte de coherencia SE↔UCS ya filtraba por ROP_MIN_FISICA; esta ruta
    no. Dos caminos leyendo lo mismo con reglas distintas.
    """
    section("Banda — la SE no física queda fuera, y se nota")
    _escenario()
    w = next(iter(gw.wells.values()))
    lito = w.points[0].lito
    n_antes = len(gw._puntos_de_litologia(lito))
    # Diez puntos con ROP casi cero: SE se dispara a valores imposibles.
    for p in w.points[:10]:
        p.vel = 1e-6
        p.se = (p.pp + p.pr + p.pa) / p.vel
    check(max(p.se for p in w.points[:10]) > 1e6,
          "el escenario tiene SE imposible", max(p.se for p in w.points[:10]))
    n_despues = len(gw._puntos_de_litologia(lito))
    check(n_despues == n_antes - 10,
          "los diez puntos con ROP no física quedan fuera de la relación",
          (n_antes, n_despues))
    esc = gw._se_escala_lito(lito)
    check(esc is not None and esc[1] < 1e4,
          "y la escala de SE no se contamina: sin el filtro, σ se iba a 1e10",
          esc)
    rep = gw.predict_ucs_banda()
    check(rep["status"] == "ok", "la predicción corre igual", rep.get("motivo"))
    vals = np.array([p.ucs_ml for w2 in gw.wells.values() for p in w2.points
                     if p.lito == lito and p.ucs_ml is not None])
    check(float(np.percentile(vals, 10)) != float(np.percentile(vals, 90)),
          "y el resultado VARÍA: p10 igual a p90 era la firma del defecto",
          (float(np.percentile(vals, 10)), float(np.percentile(vals, 90))))


def el_ml_no_puede_usar_la_banda():
    section("Banda — por qué el ML se queda con la etiqueta central")
    _escenario()
    check(gw.MOTIVO_BANDA_SIN_ML,
          "el motivo está escrito en el código, no solo en una conversación")
    txt = gw.MOTIVO_BANDA_SIN_ML.lower()
    check("se" in txt and ("circul" in txt or "identidad" in txt),
          "y nombra la razón: la etiqueta sería f(SE) y las predictoras del ML "
          "determinan SE exactamente", gw.MOTIVO_BANDA_SIN_ML[:120])
    check("se" not in gw.ML_FEATURES_SIN_SE,
          "SE sigue fuera de las predictoras del ML", gw.ML_FEATURES_SIN_SE)


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    la_dispersion_manda_sobre_la_banda_de_confianza,
    sin_banda_se_deriva_y_se_declara,
    el_valor_por_punto_sale_de_la_banda,
    algunos_puntos_se_escapan_de_la_banda,
    un_punto_sin_litologia_igual_recibe_valor,
    la_vara_no_usa_la_banda_de_la_propia_litologia,
    la_se_no_fisica_queda_fuera,
    el_ml_no_puede_usar_la_banda,
]


def test_banda_ucs():
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
    print("✓ BANDA DE UCS — todas las verificaciones pasaron.")
    print("=" * 72)


# ─────────────────────────────────────────────────────────────────────────────
def las_lavas_se_separan_por_cota():
    """
    Pucobre entrega las Lavas Superiores y las Inferiores con el MISMO nombre
    de malla. La regla del geólogo —inferiores bajo ~320, superiores sobre
    ~400— es lo único que las separa, y es un criterio trazable, no un filtro
    estadístico: por eso se aplica donde la convención prohíbe los percentiles.

    Sobre los datos reales, las Lavas de PCS_1043 caen 35 m sobre el techo de
    las inferiores. Heredaban Kpcli=180 MPa sin que nada lo respaldara: 39.927
    puntos con un ancla prestada.
    """
    section("Lavas — las separa la cota, y la franja intermedia no se adivina")
    reset()
    casos = [("PCC_1541", 300, 329, "Kpcli"),
             ("PCC_0042", 268, 311, "Kpcli"),
             ("PCS_1059", 420, 460, "Kpcls"),
             ("PCS_1043", 341, 363, None)]
    for nom, zmin, zmax, esperado in casos:
        r = gw.clasificar_lavas_por_cota(zmin, zmax)
        check(r["atributo"] == esperado,
              f"{nom} (cota {zmin}-{zmax}) → {esperado or 'sin atributo'}",
              (r["atributo"], r["motivo"]))
    r = gw.clasificar_lavas_por_cota(341, 363)
    check("inventar" in r["motivo"] or "intermedia" in r["motivo"],
          "y la franja intermedia explica POR QUÉ no se asigna", r["motivo"])
    # Kpcls existe y NO tiene ancla: sus puntos no entrenan, y eso se declara.
    kpcls = gw.attr_registry["Kpcls"]
    check(kpcls.ucs_ancla() is None,
          "Lavas Superiores sin ancla: no hay ensayo", kpcls.ucs_ancla())
    check(not kpcls.entrenable()[0], "así que no entrena", kpcls.entrenable())
    # Las cotas son del perfil, no del código.
    for pid in ("lito.cota_lavas_inferiores", "lito.cota_lavas_superiores"):
        check(pid in gw.param_registry, f"{pid} es configurable")
    gw.set_param("lito.cota_lavas_inferiores", 360.0)
    check(gw.clasificar_lavas_por_cota(341, 363)["atributo"] == "Kpcli",
          "y moverlas cambia la clasificación: otra mina, otros niveles")
    gw.seed_param_registry(force=True)


def bht_feldk_es_litologia_propia():
    section("Bht_feldk — litología distinta de Bht, por decisión del autor")
    reset()
    a = gw.attr_registry["Bht_feldk"]
    check(a.rol == "litologia", "es litología", a.rol)
    check((a.ucs_min, a.ucs_max) == (130.0, 180.0),
          "con su banda 130-180 MPa", (a.ucs_min, a.ucs_max))
    check(a.ucs_ancla() == 155.0, "y ancla 155", a.ucs_ancla())
    check(gw.resolve_alias("Bht_feldk") == {"litologia": "Bht_feldk"},
          "la malla resuelve a ella, NO se descompone en Bht + alteración Fk",
          gw.resolve_alias("Bht_feldk"))
    check(gw.attr_registry["Bht"].ucs_ancla() == 128.1,
          "y Bht conserva la suya, separada", gw.attr_registry["Bht"].ucs_ancla())
    # El dique es estructura: no lleva banda y no bloquea el entrenamiento.
    d = gw.attr_registry["Dique"]
    check(d.rol == "estructura", "DQ1 es un dique, rol estructura", d.rol)
    check(gw.resolve_alias("DQ1") == {"estructura": "Dique"},
          "y su malla resuelve ahí", gw.resolve_alias("DQ1"))
    check(d.entrenable()[0],
          "una estructura no necesita banda de UCS para no bloquear")


ALL_TESTS += [las_lavas_se_separan_por_cota, bht_feldk_es_litologia_propia]

def la_no_monotonia_se_declara():
    """
    LA PREMISA DE LA RELACIÓN DIRECTA es que a más SE, más resistencia. Sobre
    los datos reales de MPC NO se cumple: la Brecha mixta tiene la SE más alta
    (445,6) y la UCS más baja (111,5). Ninguna curva monótona pasa por los tres
    puntos, y el error de la relación queda acotado por abajo por esa
    inversión, no por el ajuste.

    Y con tres anclas, dos de los tres pliegues EXTRAPOLAN: dejando fuera la
    Brecha mixta, la curva predijo 450 MPa —el tope físico— contra 111,5
    reales, y el MAE saltó de 53,9 a 151,3. Ese número mide la falta de anclas,
    no el método, y el reporte tiene que decirlo.
    """
    section("Relación — la no monotonía y la extrapolación se declaran")
    reset()
    rng = np.random.default_rng(7)
    # Tres litologías donde la TERCERA invierte la relación, como Brecha_mixta.
    for k, (lito, ucs, se_obj) in enumerate([("Bht", 128.1, 335.0),
                                             ("Kpcli", 180.0, 348.0),
                                             ("Brecha_mixta", 111.5, 446.0)]):
        for w_i in range(3):
            pts = []
            for i in range(200):
                rop = float(0.9 + rng.normal(0, 0.02))
                pp = float(rng.choice([110.0, 150.0, 200.0]))
                pa = 60.0
                pr = se_obj * rop - pp - pa
                p = gw.MWDPoint(largo=i * 0.02, vel=rop, pp=pp, pa=pa, pd=75.0,
                                pr=pr, pf=8.0, se=(pp + pr + pa) / rop, t=0.0)
                p.este = E0 + k * 40.0 + w_i * 3.0; p.norte = N0
                p.cota = Z0 - i * 0.02
                p.entrenable = True; p.dominio = lito; p.lito = lito; p.di = 0.4
                pts.append(p)
            gw.wells[f"{lito}_W{w_i}"] = gw.Well(
                well_name=f"{lito}_W{w_i}", plan_id=f"C_{lito}",
                hole_id=f"{lito}{w_i}", points=pts)
        gw.domains[lito] = {"count": 600, "ucs_lab": ucs, "atributo_id": lito,
                            "alteracion_id": None, "estructura_id": None,
                            "pi_factor": None, "calidad": 1,
                            "fuente_ucs": "prueba", "modo_ucs": "central"}
    mon = gw._monotonia_se_ucs()
    check(mon["status"] == "ok", "la monotonía se evalúa", mon.get("motivo"))
    check(not mon["monotona"],
          "y se detecta que NO es monótona: hay una litología con más SE y "
          "menos UCS", mon.get("orden_por_se"))
    check("Brecha_mixta" in mon["rompen"],
          "nombrando cuál rompe la relación", mon["rompen"])
    check("monótona" in mon["lectura"] or "monotona" in mon["lectura"],
          "con la lectura escrita, no solo el booleano", mon["lectura"][:80])

    c = gw.compare_ucs_methods()
    check(c["status"] == "ok", "la comparación corre", c.get("motivo"))
    check(c.get("aviso_extrapolacion"),
          "y AVISA que hay pliegues que extrapolan: un pliegue recortado al "
          "tope físico domina el promedio y el MAE deja de medir el método",
          c.get("aviso_extrapolacion"))
    check(c.get("ganador_interpolacion"),
          "declarando cuál ganaría juzgando solo los pliegues que interpolan",
          c.get("ganador_interpolacion"))
    check(c.get("monotonia", {}).get("status") == "ok",
          "y la monotonía viaja en el mismo reporte")
    rel = [m for m in c["metodos"] if m["metodo"] == "relacion"][0]
    if rel.get("n_extrapolados"):
        check(rel.get("mae_interpolacion") is not None
              and rel["mae_interpolacion"] < rel["mae_mpa"],
              "el error de interpolación es menor que el total, como debe ser",
              (rel.get("mae_interpolacion"), rel["mae_mpa"]))


ALL_TESTS.append(la_no_monotonia_se_declara)
