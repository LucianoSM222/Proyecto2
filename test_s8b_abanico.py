"""
test_s8b_abanico.py — Paso 5: separar los picos que son el plano del abanico.

UN ABANICO DE TIROS ES UN PLANO. Si los picos del DI se reparten a lo largo
de los tiros de un mismo abanico, cualquier subconjunto suyo sale "plano" por
construcción, sin que exista ninguna estructura geológica. Sobre los datos
reales de Punta del Cobre esto no es teórico: 19 de 31 grupos planares
resultaron ser el abanico, incluidos los tres mayores (590, 533 y 478 picos),
con 0,5°, 0,0° y 0,5° entre su normal y la del abanico.

Un pico marcado como plano de abanico NO SE BORRA. Se marca, con su motivo, y
los reportes entregan las cifras con y sin él para que la comparación sea
visible. Borrarlo sería un default silencioso de los que el proyecto prohíbe.

LA AMBIGÜEDAD DE FONDO, que el criterio respeta: dentro de UN SOLO abanico no
se puede distinguir una estructura de su propio plano, porque todo lo que hay
en el abanico está en el plano del abanico. La capacidad de discriminar viene
de cruzar VARIOS abanicos.
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


E0, N0, Z0 = 376700.0, 6959000.0, 300.0
PASO = 0.05          # 5 cm entre registros


def _tiro(wn, plan, collar, direccion, largo_m=20.0, picos_en=()):
    """
    Tiro recto desde `collar` en `direccion` (unitaria). Los largos listados
    en `picos_en` reciben DI alto: son los picos que el DI ya detectó.
    """
    d = np.asarray(direccion, dtype=np.float64)
    d = d / np.linalg.norm(d)
    c = np.asarray(collar, dtype=np.float64)
    n = int(largo_m / PASO)
    pts = []
    for i in range(n):
        largo = i * PASO
        q = c + d * largo
        p = gw.MWDPoint(largo=largo, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                        pr=45.0, pf=8.0, se=340.0, t=0.0)
        p.este, p.norte, p.cota = float(q[0]), float(q[1]), float(q[2])
        p.di = 0.4
        p.entrenable = True
        p.dominio = "Bht"; p.lito = "Bht"
        pts.append(p)
    for lp in picos_en:
        i0, i1 = int((lp - 0.15) / PASO), int((lp + 0.15) / PASO)
        for i in range(max(0, i0), min(n, i1 + 1)):
            pts[i].di = 2.5
    w = gw.Well(well_name=wn, plan_id=plan, hole_id=wn, points=pts)
    w.caseron = "CAS_A"
    gw.wells[wn] = w
    return w


def _abanico(plan, norte, angulos, profundidad_pico):
    """
    Abanico de tiros que radian DENTRO DE UN PLANO vertical de norte
    constante — la geometría real de un Sub Level Stoping.

    Las profundidades de los picos se alternan a propósito: así los picos no
    dibujan un arco casi rectilíneo sino un PARCHE de dos dimensiones dentro
    del plano del abanico, que es lo que produce un abanico real y lo que
    hace que el grupo tenga normal bien definida.
    """
    angulos = list(angulos)
    rng = np.random.default_rng(7)
    for k, ang in enumerate(angulos):
        r = np.radians(ang)
        prof = profundidad_pico + (2.0 if k % 2 else -2.0)
        # Un abanico real no es un plano perfecto: la desviación de
        # perforación mueve cada tiro unos centímetros fuera del plano
        # nominal. Sin ese ruido el escenario es más limpio que la realidad y
        # los umbrales no se pueden poner a prueba.
        dn = float(rng.normal(0.0, 0.10))
        # Varios picos por tiro, como en los datos reales (media 7,4 por
        # pozo). Así los picos dibujan un PARCHE de dos dimensiones dentro del
        # plano del abanico y el grupo tiene normal bien definida, que es la
        # condición para que el criterio angular pueda aplicarse.
        _tiro(f"{plan}_H{k}", plan, (E0, norte + dn, Z0),
              (np.sin(r), 0.0, -np.cos(r)),
              picos_en=(prof - 3.0, prof, prof + 3.0))


# ─────────────────────────────────────────────────────────────────────────────
def un_solo_abanico_es_artefacto():
    section("5 — Un abanico solo: sus picos son el plano del abanico, no geología")
    reset()
    _abanico("CAS_PR01_TH_P01", N0, angulos=range(-20, 21, 5), profundidad_pico=10.0)

    rep = gw.discriminate_all()
    check(rep["status"] == "ok", "corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    marcados = [p for p in rep["picos"] if p.get("plano_abanico")]
    check(len(marcados) >= 5,
          "los picos del abanico quedan MARCADOS como plano de abanico",
          f"{len(marcados)} de {rep['n_picos']}")
    check(all(p.get("motivo_abanico") for p in marcados),
          "cada uno con su motivo, no una bandera muda",
          [p["pozo"] for p in marcados if not p.get("motivo_abanico")][:3])
    check(rep["n_picos"] == len(rep["picos"]),
          "y NO se borra ninguno: marcar no es descartar")
    check(rep.get("n_plano_abanico") == len(marcados),
          "el reporte cuenta cuántos son", rep.get("n_plano_abanico"))


def estructura_que_cruza_abanicos_no_se_marca():
    section("5 — Un plano que CRUZA varios abanicos sí es estructura: no se marca")
    reset()
    # Tres abanicos paralelos separados 2 m en el norte, cada uno radiando en
    # su propio plano vertical. Una estructura de rumbo norte-sur y manteo
    # vertical —el plano E = E_ESTRUCT— los corta a los tres. El pico cae en
    # cada tiro donde ese plano lo intersecta, o sea a distinta profundidad
    # según la inclinación del tiro.
    E_ESTRUCT = E0 + 3.0
    for j, dn in enumerate((0.0, 2.0, 4.0)):
        plan = f"CAS_PR01_TH_P{j+1:02d}"
        for k, ang in enumerate((20, 25, 30, 35, 40)):
            r = np.radians(ang)
            prof = (E_ESTRUCT - E0) / np.sin(r)      # intersección con el plano
            _tiro(f"{plan}_H{k}", plan, (E0, N0 + dn, Z0),
                  (np.sin(r), 0.0, -np.cos(r)), picos_en=(prof,))

    rep = gw.discriminate_all()
    check(rep["status"] == "ok", "corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    marcados = [p for p in rep["picos"] if p.get("plano_abanico")]
    check(len(marcados) == 0,
          "ningún pico se marca: los tiros involucrados NO son coplanares",
          f"{len(marcados)} marcados de {rep['n_picos']} · "
          f"grupos={(rep.get('abanico') or {}).get('grupos')}")
    grupos = (rep.get("abanico") or {}).get("grupos") or []
    multi = [g for g in grupos if g["n_abanicos"] >= 3]
    check(multi, "y el grupo que se forma cruza los tres abanicos",
          [(g["n_picos"], g["n_abanicos"]) for g in grupos])


def picos_aislados_no_se_marcan():
    section("5 — Un pico solo no forma plano: no se marca")
    reset()
    _tiro("SOLO_H1", "CAS_PR01_TH_P01", (E0, N0, Z0), (0.0, 0.0, -1.0),
          picos_en=(5.0,))
    rep = gw.discriminate_all()
    if rep["status"] != "ok":
        check(False, "corre", rep.get("motivo")); return
    check(not any(p.get("plano_abanico") for p in rep["picos"]),
          "el pico aislado queda sin marcar")
    check(rep.get("n_plano_abanico") == 0, "y el conteo lo confirma",
          rep.get("n_plano_abanico"))


def el_reporte_entrega_las_dos_cifras():
    section("5 — El contraste contra sondajes se reporta CON y SIN los del abanico")
    reset()
    _abanico("CAS_PR01_TH_P01", N0, angulos=range(-20, 21, 5), profundidad_pico=10.0)
    # Un sondaje vertical cerca, con una estructura logueada a la profundidad
    # del arco de picos, para que haya pares que aparear.
    dh = gw.DrillHole(holeid="DH1", x_utm=E0 + 1.0, y_utm=N0, z_utm=Z0, length=20.0)
    dh.trace = [(0.0, E0 + 1.0, N0, Z0), (20.0, E0 + 1.0, N0, Z0 - 20.0)]
    dh.structures = [{"from": 10.0, "to": 10.0, "codigo": "FALLA",
                      "atributo_id": "FM", "tipo": "logueada"}]
    gw.drillholes["DH1"] = dh

    rep = gw.discriminator_report(radio_m=10.0)
    check(rep["status"] in ("ok", "sin_etiquetas"), "corre", rep.get("motivo"))
    check("sin_abanico" in rep,
          "el reporte trae el bloque 'sin_abanico' al lado del completo", list(rep))
    sa = rep.get("sin_abanico") or {}
    check("n_pares" in sa and "motivo" in sa or sa.get("status"),
          "que declara su estado y su tamaño de muestra", sa)
    check(rep.get("n_plano_abanico") is not None,
          "y cuántos picos se atribuyeron al abanico", rep.get("n_plano_abanico"))


def los_umbrales_son_ajustables_y_declarados():
    section("5 — Los umbrales del criterio son parámetros, no números enterrados")
    for nombre in ("ABANICO_EPS_M", "ABANICO_MIN_PICOS",
                   "ABANICO_PLANARIDAD_TIROS", "ABANICO_ANG_MAX_GRAD",
                   "ABANICO_TOL_PLANO_M"):
        check(hasattr(gw, nombre), f"{nombre} existe como constante del módulo")
    check(gw.ABANICO_EPS_M == 2.5,
          "el agrupamiento usa el burden de la operación (2,5 m)", gw.ABANICO_EPS_M)
    reset()
    _abanico("CAS_PR01_TH_P01", N0, angulos=range(-20, 21, 5), profundidad_pico=10.0)
    # Apretar cualquiera de los dos criterios desde la llamada tiene que
    # cambiar el resultado: son parámetros de verdad, no adorno.
    rep2_ref = gw.discriminate_all().get("n_plano_abanico", 0)
    check(rep2_ref > 0, "con los valores por defecto hay marcas de referencia",
          rep2_ref)
    rep = gw.discriminate_all(tol_plano_m=0.0)
    check(rep.get("n_plano_abanico") == 0,
          "apretar la tolerancia de distancia al plano cambia el resultado",
          rep.get("n_plano_abanico"))
    # El criterio angular es SECUNDARIO: solo aplica a los grupos con normal
    # utilizable. Apretarlo reduce las marcas, pero no puede llevarlas a cero
    # mientras haya grupos casi rectilíneos, donde la normal es arbitraria y la
    # distancia al plano es lo único que decide. Exigir cero sería exigir que
    # el criterio mienta.
    rep_ang = gw.discriminate_all(ang_max_grad=0.0)
    check(rep_ang.get("n_plano_abanico", 0) < rep2_ref,
          "apretar la tolerancia angular reduce las marcas de los grupos con "
          "normal utilizable",
          (rep2_ref, rep_ang.get("n_plano_abanico")))
    g_ang = (rep_ang.get("abanico") or {}).get("grupos") or []
    check(any(x.get("normal_utilizable") for x in g_ang),
          "y el reporte declara cuándo la normal del grupo ES utilizable",
          [(x["n_picos"], x["normal_utilizable"]) for x in g_ang])
    rep2 = gw.discriminate_all()
    check(rep2.get("n_plano_abanico", 0) > 0,
          "y con los valores por defecto vuelve a marcar", rep2.get("n_plano_abanico"))
    # El reporte por grupo declara con qué medidas se decidió.
    g = (rep2.get("abanico") or {}).get("grupos") or []
    check(g and all(k in g[0] for k in ("planaridad_tiros", "dist_al_plano_m",
                                        "angulo_con_abanico_grad", "es_abanico")),
          "y cada grupo declara las medidas con que se decidió", g[:1])


def el_di_no_se_toca():
    section("5 — Este paso NO toca el DI ni sus picos")
    reset()
    _abanico("CAS_PR01_TH_P01", N0, angulos=range(-20, 21, 5), profundidad_pico=10.0)
    antes = sum(len(gw.di_peaks(w)) for w in gw.wells.values())
    gw.discriminate_all()
    despues = sum(len(gw.di_peaks(w)) for w in gw.wells.values())
    check(antes == despues, "di_peaks devuelve los mismos picos", (antes, despues))
    check(gw.di_config_is_default(),
          "la configuración del DI sigue en sus valores de convención",
          gw.di_config_summary())


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    un_solo_abanico_es_artefacto,
    estructura_que_cruza_abanicos_no_se_marca,
    picos_aislados_no_se_marcan,
    el_reporte_entrega_las_dos_cifras,
    los_umbrales_son_ajustables_y_declarados,
    el_di_no_se_toca,
]


def test_s8b_abanico():
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
    print("✓ PASO 5 — todas las verificaciones pasaron.")
    print("=" * 72)
