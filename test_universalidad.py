"""
test_universalidad.py — Ninguna decisión de faena queda clavada en el código.

EL REQUISITO, en palabras del autor: «hay decisiones y datos que si queremos
hacer que esto futuramente sea replicable en otros yacimientos, necesito que
sean configurables desde el programa y no fijos en el código».

Estaba a medias. El perfil de faena tenía 42 parámetros, pero seguían clavadas
en el archivo cosas que OTRA MINA cambia sí o sí: a qué distancia un sondaje
se considera cercano —que depende de la densidad de sondajes, no de la
física—, cuántas litologías distintas se exigen para entrenar, con cuántos
sondajes se acepta calibrar, el paso de desurvey, los estratos de percusión.
Cada una de esas es un número de Punta del Cobre disfrazado de constante
universal.

LA DISTINCIÓN QUE ESTE TEST SOSTIENE:

  · Es CONVENCIÓN o FÍSICA → puede ser constante. El orden de los campos Val,
    los límites 0-450 MPa de UCS, las bandas ISRM de Brown 1981, la ventana y
    los pesos de Fernández. Cambiarlas rompe la comparabilidad o miente sobre
    la roca.

  · Es una DECISIÓN DE ESTA FAENA → va al perfil. Radios, umbrales de
    aceptación, mínimos de muestra, tamaños de bloque, semillas.

La lista de abajo se declara a mano a propósito: agregar una constante de
faena nueva y no registrarla tiene que hacer fallar este test, no pasar
inadvertido.
"""

import os, sys, json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

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


# Constante del módulo → parámetro del perfil que la gobierna.
DECISIONES_DE_FAENA = {
    "DRILLHOLE_NEAR_DISTANCE_M":  "sondajes.radio_cercania",
    "DRILLHOLE_TRACE_STEP_M":     "sondajes.paso_desurvey",
    "DQ_MERGE_WARN_M":            "carga.aviso_desplazamiento_dq",
    "PARSE_BUDGET_S":             "carga.presupuesto_parseo",
    "BORDE_MALLA_M":              "mallas.borde",
    "VAL_MAX_OFFSET_M":           "mallas.offset_maximo",
    "VAL_MIN_WELLS":              "mallas.pozos_minimos",
    "MIN_DISTINCT_LABELS":        "ml.etiquetas_minimas",
    "MIN_SAMPLES_PER_LABEL":      "ml.muestras_por_etiqueta",
    "MULTICOLLINEARITY_THRESHOLD": "ml.umbral_colinealidad",
    "COMPARISON_MAX_N":           "ml.submuestreo_comparacion",
    "COMPARISON_SEED":            "ml.semilla",
    "MAX_VIZ_POINTS":             "visor.puntos_maximos",
    "CAL_N_MUESTRAS":             "calibracion.n_muestras",
    "CAL_MIN_SONDAJES":           "calibracion.sondajes_minimos",
    "CAL_SEMILLA":                "calibracion.semilla",
    "DI_RQD_MIN_PUNTOS":          "calibracion.puntos_minimos",
    "IDW_MIN_POZOS":              "bloques.pozos_minimos",
    "SINGLE_SPECIMEN_PI_FACTOR":  "ucs.factor_probeta_unica",
    "HIGH_CV_THRESHOLD":          "ucs.cv_alto",
    "HIGH_CV_PI_FACTOR":          "ucs.factor_cv_alto",
}

# Estas SÍ son constantes, y tienen que seguir siéndolo.
CONVENCIONES_INTOCABLES = [
    "MWD_VAL_ORDER",          # LT|ROP|PP|FP|DP|RP|FLP, exactamente 7
    "BANDAS_RESISTENCIA",     # ISRM, Brown 1981
    "TERMINOLOGIA_C",         # "modelo geológico informado por MWD"
    "DI_VARIANTE_CONVENCION",
    "ATTR_ROLES",
    "CAL_PARAMS",             # las cinco presiones candidatas
]


# ─────────────────────────────────────────────────────────────────────────────
def toda_decision_de_faena_es_configurable():
    section("Universalidad — toda decisión de faena tiene su parámetro")
    faltan = [(c, p) for c, p in DECISIONES_DE_FAENA.items()
              if p not in gw.param_registry]
    check(not faltan,
          "cada constante de faena declarada tiene su parámetro en el perfil",
          faltan)
    sin_global = [p for c, p in DECISIONES_DE_FAENA.items()
                  if p in gw.param_registry
                  and gw.param_registry[p].get("global") != c]
    check(not sin_global,
          "y el parámetro está amarrado a la constante que gobierna: cambiarlo "
          "tiene que mover el número que el código lee, no solo una entrada de "
          "un diccionario", sin_global)


def cambiar_el_parametro_mueve_el_numero():
    section("Universalidad — cambiar el perfil cambia lo que el código usa")
    try:
        gw.set_param("sondajes.radio_cercania", 40.0)
        check(gw.DRILLHOLE_NEAR_DISTANCE_M == 40.0,
              "el radio de cercanía de sondajes se mueve",
              gw.DRILLHOLE_NEAR_DISTANCE_M)
        gw.set_param("ml.etiquetas_minimas", 3)
        check(gw.MIN_DISTINCT_LABELS == 3,
              "el mínimo de litologías para entrenar también", gw.MIN_DISTINCT_LABELS)
        gw.reset_param("sondajes.radio_cercania")
        check(gw.DRILLHOLE_NEAR_DISTANCE_M == 25.0,
              "y reponer el parámetro repone el número", gw.DRILLHOLE_NEAR_DISTANCE_M)
    finally:
        gw.seed_param_registry(force=True)


def las_convenciones_siguen_siendo_constantes():
    section("Universalidad — lo que es convención NO se vuelve configurable")
    for c in CONVENCIONES_INTOCABLES:
        check(hasattr(gw, c), f"{c} existe", c)
    check(gw.MWD_VAL_ORDER == ("LT", "ROP", "PP", "FP", "DP", "RP", "FLP"),
          "el orden de los campos Val es el de CLAUDE.md", gw.MWD_VAL_ORDER)
    check(len(gw.MWD_VAL_ORDER) == 7, "exactamente 7", len(gw.MWD_VAL_ORDER))
    # EL CONTRATO CAMBIÓ DOS VECES, y esta es la segunda.
    #
    # Primero los seis del DI estaban BLOQUEADOS en el perfil. El autor los
    # liberó: quien calibra decide, y calibrar contra el testigo es el método
    # de Fernández, no una desviación.
    #
    # Después se vio lo que en realidad pasaba al escribirlos ahí: NADA. La
    # pantalla aceptaba el número, lo reportaba como aplicado, y el DI seguía
    # corriendo con los suyos, porque `di_config`/`di_threshold` se escriben
    # solo desde activar_di(). Un control que no controla es peor que no
    # tenerlo, y encima se pedían dos veces —perfil y Paso 3—. Salieron del
    # registro: se escriben en UN lugar y el perfil los muestra en vivo.
    for pid in ("di.ventana", "di.umbral", "di.peso_pp", "di.peso_dp",
                "di.peso_fp", "di.peso_rp"):
        check(pid not in gw.param_registry,
              f"{pid} ya no es un parámetro del perfil: no lo usaba nadie")
    check(not any(k.startswith("di.") for k in gw.param_registry),
          "ningún parámetro del DI quedó suelto en el perfil",
          [k for k in gw.param_registry if k.startswith("di.")])
    # Lo que los reemplaza: el perfil los MUESTRA, sin ofrecer editarlos.
    cuerpo = gw._di_vigente_body()
    txt = " ".join(_textos(cuerpo))
    check(gw.di_activo() in txt,
          "el perfil dice qué variante del DI está corriendo", txt[:100])
    check("olo lectura" in txt,
          "y declara que es solo lectura, en vez de fingir un control", txt[:200])
    check(f"{gw.di_config['window']}" in txt, "con su ventana")
    # El único escritor sigue siendo activar_di().
    check(gw.di_config["weights"] == gw.DI_DEFAULTS["weights"],
          "y los pesos que corren son los de convención mientras nadie active "
          "otra variante", gw.di_config["weights"])
    # El mecanismo de protección sigue existiendo para la faena que lo necesite.
    check(hasattr(gw, "ParametroProtegido"),
          "el mecanismo de protección sigue disponible aunque hoy no se use")


def los_estratos_de_pp_son_de_la_faena():
    section("Universalidad — los estratos de percusión son de la faena")
    check("pp.estratos" in gw.param_registry,
          "los estratos de PP se declaran en el perfil: 90-130-170-230 son los "
          "de MPC, no una propiedad de la percusión")
    try:
        gw.set_param("pp.estratos", "100-150,150-200")
        check(gw.PP_ESTRATOS == ((100.0, 150.0), (150.0, 200.0)),
              "y cambiarlos cambia los estratos que el código usa", gw.PP_ESTRATOS)
        try:
            gw.set_param("pp.estratos", "esto no es un estrato")
            check(False, "un texto ilegible tenía que fallar")
        except ValueError:
            check(True, "un texto ilegible se rechaza en vez de dejar cero estratos")
        check(gw.PP_ESTRATOS == ((100.0, 150.0), (150.0, 200.0)),
              "sin tocar los vigentes", gw.PP_ESTRATOS)
    finally:
        gw.seed_param_registry(force=True)
    check(gw.PP_ESTRATOS == ((90.0, 130.0), (130.0, 170.0), (170.0, 230.0)),
          "y el defecto sigue siendo el de MPC", gw.PP_ESTRATOS)


def ningun_parametro_queda_congelado_en_un_default():
    """
    LA TRAMPA: `def f(radio=DRILLHOLE_NEAR_DISTANCE_M)`. Python evalúa los
    valores por defecto UNA VEZ, al definir la función. Cambiar el parámetro
    del perfil mueve el global, pero esa función sigue usando el número que
    había al importar el módulo, para siempre y sin avisar.

    Es el peor de los casos: el perfil dice 40 m, la pantalla dice 40 m, y el
    cálculo se hace con 25. Ocho funciones estaban así.
    """
    section("Universalidad — ningún parámetro congelado en un default de función")
    import ast
    ruta = os.path.join(HERE, "geomech_wizard.py")
    arbol = ast.parse(open(ruta, encoding="utf-8").read())
    globales = {p["global"] for p in gw.param_registry.values() if p.get("global")}
    malos = []
    for n in ast.walk(arbol):
        if not isinstance(n, ast.FunctionDef):
            continue
        defaults = list(n.args.defaults) + [d for d in n.args.kw_defaults if d]
        for d in defaults:
            for sub in ast.walk(d):
                if isinstance(sub, ast.Name) and sub.id in globales:
                    malos.append(f"{n.name}() ← {sub.id}")
    check(not malos,
          "ningún parámetro del perfil se usa como valor por defecto de una "
          "función: se resuelve en el cuerpo, con el valor vigente", malos)


def _textos(nodo):
    """Todo el texto de un árbol de componentes Dash, aplanado."""
    out = []
    def rec(x):
        if isinstance(x, str):
            out.append(x); return
        if isinstance(x, (list, tuple)):
            for y in x: rec(y)
            return
        for attr in ("children", "title", "label", "placeholder"):
            v = getattr(x, attr, None)
            if v is not None: rec(v)
    rec(nodo)
    return out


def _ids(nodo):
    out = []
    def rec(x):
        if isinstance(x, (list, tuple)):
            for y in x: rec(y)
            return
        i = getattr(x, "id", None)
        if i is not None: out.append(i)
        for attr in ("children", "title"):
            v = getattr(x, attr, None)
            if v is not None: rec(v)
    rec(nodo)
    return out


def el_perfil_se_edita_desde_el_programa():
    """
    «Configurables DESDE EL PROGRAMA» quiere decir desde la pantalla. El
    registro existía pero solo se alcanzaba llamando set_param() a mano en una
    celda: para el geomecánico que abre la plataforma, eso es igual de fijo que
    tenerlo clavado en el código.
    """
    section("Universalidad — el perfil se edita desde la pantalla, repartido en menús")
    # El panel dibuja UN MENÚ por vez: los 64 parámetros de 18 secciones de una
    # sola vez eran lentos de renderizar y con todo a la vista no se distingue
    # lo que hay que decidir de lo que hay que dejar quieto. La garantía que
    # importa es que NADA se haya perdido en el reparto.
    vistos, textos = set(), []
    for menu in gw.MENUS_PERFIL:
        cuerpo = gw._perfil_panel_body(menu, avanzados=True)
        textos += _textos(cuerpo)
        for i in _ids(cuerpo):
            if isinstance(i, dict) and i.get("type") == "perfil-param":
                vistos.add(i.get("param"))
    # Los OCULTOS no tienen campo a propósito: la faena los fija una vez.
    editables = {p["id"] for p in gw.param_registry.values()
                 if not p.get("protegido") and p["id"] not in gw.PARAMS_OCULTOS}
    faltan = editables - vistos
    check(not faltan,
          "recorriendo los menús, todo parámetro editable tiene su campo: "
          "ninguno quedó huérfano al repartir", sorted(faltan))
    check("repo.ruta" not in (editables - vistos), "incluida la ruta del repositorio")
    txt = " | ".join(textos)
    for sec in ("Sondajes", "Modelo de bloques", "Calibración DI↔RQD",
                "Modelo de aprendizaje"):
        check(sec in txt, f"la sección «{sec}» aparece agrupada", txt[:200])
    # Los seis del DI ya no son campos del perfil —escribirlos ahí no movía el
    # DI— pero el menú de Fracturamiento tiene que SEGUIR diciendo con qué
    # está corriendo. Sacarlos sin poner nada en su lugar habría convertido un
    # control falso en una ausencia, que informa todavía menos.
    frac = " | ".join(_textos(gw._perfil_panel_body("Fracturamiento",
                                                    avanzados=True)))
    check("Peso de PP" not in frac,
          "el perfil ya no ofrece escribir los pesos del DI", frac[:200])
    check(gw.di_activo() in frac and "olo lectura" in frac,
          "pero sí muestra qué variante corre, declarada como solo lectura",
          frac[:300])
    # Cada sección cae en exactamente un menú, y ningún menú queda vacío.
    secs = {p["seccion"] for p in gw.param_registry.values()}
    cubiertas = {s for lista in gw.MENUS_PERFIL.values() for s in lista}
    check(secs <= cubiertas, "ninguna sección queda fuera de los menús",
          sorted(secs - cubiertas))
    check(not any(p.get("menu") == "Otros" for p in gw.param_registry.values()),
          "y ningún parámetro cae en el cajón de sastre")


def los_basicos_son_los_que_una_faena_toca():
    section("Universalidad — lo que varía poco no compite por la atención")
    basicos = {p["id"] for p in gw.param_registry.values() if p.get("basico")}
    check(basicos, "hay un subconjunto declarado de parámetros básicos", len(basicos))
    for pid in ("repo.ruta", "rqd.radio_max_m", "bloques.tamano_m",
                "ucs.estadistica_ml", "top.largo_min_pozo_m"):
        check(pid in basicos, f"{pid} es básico: una faena nueva lo toca sí o sí")
    # El radio de cercanía de sondajes pasó a AVANZADO: la decisión que sí
    # importa es el radio con que se asigna el RQD, y preguntar las dos era
    # preguntar dos veces por lo mismo.
    check("sondajes.radio_cercania" not in basicos,
          "y el radio de cercanía quedó en avanzados")
    for pid in ("ml.semilla", "calibracion.semilla", "discriminador.var_factor"):
        if pid in gw.param_registry:
            check(pid not in basicos,
                  f"{pid} es avanzado: se mueve poco y va detrás del interruptor")
    # Sin avanzados, la pantalla muestra MENOS que con ellos. Es el punto.
    for menu in gw.MENUS_PERFIL:
        n_b = len([i for i in _ids(gw._perfil_panel_body(menu, False))
                   if isinstance(i, dict) and i.get("type") == "perfil-param"])
        n_a = len([i for i in _ids(gw._perfil_panel_body(menu, True))
                   if isinstance(i, dict) and i.get("type") == "perfil-param"])
        check(n_b <= n_a, f"menú {menu}: básico ({n_b}) ≤ avanzado ({n_a})")


def la_pantalla_escribe_lo_que_promete():
    """
    Esta prueba pasó por los tres contratos del DI: primero verificaba que la
    pantalla NO pudiera escribir esos seis parámetros; después que SÍ pudiera,
    cuando el autor los liberó; y ahora ya no los usa, porque escribirlos ahí
    nunca movió el DI. Lo que valió en las tres versiones y sigue valiendo: lo
    que la pantalla dice haber aplicado tiene que haberse aplicado de verdad, y
    un valor RECHAZADO se declara sin bloquear a los demás.
    """
    section("Universalidad — la pantalla escribe, y lo rechazado se declara")
    rep = gw.aplicar_perfil_desde_panel({"bloques.tamano_m": 3.5,
                                         "sondajes.radio_cercania": 30.0})
    check(gw.get_param("bloques.tamano_m") == 3.5,
          "lo que la pantalla aplica llega al parámetro",
          gw.get_param("bloques.tamano_m"))
    check(gw.BLOQUE_M == 3.5,
          "y al módulo: un parámetro que se aplica solo en el registro es el "
          "control que no controla que ya sacamos del DI", gw.BLOQUE_M)
    check(gw.get_param("sondajes.radio_cercania") == 30.0,
          "y el resto también", gw.get_param("sondajes.radio_cercania"))
    check(rep["n_aplicados"] == 2, "los dos se aplican", rep["n_aplicados"])
    gw.seed_param_registry(force=True)

def un_valor_fuera_de_rango_se_declara():
    section("Universalidad — un valor fuera de rango se rechaza con su motivo")
    rep = gw.aplicar_perfil_desde_panel({"sondajes.radio_cercania": 99999.0})
    check(gw.get_param("sondajes.radio_cercania") == 25.0,
          "el valor no entra", gw.get_param("sondajes.radio_cercania"))
    rech = rep.get("rechazados") or []
    check(rech and rech[0].get("motivo"),
          "y viene con el motivo, con el límite nombrado", rech)
    # None (campo vaciado en la pantalla) no borra el valor vigente.
    rep2 = gw.aplicar_perfil_desde_panel({"sondajes.radio_cercania": None})
    check(gw.get_param("sondajes.radio_cercania") == 25.0,
          "y un campo vacío deja el valor vigente en vez de anularlo",
          gw.get_param("sondajes.radio_cercania"))
    check(rep2["n_aplicados"] == 0, "sin contarlo como aplicado", rep2)
    gw.seed_param_registry(force=True)


def el_perfil_completo_viaja():
    section("Universalidad — todo esto viaja en el perfil exportado")
    d = json.loads(gw.export_site_profile())
    faltan = [p for p in DECISIONES_DE_FAENA.values()
              if p not in (d.get("parametros") or {})]
    check(not faltan, "los parámetros nuevos van en el JSON que recibe otra faena",
          faltan)
    # Y volver a importarlo repone exactamente lo mismo.
    gw.set_param("sondajes.radio_cercania", 33.0)
    rep = gw.import_site_profile(json.dumps(d))
    check(gw.get_param("sondajes.radio_cercania") == 25.0,
          "importar el perfil repone los valores", gw.get_param("sondajes.radio_cercania"))
    check(rep.get("n_aplicados", 0) > 0, "declarando cuántos aplicó", rep)
    gw.seed_param_registry(force=True)


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    toda_decision_de_faena_es_configurable,
    cambiar_el_parametro_mueve_el_numero,
    las_convenciones_siguen_siendo_constantes,
    los_estratos_de_pp_son_de_la_faena,
    ningun_parametro_queda_congelado_en_un_default,
    el_perfil_se_edita_desde_el_programa,
    los_basicos_son_los_que_una_faena_toca,
    la_pantalla_escribe_lo_que_promete,
    un_valor_fuera_de_rango_se_declara,
    el_perfil_completo_viaja,
]


def test_universalidad():
    """Punto de entrada para pytest."""
    FAILURES.clear()
    try:
        for t in ALL_TESTS:
            t()
    finally:
        gw.seed_param_registry(force=True)
    assert not FAILURES, f"{len(FAILURES)} comprobación(es) fallida(s): " + "; ".join(FAILURES)


if __name__ == "__main__":
    try:
        for t in ALL_TESTS:
            t()
    finally:
        gw.seed_param_registry(force=True)
    print(f"\n{'='*72}")
    if FAILURES:
        print(f"✗ {len(FAILURES)} FALLA(S):")
        for f in FAILURES:
            print(f"   · {f}")
        sys.exit(1)
    print("✓ UNIVERSALIDAD — todas las verificaciones pasaron.")
    print("=" * 72)
