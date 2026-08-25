"""
╔══════════════════════════════════════════════════════════════════════════════╗
║       MWD GEOMECH WIZARD — v1.1  (port fiel del HTML de referencia)         ║
║       Autor: Luciano Poblete Vergara — USACH 2026                            ║
║                                                                              ║
║  Cambios v1.1 (respecto a v1.0) — corrige los MWD que no aparecían:         ║
║    · Se replica utm2t() con globalCenter                                     ║
║    · Matching MW↔DQ con fallback laxo (por hole_id si plan_id no coincide) ║
║    · Sistema de coordenadas: DXF nativo (X=Este, Y=Norte, Z=Cota)           ║
║    · wz_state['step1']['xml_loaded'] se actualiza al terminar la carga      ║
║    · Diagnóstico visual de calce MWD↔DXF                                    ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, sys, json, time, base64, tempfile, re, warnings, threading, traceback, math, hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
import ezdxf, ezdxf.recover
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.neighbors import KNeighborsRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import cross_val_score, cross_val_predict, GroupKFold, LeaveOneGroupOut
from sklearn.inspection import permutation_importance
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import dash
from dash import dcc, html, Input, Output, State, callback_context, no_update, ALL
import dash_bootstrap_components as dbc

warnings.filterwarnings("ignore")
IN_COLAB = "google.colab" in sys.modules

APP_TITLE, APP_VERSION, PORT = "MWD GeoMech Wizard", "1.1", 8050
NS_IR = "http://www.iredes.org/xml"
NS_DR = "http://www.iredes.org/xml/DrillRig"
IR, DR = f"{{{NS_IR}}}", f"{{{NS_DR}}}"

ML_FEATURES = ["vel","pp","pa","pd","pr","pf","se"]
ML_LABELS   = ["ROP","PP","AP","DP","RP","FP","SE"]
# (P1-T1.6) Límites físicos de UCS: 0 a 450 MPa. El rango anterior (25–280)
# no era físico sino operacional, y al estar cableado como `min`/`max` del
# componente Dash provocaba que un valor superior devolviera None y la
# expresión `float(v or default)` cayera al valor por defecto — excluyendo en
# silencio una litología completa. Los límites de aviso (warning_*) son
# orientativos y NUNCA truncan: solo colorean. Los defaults abarcan todo el
# rango físico para que ninguna banda quede fuera sin decisión explícita.
UCS_CONFIG = {"physical_min":0.0,"physical_max":450.0,"warning_min":50.0,"warning_max":350.0,"default_min":0.0,"default_max":450.0}
PALETTE = ["#3B8BD4","#D05538","#5DCAA5","#EF9F27","#D4537E","#7F77DD","#2ECC71","#E74C3C","#F39C12","#1ABC9C","#9B59B6","#F1C40F","#E67E22","#BDC3C7"]
EPS = 1e-9
PARSE_BUDGET_S = 12.0
# Convención inmutable del orden de campos de <Val> en el MWD IREDES. Son
# EXACTAMENTE 7; todo campo excedente se descarta del uso pero se reporta una
# vez en la carga (parse_mw), nunca en silencio.
MWD_VAL_ORDER = ("LT", "ROP", "PP", "FP", "DP", "RP", "FLP")
MWD_VAL_FIELDS = len(MWD_VAL_ORDER)

# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  P1 — FUNDACIONES: partición por sitio y registro de vocabulario        ║
# ║                                                                          ║
# ║  Esta capa hace la herramienta portable a otras minas e impide que un   ║
# ║  dato de un sitio contamine otro. Convierte los datos faltantes (como   ║
# ║  el UCS de Bht) en estados manejados en vez de bloqueos mudos.          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

# ─── T1.1 · CONSTANTE DE SITIO Y GUARDIÁN POR COORDENADAS ────────────────────
# Principio: las coordenadas son la autoridad de pertenencia a un sitio. Ni el
# nombre del archivo ni el desplegable que eligió el usuario deciden nada.

SITE_REGISTRY: Dict[str, Dict] = {
    "MPC": {
        "id": "MPC",
        "display": "Punta del Cobre",
        # Envolvente UTM de los 11 sondajes MPC (WGS84 19S).
        "este_min": 376521.0, "este_max": 377005.0,
        "norte_min": 6958752.0, "norte_max": 6959323.0,
        "margen_m": 1500.0,
        "notas": "Mina subterránea de cobre, Sub Level Stoping. Convenio Pucobre.",
    },
}
ACTIVE_SITE = "MPC"

# Objetos cuya carga disparó la advertencia de sitio y esperan confirmación
# explícita. Cada entrada: {token, etiqueta, tipo, este, norte, dist_m,
# umbral_m, confirmado, ts}. El guardián NO carga nada por su cuenta: devuelve
# un veredicto y el llamador decide.
site_pending_confirms: List[Dict] = []
# Tokens que el usuario confirmó explícitamente ("sí, cárgalo igual").
site_confirmed_tokens: set = set()

# (A.7) EXENCIONES DE FIXTURE — explícitas y declaradas, nunca implícitas.
#
# Bht_Fk.dxf pertenece a Mina Granate (MGN 3025), a ~3,05 km del centroide de
# MPC. Cargarlo por el FLUJO NORMAL debe disparar la advertencia de T1.1: eso
# es una buena prueba del guardián y se verifica como tal. Pero los tests que
# lo usan como fixture geométrico necesitan cargarlo sin fricción.
#
# La exención se declara aquí, por token, con su razón. Si un fixture de otro
# sitio pudiera cargarse sin declararlo, el guardián estaría silenciosamente
# roto — que es exactamente lo que esta capa existe para impedir. Por eso la
# exención NO se aplica sola: hay que activarla con allow_site_fixtures().
SITE_FIXTURE_EXEMPTIONS: Dict[str, str] = {
    "dxf:Bht_Fk": ("Fixture geométrico de test. Pertenece a Mina Granate (MGN 3025), "
                   "no a MPC. Se usa solo para verificar ray casting y reglas de "
                   "traslape; jamás debe entrar a un análisis de Punta del Cobre."),
}
# Interruptor de las exenciones. False en la aplicación: un usuario nunca debe
# saltarse el guardián por una lista interna. Los tests lo encienden a mano.
site_fixtures_allowed: bool = False


def allow_site_fixtures(enabled: bool = True):
    """
    Activa/desactiva las exenciones declaradas en SITE_FIXTURE_EXEMPTIONS.
    Pensado para los tests: la aplicación corre siempre con esto en False.
    """
    global site_fixtures_allowed
    site_fixtures_allowed = bool(enabled)


def site_fixture_exempt(token: str) -> Optional[str]:
    """Razón de la exención si aplica y está habilitada; None en caso contrario."""
    if not site_fixtures_allowed: return None
    return SITE_FIXTURE_EXEMPTIONS.get(token)


def active_site() -> Dict:
    """Config del sitio activo. Falla ruidosamente si el id no existe."""
    if ACTIVE_SITE not in SITE_REGISTRY:
        raise KeyError(f"Sitio activo '{ACTIVE_SITE}' no está en SITE_REGISTRY.")
    return SITE_REGISTRY[ACTIVE_SITE]


def site_centroid(site_id: Optional[str] = None) -> Tuple[float, float]:
    """Centroide (este, norte) de la envolvente declarada del sitio."""
    s = SITE_REGISTRY[site_id or ACTIVE_SITE]
    return ((s["este_min"] + s["este_max"]) / 2.0,
            (s["norte_min"] + s["norte_max"]) / 2.0)


def site_guard(este: float, norte: float, etiqueta: str, tipo: str = "objeto",
               token: Optional[str] = None) -> Dict:
    """
    Evalúa si un objeto cargado pertenece al sitio activo, por coordenadas.

    `este`/`norte` son el centroide del objeto (malla DXF, collar de sondaje,
    nube de puntos MWD). Devuelve un veredicto:

        {"ok": bool, "dist_m": float, "umbral_m": float, "sitio": str,
         "mensaje": str, "token": str, "confirmado": bool}

    ok=True  → dentro del margen, o ya confirmado explícitamente por el usuario.
    ok=False → excede el margen y NO hay confirmación: el llamador debe abstenerse
               de cargar y encolar el objeto en site_pending_confirms.

    Nunca carga ni descarta por su cuenta, y nunca aplica un default.
    """
    s = active_site()
    tok = token or f"{tipo}:{etiqueta}"
    if este is None or norte is None or not (np.isfinite(este) and np.isfinite(norte)):
        return {"ok": False, "dist_m": None, "umbral_m": s["margen_m"], "sitio": s["id"],
                "token": tok, "confirmado": False,
                "mensaje": (f'"{etiqueta}": centroide no calculable (coordenadas no finitas). '
                            f"No se puede verificar pertenencia al sitio {s['display']}.")}
    cx, cy = site_centroid()
    dist = float(np.hypot(este - cx, norte - cy))
    # (A.7) Exención de fixture: explícita, declarada y habilitada a mano.
    razon = site_fixture_exempt(tok)
    if razon is not None and dist > s["margen_m"]:
        return {"ok": True, "dist_m": round(dist, 1), "umbral_m": s["margen_m"],
                "sitio": s["id"], "token": tok, "confirmado": True, "fixture": True,
                "mensaje": (f'"{etiqueta}" a {_num_cl(dist)} m: EXENTO como fixture '
                            f"declarado. {razon}")}
    if dist <= s["margen_m"]:
        return {"ok": True, "dist_m": round(dist, 1), "umbral_m": s["margen_m"],
                "sitio": s["id"], "token": tok, "confirmado": False, "mensaje": ""}
    confirmado = tok in site_confirmed_tokens
    msg = (f'⚠ "{etiqueta}" ({tipo}) está a {_num_cl(dist)} m del centroide de '
           f"{s['display']} ({s['id']}); el margen declarado es {_num_cl(s['margen_m'])} m. "
           f"Centroide del objeto: E {_num_cl(este, 1)} · N {_num_cl(norte, 1)}. "
           f"Muy probablemente sea de OTRA MINA.")
    if not confirmado:
        _queue_site_confirm(tok, etiqueta, tipo, este, norte, dist, s["margen_m"])
    return {"ok": confirmado, "dist_m": round(dist, 1), "umbral_m": s["margen_m"],
            "sitio": s["id"], "token": tok, "confirmado": confirmado,
            "mensaje": msg + (" [confirmado por el usuario]" if confirmado else "")}


def _num_cl(x, dec=0):
    """Número en formato chileno: miles con '.', decimales con ','."""
    s = f"{x:,.{dec}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _queue_site_confirm(token, etiqueta, tipo, este, norte, dist, umbral):
    for e in site_pending_confirms:
        if e["token"] == token:
            e.update(dist_m=round(dist, 1), este=este, norte=norte); return
    site_pending_confirms.append({
        "token": token, "etiqueta": etiqueta, "tipo": tipo,
        "este": float(este), "norte": float(norte),
        "dist_m": round(float(dist), 1), "umbral_m": float(umbral),
        "ts": time.strftime("%H:%M:%S"),
    })


def confirm_site_token(token: str):
    """Marca un objeto fuera de envolvente como aceptado explícitamente."""
    site_confirmed_tokens.add(token)
    for i, e in enumerate(list(site_pending_confirms)):
        if e["token"] == token:
            site_pending_confirms.pop(i); break


def discard_site_token(token: str):
    """Descarta la solicitud de confirmación (el objeto no se carga)."""
    for i, e in enumerate(list(site_pending_confirms)):
        if e["token"] == token:
            site_pending_confirms.pop(i); break


# ─── T1.2 · REGISTRO DE ATRIBUTOS CANÓNICOS ──────────────────────────────────
# El campo `calidad` no es decorativo: modula el ancho del intervalo de
# predicción del modelo. Un ancla de laboratorio de una sola probeta y un
# análogo de otra mina no pueden producir la misma confianza.

QUALITY_LABELS = {
    0: "sin_asignar",
    1: "ensayo_del_sitio",
    2: "componente_RMR_local",
    3: "analogo_del_distrito",
    4: "literatura",
}
# Multiplicador del semiancho del intervalo de predicción según procedencia del
# ancla de UCS. calidad 0 no tiene factor: no puede entrar al entrenamiento.
QUALITY_PI_FACTOR = {0: None, 1: 1.00, 2: 1.30, 3: 1.60, 4: 2.00}
# Ensanche adicional cuando el ancla proviene de una sola probeta (sin SD).
# El Albitófiro de Karzulovic carece de desviación estándar, lo que sugiere una
# única probeta: se acepta el valor, pero la incertidumbre debe reflejarlo.
SINGLE_SPECIMEN_PI_FACTOR = 1.35
# (P1c-B.5) Umbral de coeficiente de variación sobre el que la interfaz alerta
# y el intervalo de predicción se ensancha. Bht mide CV=0,57 (cuatro métodos
# independientes, convergentes) frente a CV~0,10-0,21 de las demás unidades
# con banda: la etiqueta no es menos confiable, es intrínsecamente más ancha,
# y el intervalo debe reflejar eso en vez de fingir la misma precisión.
HIGH_CV_THRESHOLD = 0.35
HIGH_CV_PI_FACTOR = 1.30


# (A.1) Roles del vocabulario. Enumeración EXTENSIBLE: agregar un rol nuevo es
# añadirlo aquí; las reglas de traslape (A.5) operan sobre el rol, no sobre una
# lista cerrada de casos. `estructura` predomina sobre todo lo demás.
ATTR_ROLES = ("litologia", "alteracion", "estructura")

# LA BANDA DE UCS ES PROPIEDAD DE LA LITOLOGÍA.
# Karzulovic reporta por litología, no por litología×alteración. Por eso los
# campos de banda (ucs_*, fuente, calidad) SOLO aplican a rol="litologia"; en
# los demás roles quedan nulos y la interfaz no los ofrece.
#   Bht+Fk y Bht+otra alteración son dominios DISTINTOS que heredan la MISMA
#   banda como valor previo. Si el MWD muestra que difieren, eso es un
#   hallazgo, no un error.
ROLES_CON_BANDA_UCS = ("litologia",)


@dataclass
class Attribute:
    """
    Atributo canónico de vocabulario.

    `rol` decide qué significa el atributo y cómo se compone con otros en un
    punto (ver resolve_overlap_by_role). `nivel`/`padre` describen la jerarquía
    unidad→subunidad, que solo tiene sentido dentro de un mismo rol.
    """
    id: str
    nombre_oficial: str
    sitio: str = ACTIVE_SITE
    rol: str = "litologia"                   # ver ATTR_ROLES
    nivel: str = "unidad"                    # "unidad" | "subunidad"
    padre: Optional[str] = None              # id de la unidad que la contiene
    ucs_min: Optional[float] = None
    ucs_max: Optional[float] = None
    ucs_media: Optional[float] = None
    ucs_sd: Optional[float] = None
    ucs_n: Optional[int] = None              # nº de probetas (None = desconocido)
    fuente: str = ""
    calidad: int = 0
    fecha: str = ""
    mi: Optional[float] = None
    modulo_E: Optional[float] = None         # GPa
    poisson: Optional[float] = None
    densidad: Optional[float] = None         # t/m³
    notas: str = ""
    # (P1c-B.4) Cuatro campos que distinguen DOS conceptos que NO son lo
    # mismo, deliberadamente separados para no poder confundirlos:
    #   ucs_central                  el valor con el que el modelo ENTRENA
    #                                 (p.ej. σci de un ajuste Hoek-Brown — no
    #                                 necesariamente la media aritmética de
    #                                 probetas, por eso un nombre distinto de
    #                                 ucs_media).
    #   dispersion_min/dispersion_max variabilidad OBSERVADA del material
    #                                 (rango real de resultados de ensayo).
    # ucs_min/ucs_max siguen siendo la banda de CONFIANZA sobre ucs_central,
    # igual que para el resto del vocabulario. Declarar la dispersión como si
    # fuera la banda de confianza afirmaría una homogeneidad que los datos no
    # respaldan (Bht: banda 100-145 vs. dispersión real 64,5-296,9).
    ucs_central: Optional[float] = None
    dispersion_min: Optional[float] = None
    dispersion_max: Optional[float] = None
    ucs_cv: Optional[float] = None

    def usa_banda_ucs(self) -> bool:
        """
        (A.1/A.4) ¿A este rol le corresponde tener banda de UCS? Solo la
        litología. Una alteración nunca tendrá ensayo uniaxial propio, así que
        exigirle banda la convertiría en un bloqueo permanente e insalvable.
        """
        return self.rol in ROLES_CON_BANDA_UCS

    def tiene_banda_ucs(self) -> bool:
        """True si hay un ancla de UCS utilizable como etiqueta de entrenamiento."""
        if not self.usa_banda_ucs(): return False
        return any(v is not None for v in
                   (self.ucs_central, self.ucs_media, self.ucs_min, self.ucs_max))

    def ucs_ancla(self) -> Optional[float]:
        """
        Valor puntual de UCS a usar como etiqueta. None si no hay banda.

        `ucs_central` tiene prioridad cuando existe: es el valor documentado
        explícitamente como central (p.ej. σci de Hoek-Brown), distinto de
        una media aritmética de probetas. Para el vocabulario prepoblado
        antes de B.4, que no lo trae, el comportamiento es idéntico a antes.
        """
        if self.ucs_central is not None: return float(self.ucs_central)
        if self.ucs_media is not None: return float(self.ucs_media)
        if self.ucs_min is not None and self.ucs_max is not None:
            return (float(self.ucs_min) + float(self.ucs_max)) / 2.0
        for v in (self.ucs_min, self.ucs_max):
            if v is not None: return float(v)
        return None

    def alta_variabilidad(self) -> bool:
        """(B.5) True si el CV documentado supera el umbral de alerta."""
        return self.ucs_cv is not None and self.ucs_cv > HIGH_CV_THRESHOLD

    def pi_factor(self) -> Optional[float]:
        """
        Factor de ensanche del intervalo de predicción, según la calidad del
        ancla, si proviene de una sola probeta, y (B.5) si el CV documentado
        excede el umbral de alta variabilidad. None si el atributo no es
        entrenable (calidad 0 o sin banda).
        """
        base = QUALITY_PI_FACTOR.get(self.calidad)
        if base is None or not self.tiene_banda_ucs(): return None
        f = base
        if self.ucs_sd is None and (self.ucs_n is None or self.ucs_n <= 1):
            f *= SINGLE_SPECIMEN_PI_FACTOR
        if self.alta_variabilidad():
            f *= HIGH_CV_PI_FACTOR
        return round(f, 4)

    def entrenable(self) -> Tuple[bool, str]:
        """
        (puede entrenar, motivo si no).

        (A.4) Los roles sin banda de UCS quedan EXENTOS del chequeo: no
        bloquean, porque nunca van a tener ensayo. Se registran, componen
        dominio, y no participan.
        """
        if not self.usa_banda_ucs():
            return True, ""
        if self.calidad == 0:
            return False, "calidad 0 (sin_asignar)"
        if not self.tiene_banda_ucs():
            return False, "sin banda de UCS asignada"
        return True, ""


attr_registry: Dict[str, Attribute] = {}

# ─── COLISIÓN DE NOMENCLATURA Fk ↔ Kfa ───────────────────────────────────────
# Registrada en las notas de AMBOS atributos, no solo en un comentario: el
# registro de vocabulario es lo que se publica como anexo de la memoria, y esta
# es exactamente la clase de confusión que ese anexo existe para evitar.
COLISION_FK_KFA = (
    "⚠ COLISIÓN DE NOMENCLATURA Fk ↔ Kfa: 'Fk' es feldespato potásica, una "
    "ALTERACIÓN; 'Kfa' es Albitófiro, una LITOLOGÍA. Son strings casi "
    "invertidos con roles OPUESTOS. Esta colisión originó una confusión que "
    "estuvo a punto de invalidar el 66% del metraje de sondaje (los 1.176,3 m "
    "de Albitófiro). El campo `rol` existe en buena medida por este caso: "
    "distingue los dos aunque el texto se parezca, y hace que un traslape "
    "entre ellos sea composición (roles distintos) y no conflicto."
)


def seed_attribute_registry(force: bool = False):
    """
    Prepobla el registro con la tabla de roca intacta de Karzulovic & Asoc.
    Ltda., "Evaluación Geotécnica Caserones Mina Punta del Cobre", Tabla 3.2,
    y con los códigos de unidad observados en los sondajes MPC.

    Dos trampas de nomenclatura quedan documentadas en el propio registro:

    1. `Kpcsb` se usa en la literatura tanto para la Brecha basal (unidad
       padre, según Marschik) como para la Brecha sedimentaria (una de sus
       subunidades, según Ortiz et al.). Se registran con identificadores
       distintos —`Kpcsb_basal` y `Kpcsb_sedimentaria`— y la ambigüedad queda
       anotada en ambos.

    2. `Fk` (feldespato potásica, ALTERACIÓN) y `Kfa` (Albitófiro, LITOLOGÍA)
       son strings casi invertidos con roles OPUESTOS. Ver COLISION_FK_KFA.
    """
    if attr_registry and not force: return
    # Resembrar reconstruye el vocabulario COMPLETO: los alias deben irse con
    # los atributos. Si sobrevivieran, quedarían apuntando a ids que ya no
    # existen (o que fueron redefinidos), y resolve_alias devolvería un
    # atributo fantasma sin que nada lo advirtiera.
    attr_registry.clear()
    alias_registry.clear()
    pending_aliases.clear()
    FUENTE_K = "Karzulovic & Asoc. 2005, Tabla 3.2 (roca intacta)"
    AMB_KPCSB = ("AMBIGÜEDAD DE NOMENCLATURA: el código 'Kpcsb' se usa en la "
                 "literatura tanto para la Brecha basal (unidad padre, Marschik) "
                 "como para la Brecha sedimentaria (subunidad, Ortiz et al.). "
                 "Aquí se distinguen con ids explícitos.")
    defs = [
        # ── Unidades observadas en los sondajes MPC ──────────────────────────
        Attribute(id="Kfa", nombre_oficial="Albitófiro", rol="litologia", nivel="unidad",
                  ucs_min=274.3, ucs_max=304.9, ucs_media=289.6,
                  ucs_sd=None, ucs_n=None, calidad=1, fuente=FUENTE_K,
                  mi=11.3, modulo_E=71.6, poisson=0.15, densidad=2.85,
                  notas=("La tabla no reporta desviación estándar, lo que sugiere una "
                         "única probeta. Se acepta el valor, pero el intervalo de "
                         "predicción se ensancha (ucs_n desconocido → marcar). "
                         "66% del metraje de sondaje MPC (1.176,3 m). "
                         + COLISION_FK_KFA)),
        # ── Alteraciones ─────────────────────────────────────────────────────
        Attribute(id="Fk", nombre_oficial="Feldespato potásica", rol="alteracion",
                  nivel="unidad", calidad=0,
                  notas=("Alteración potásica. Sin banda de UCS y NUNCA la tendrá: "
                         "Karzulovic reporta por litología, no por litología×alteración. "
                         "Por eso no participa del chequeo de bloqueo (A.4). "
                         + COLISION_FK_KFA)),
        # (P1c-Adenda B) Brecha Hidrotermal, registrada tras el ajuste Hoek-Brown.
        #
        # LA TRAMPA DEL PROMEDIO 198,19: la hoja UCS-TX de BRECHA_2.XLS lista
        # ocho probetas BHT con σ1 promedio 198,19 MPa (fila 14). Ese promedio
        # NO es UCS — seis de las ocho son ensayos TRIAXIALES; su σ3 vive en
        # la hoja Envolvente, no en UCS-TX, y con los parámetros de abajo 6 MPa
        # de confinamiento agregan ~35% (σ1≈173 para un material de σci=128).
        # Toda lectura futura de ese libro DEBE filtrar por σ3=0 antes de
        # calcular estadísticas de UCS. La hoja RocData es la ENTRADA del
        # software (listado ensayo a ensayo TRX/UCS/UCS DEF/TID), no su
        # salida: ajusta una envolvente a pares (σ3,σ1), no convierte desde
        # módulo de Young ni velocidad de onda.
        #
        # AJUSTE HOEK-BROWN (roca intacta, s=1, a=0,5) sobre los 25 ensayos de
        # compresión del libro (15 triaxiales + 10 uniaxiales):
        #   σci=128,1 MPa · mi=14,77 · RMSE=51,8 MPa
        # Validado contra 18 ensayos brasileños que NO entraron en el ajuste:
        # predice σt=-8,63 MPa; lo medido da media -7,78 (rango -5,39 a
        # -10,25) — la forma de la envolvente es correcta.
        #
        # CORROBORACIÓN INDEPENDIENTE por carga puntual (PLT_MPC-NIVEL_175-
        # CZ_06_Sector_CAS1004S_CAP_5, 30 bloques irregulares con alteración
        # silícea, nivel 175, ensayados 30-03-2026 y 09-04-2026), separado por
        # modo de rotura porque solo la rotura por matriz representa roca
        # intacta: por matriz n=16 media 112,1 mediana 111,5 CV 0,563; por
        # discontinuidad n=13 media 120,1 mediana 113,9 CV 0,353; promedio de
        # informe (n=29) 119,7.
        #
        # CONVERGENCIA de cuatro métodos independientes — dos laboratorios,
        # tres tipos de ensayo, dos sectores: σci Hoek-Brown 128,1 · promedio
        # de los 10 uniaxiales 123,9 · carga puntual informe (n=29) 119,7 ·
        # carga puntual por matriz (n=16) 112,1.
        #
        # VERIFICACIÓN REGISTRADA: excluir las probetas de densidad anómala
        # (muestras 2 y 3, ρ=3,18 y 4,15 g/cm³) NO produce la banda 100-145 —
        # retira los valores altos (182,4 y 169,1) y baja la media a 110,9.
        # La densidad bimodal (1-5: 3,15-4,15 · 6-10: 2,63-2,77) tampoco
        # explica la variabilidad de UCS: muestra 7 (ρ=2,63) da 296,9 y
        # muestra 6 (ρ=2,64) da 69,0.
        Attribute(id="Bht", nombre_oficial="Brecha Hidrotermal", rol="litologia", nivel="unidad",
                  ucs_central=128.1,
                  # ucs_min/ucs_max: banda de CONFIANZA sobre ucs_central, no
                  # el rango de resistencia del material (ver dispersion_*).
                  ucs_min=100.0, ucs_max=145.0,
                  # dispersion_min/dispersion_max: variabilidad OBSERVADA
                  # (cuatro métodos independientes miden CV~0,56, no ~0,09).
                  dispersion_min=64.5, dispersion_max=296.9, ucs_cv=0.57,
                  mi=14.77, calidad=1, densidad=2.97,
                  fuente=("Hoek-Brown ajustado sobre 25 ensayos, BRECHA_2.XLS, "
                          "Laboratorio Punta del Cobre 19-06-2022. Corroborado por "
                          "carga puntual n=16 rotura por matriz, CAS1004S nivel 175, "
                          "marzo-abril 2026. σt ajustado -7,8 MPa (validado contra 18 "
                          "ensayos brasileños no usados en el ajuste)."),
                  notas=("33% del metraje MPC (576,9 m). No es una brecha débil: RQD "
                         "mediana 92,0 (mejor que el Albitófiro) y densidad media "
                         "2,97 t/m³ (máx 4,09), coherente con brecha mineralizada bien "
                         "cementada (magnetita/sulfuros). "
                         "ALERTA DE VARIABILIDAD (B.5, CV=0,57>0,35): la granularidad "
                         "de la etiqueta acota el techo del modelo — con todo Bht "
                         "etiquetado en 128,1, el modelo no puede predecir nada "
                         "distinto de eso dentro de Bht. Esto NO es un defecto de "
                         "resolución punto a punto (esa sí se cumple para dominio y "
                         "DI): es que la variabilidad interna de Bht excede la "
                         "resolución alcanzable para UCS, y se declara como "
                         "limitación, no se oculta ensanchando la banda de confianza.")),
        Attribute(id="Kpcli", nombre_oficial="Lavas Inferiores", rol="litologia", nivel="unidad",
                  calidad=0,
                  notas="Sin UCS de laboratorio. 1,2% del metraje MPC (20,8 m)."),
        Attribute(id="DL", nombre_oficial="Sin identificar", rol="litologia", nivel="unidad",
                  calidad=0,
                  notas="Código sin identificar en los sondajes. 0,2% del metraje MPC (3,1 m)."),
        # ── Brecha basal y sus subunidades ───────────────────────────────────
        Attribute(id="Kpcsb_basal", nombre_oficial="Brecha basal", rol="litologia", nivel="unidad",
                  calidad=0, fuente="Marschik (nomenclatura)", notas=AMB_KPCSB),
        Attribute(id="Brecha_mixta", nombre_oficial="Brecha mixta", rol="litologia", nivel="subunidad",
                  padre="Kpcsb_basal",
                  ucs_min=82.6, ucs_max=141.7, ucs_media=111.5, ucs_sd=23.6,
                  calidad=1, fuente=FUENTE_K,
                  mi=7.6, modulo_E=17.3, poisson=0.20, densidad=2.80,
                  notas="CV = 0,212."),
        Attribute(id="Kpcsb_sedimentaria", nombre_oficial="Brecha sedimentaria",
                  rol="litologia", nivel="subunidad", padre="Kpcsb_basal",
                  ucs_min=77.4, ucs_max=98.7, ucs_media=83.6, ucs_sd=8.6,
                  calidad=1, fuente=FUENTE_K,
                  mi=19.1, modulo_E=12.8, poisson=0.22, densidad=2.76,
                  notas="CV = 0,103. " + AMB_KPCSB),
        # ── Miembro Trinidad y sus subunidades ───────────────────────────────
        Attribute(id="Kpcs", nombre_oficial="Miembro Trinidad", rol="litologia", nivel="unidad",
                  calidad=0, notas="Unidad padre de las lutitas."),
        Attribute(id="Lutitas_normales", nombre_oficial="Lutitas normales",
                  rol="litologia", nivel="subunidad", padre="Kpcs",
                  ucs_min=117.1, ucs_max=134.9, ucs_media=126.0, ucs_sd=12.6,
                  calidad=1, fuente=FUENTE_K,
                  mi=15.8, modulo_E=16.4, poisson=0.28, densidad=2.45,
                  notas="CV = 0,100."),
        Attribute(id="Lutitas_metamorfoseadas", nombre_oficial="Lutitas metamorfoseadas",
                  rol="litologia", nivel="subunidad", padre="Kpcs",
                  ucs_min=186.8, ucs_max=221.8, ucs_media=204.3, ucs_sd=24.8,
                  calidad=1, fuente=FUENTE_K,
                  mi=20.8, modulo_E=89.0, poisson=0.115, densidad=2.50,
                  notas="CV = 0,121."),
        # ── Códigos de estructura de los sondajes (P2-T2.1) ──────────────────
        # Todos rol="estructura": no llevan banda de UCS (A.4) y nunca
        # bloquean el entrenamiento. calidad=0 es correcto aquí, no un hueco.
        Attribute(id="ZFR", nombre_oficial="Zona fracturada", rol="estructura",
                  nivel="unidad", calidad=0),
        Attribute(id="FRI", nombre_oficial="Fractura interna", rol="estructura",
                  nivel="unidad", calidad=0),
        Attribute(id="FM", nombre_oficial="Falla menor", rol="estructura",
                  nivel="unidad", calidad=0),
        Attribute(id="V", nombre_oficial="Veta", rol="estructura",
                  nivel="unidad", calidad=0,
                  notas="Sinónimo logueado como 'vet' en algunos sondajes."),
        Attribute(id="ZF", nombre_oficial="Zona de falla", rol="estructura",
                  nivel="unidad", calidad=0),
        Attribute(id="FI", nombre_oficial="Falla interna", rol="estructura",
                  nivel="unidad", calidad=0),
        Attribute(id="SD", nombre_oficial="Zona de cizalle", rol="estructura",
                  nivel="unidad", calidad=0),
        Attribute(id="Cto", nombre_oficial="Contacto", rol="estructura",
                  nivel="unidad", calidad=0,
                  notas=("Los contactos casi no están logueados como estructura en los "
                         "sondajes; la mayoría se DERIVAN de los límites de la tabla de "
                         "litología (P2-T2.3, tipo='contacto_derivado').")),
    ]
    for a in defs:
        attr_registry[a.id] = a
    _seed_default_aliases()


def attribute_children(attr_id: str) -> List[str]:
    """Ids de las subunidades cuyo padre es `attr_id`."""
    return [a.id for a in attr_registry.values() if a.padre == attr_id]


UCS_OVERLAP_CRITERIA = ("confianza", "dispersion")


def _ucs_overlap_range(a: Attribute, criterio: str) -> Optional[Tuple[float, float]]:
    """
    Rango UCS de `a` bajo el criterio pedido (P1c-B.7).

    "dispersion" usa dispersion_min/dispersion_max cuando la unidad los
    reporta (hoy, solo Bht); las unidades que no tienen dispersión propia
    documentada no fingen tenerla — caen a su banda de confianza, que es lo
    único que hay. "confianza" usa siempre ucs_min/ucs_max (la banda que ya
    trae TODO el vocabulario, sea o no la misma unidad la que reporta
    dispersión aparte).
    """
    if criterio == "dispersion" and a.dispersion_min is not None and a.dispersion_max is not None:
        return (float(a.dispersion_min), float(a.dispersion_max))
    if a.ucs_min is not None and a.ucs_max is not None:
        return (float(a.ucs_min), float(a.ucs_max))
    v = a.ucs_ancla()
    return (v, v) if v is not None else None


def ucs_band_overlap_matrix(criterio: str = "confianza") -> List[Dict]:
    """
    (P1c-B.7) Pares de litologías cuyas bandas de UCS se traslapan bajo
    `criterio` ("confianza" o "dispersion"). Solo litologías con banda
    utilizable (entrenables); una unidad sin banda no puede traslaparse con
    nada porque no tiene rango que comparar.
    """
    if criterio not in UCS_OVERLAP_CRITERIA:
        raise ValueError(f"criterio debe ser uno de {UCS_OVERLAP_CRITERIA}: «{criterio}»")
    unidades = [a for a in attr_registry.values() if a.usa_banda_ucs() and a.tiene_banda_ucs()]
    rangos = {a.id: r for a in unidades if (r := _ucs_overlap_range(a, criterio)) is not None}
    pares = []
    ids = sorted(rangos)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a_id, b_id = ids[i], ids[j]
            (amin, amax), (bmin, bmax) = rangos[a_id], rangos[b_id]
            if amax >= bmin and bmax >= amin:
                pares.append({"a": a_id, "b": b_id, "rango_a": (amin, amax),
                             "rango_b": (bmin, bmax), "criterio": criterio})
    return pares


def ucs_band_overlap_report() -> Dict[str, List[Dict]]:
    """
    (P1c-B.7) Matriz de traslape de bandas UCS bajo AMBOS criterios a la vez.
    Reportar solo uno fingiría un único panorama donde hay dos: bajo la
    dispersión observada Bht se traslapa con todo (incluido el Albitófiro);
    bajo la banda de confianza el panorama es distinto. La diferencia entre
    ambos ES el hallazgo — no un desacuerdo a resolver eligiendo uno.
    """
    return {c: ucs_band_overlap_matrix(c) for c in UCS_OVERLAP_CRITERIA}


def validate_attribute_tree() -> List[str]:
    """Errores estructurales del registro (padres inexistentes, niveles rotos)."""
    errs = []
    for a in attr_registry.values():
        if a.nivel not in ("unidad", "subunidad"):
            errs.append(f"{a.id}: nivel inválido '{a.nivel}'.")
        if a.nivel == "subunidad":
            if not a.padre:
                errs.append(f"{a.id}: subunidad sin padre declarado.")
            elif a.padre not in attr_registry:
                errs.append(f"{a.id}: padre '{a.padre}' no existe en el registro.")
            elif attr_registry[a.padre].nivel != "unidad":
                errs.append(f"{a.id}: padre '{a.padre}' no es una unidad.")
        elif a.padre:
            errs.append(f"{a.id}: es unidad pero declara padre '{a.padre}'.")
        if a.rol not in ATTR_ROLES:
            errs.append(f"{a.id}: rol inválido '{a.rol}'. Válidos: {ATTR_ROLES}.")
        if a.padre and a.padre in attr_registry and attr_registry[a.padre].rol != a.rol:
            errs.append(f"{a.id}: rol '{a.rol}' distinto del rol de su padre "
                        f"'{a.padre}' ('{attr_registry[a.padre].rol}'). La jerarquía "
                        f"unidad→subunidad solo existe dentro de un mismo rol.")
        if a.calidad not in QUALITY_LABELS:
            errs.append(f"{a.id}: calidad {a.calidad} fuera del catálogo.")
        # (A.1) Los campos de banda solo aplican a los roles que la usan.
        if not a.usa_banda_ucs():
            sucios = [c for c in ("ucs_min", "ucs_max", "ucs_media", "ucs_sd", "ucs_n")
                      if getattr(a, c) is not None]
            if sucios:
                errs.append(f"{a.id}: rol '{a.rol}' no lleva banda de UCS, pero tiene "
                            f"{', '.join(sucios)} con valor. La banda es propiedad de "
                            f"la litología.")
        for campo in ("ucs_min", "ucs_max", "ucs_media"):
            v = getattr(a, campo)
            if v is None: continue
            if not (UCS_CONFIG["physical_min"] <= v <= UCS_CONFIG["physical_max"]):
                errs.append(f"{a.id}.{campo} = {v} fuera de los límites físicos "
                            f"[{UCS_CONFIG['physical_min']}, {UCS_CONFIG['physical_max']}] MPa.")
    return errs


def attrs_by_role(rol: str) -> List[Attribute]:
    return [a for a in attr_registry.values() if a.rol == rol]


# ─── T1.3 / A.2 · REGISTRO DE ALIAS (CONJUNTO POR ROL) ───────────────────────
# Un alias apunta a exactamente UN ATRIBUTO POR ROL, y resuelve a un
# diccionario {rol: atributo_id}. Dos atributos del MISMO rol en un mismo alias
# es un ERROR, no una advertencia — la garantía de unicidad se conserva, solo
# que ahora es por rol.
#
#     "Kfa"    → {"litologia": "Kfa"}
#     "Fk"     → {"alteracion": "Fk"}
#     "Bht_Fk" → {"litologia": "Bht", "alteracion": "Fk"}
#
# Por qué no la alternativa: crear un atributo canónico por cada par
# litología×alteración produce n×m entradas, casi todas sin ensayo de
# laboratorio asociado, y multiplica el registro sin aportar información.
#
# El emparejamiento es insensible a mayúsculas, espacios y acentos; el alias
# almacenado conserva el texto crudo original.

# (P2-T2.1) "sondaje_estructura" se agrega para los códigos de discontinuidad
# de la tabla de estructuras de los sondajes (ZFR, FRI, FM, V, ZF, FI, SD),
# distinto de "sondaje_unidad" (litología) aunque ambos vengan de los mismos
# seis CSV — el origen registra DE QUÉ TABLA vino el texto, no solo de qué
# fuente de archivo.
ALIAS_ORIGINS = ("dxf_layer", "sondaje_unidad", "sondaje_estructura", "excel", "manual")
# Separadores con que Leapfrog compone nombres de capa (A.3).
COMPOSITE_SEPARATORS = r"[_\-+\s]+"


@dataclass
class Alias:
    texto_crudo: str
    atributos: Dict[str, str] = field(default_factory=dict)   # rol → atributo_id
    origen: str = "manual"

    @property
    def atributo_id(self) -> Optional[str]:
        """Compatibilidad: el atributo de rol litología, si lo hay."""
        return self.atributos.get("litologia")

    def es_compuesto(self) -> bool:
        return len(self.atributos) > 1


# clave = texto normalizado → Alias (con el texto crudo original preservado)
alias_registry: Dict[str, Alias] = {}
# Bandeja de pendientes de asignar: textos vistos que no resuelven a ningún
# atributo. clave normalizada → {texto_crudo, origenes:set, n_vistas, propuesta}
# `propuesta` es la descomposición sugerida por A.3 (o None), que SIEMPRE
# requiere confirmación explícita: se propone, nunca se acepta sola.
pending_aliases: Dict[str, Dict] = {}


class AliasConflict(Exception):
    """
    El alias ya apunta a otro atributo DEL MISMO ROL, o se intentó mapearlo a
    dos atributos del mismo rol a la vez. Es un error, no una advertencia.
    """


def _coerce_attr_map(atributos) -> Dict[str, str]:
    """
    Normaliza la entrada a {rol: atributo_id}. Acepta un id suelto (se deduce
    el rol del registro), una lista de ids, o un dict ya formado. Dos ids del
    mismo rol → AliasConflict.
    """
    if isinstance(atributos, str):
        atributos = [atributos]
    if isinstance(atributos, dict):
        out = {}
        for rol, aid in atributos.items():
            if aid is None: continue
            if aid not in attr_registry:
                raise KeyError(f"Atributo '{aid}' no existe en el registro.")
            real = attr_registry[aid].rol
            if rol != real:
                raise ValueError(f"El atributo '{aid}' tiene rol '{real}', "
                                 f"no '{rol}'.")
            if rol in out and out[rol] != aid:
                raise AliasConflict(f"Dos atributos del rol '{rol}' en el mismo "
                                    f"alias: '{out[rol]}' y '{aid}'.")
            out[rol] = aid
        return out
    out = {}
    for aid in atributos:
        if aid is None: continue
        if aid not in attr_registry:
            raise KeyError(f"Atributo '{aid}' no existe en el registro.")
        rol = attr_registry[aid].rol
        if rol in out and out[rol] != aid:
            raise AliasConflict(f"Dos atributos del rol '{rol}' en el mismo alias: "
                                f"'{out[rol]}' y '{aid}'. Un alias apunta a "
                                f"exactamente un atributo por rol.")
        out[rol] = aid
    return out


def register_alias(texto_crudo: str, atributos, origen: str = "manual",
                   merge: bool = False) -> Alias:
    """
    Vincula `texto_crudo` a uno o varios atributos de ROLES DISTINTOS.

    `atributos` puede ser un id suelto ("Kfa"), una lista (["Bht","Fk"]) o un
    dict {rol: id}. Lanza AliasConflict si el alias ya apunta a otro atributo
    del mismo rol (o si la entrada trae dos del mismo rol), y KeyError si algún
    atributo no existe. Con `merge=True` se añaden roles nuevos conservando los
    ya registrados; sin él, la entrada reemplaza el mapeo completo.
    """
    key = _norm_txt(texto_crudo)
    if not key:
        raise ValueError("Alias vacío.")
    if origen not in ALIAS_ORIGINS:
        raise ValueError(f"Origen '{origen}' inválido. Válidos: {ALIAS_ORIGINS}.")
    nuevos = _coerce_attr_map(atributos)
    if not nuevos:
        raise ValueError("Alias sin ningún atributo destino.")
    prev = alias_registry.get(key)
    if prev is not None:
        for rol, aid in nuevos.items():
            anterior = prev.atributos.get(rol)
            if anterior is not None and anterior != aid:
                raise AliasConflict(
                    f'El alias "{texto_crudo}" ya apunta a "{anterior}" en el rol '
                    f'"{rol}"; no puede apuntar además a "{aid}". '
                    f"Un alias resuelve a exactamente un atributo por rol.")
        if merge:
            nuevos = {**prev.atributos, **nuevos}
    al = Alias(texto_crudo=str(texto_crudo).strip(), atributos=nuevos, origen=origen)
    alias_registry[key] = al
    pending_aliases.pop(key, None)
    return al


def unregister_alias(texto_crudo: str):
    alias_registry.pop(_norm_txt(texto_crudo), None)


def resolve_alias(texto_crudo: str) -> Dict[str, str]:
    """
    Mapa {rol: atributo_id} al que resuelve el texto. Dict VACÍO si no resuelve.
    (A.2) Antes devolvía un id suelto; ahora un texto compuesto como "Bht_Fk"
    resuelve a dos atributos de roles distintos.
    """
    if texto_crudo is None: return {}
    key = _norm_txt(texto_crudo)
    al = alias_registry.get(key)
    if al is not None: return dict(al.atributos)
    # Coincidencia directa contra id o nombre oficial (insensible a caso/acentos).
    for a in attr_registry.values():
        if key in (_norm_txt(a.id), _norm_txt(a.nombre_oficial)):
            return {a.rol: a.id}
    return {}


def resolve_alias_rol(texto_crudo: str, rol: str = "litologia") -> Optional[str]:
    """Id del atributo de ese rol al que resuelve el texto, o None."""
    return resolve_alias(texto_crudo).get(rol)


# ─── A.3 · DESCOMPOSICIÓN SUGERIDA DE NOMBRES COMPUESTOS ─────────────────────
# Bht_Fk.dxf demuestra que las capas de Leapfrog pueden traer litología y
# alteración compuestas en un solo nombre. La composición se PROPONE, nunca se
# acepta sola: requiere confirmación explícita. Una vez confirmada, el string
# crudo completo se almacena como alias propio para que la próxima vez resuelva
# directo, sin volver a descomponer.

def decompose_layer_name(texto_crudo: str) -> Optional[Dict]:
    """
    Intenta descomponer un nombre compuesto en atributos de roles distintos.

    Devuelve None si no hay propuesta que hacer. Si la hay:
        {"texto_crudo": str, "atributos": {rol: aid},
         "tokens": {token: aid|None}, "sin_resolver": [tokens]}

    Reglas: se parte por `_`, `-`, `+` y espacios; cada token se empareja contra
    el registro (insensible a caso/espacios/acentos); si dos tokens resuelven al
    MISMO rol no se propone nada (es ambiguo y va a la bandeja); los tokens sin
    correspondencia se reportan.
    """
    if not texto_crudo: return None
    tokens = [t for t in re.split(COMPOSITE_SEPARATORS, str(texto_crudo).strip()) if t]
    if len(tokens) < 2: return None
    por_rol: Dict[str, str] = {}
    detalle: Dict[str, Optional[str]] = {}
    sin_resolver: List[str] = []
    for t in tokens:
        m = resolve_alias(t)
        if not m:
            detalle[t] = None; sin_resolver.append(t); continue
        if len(m) > 1:
            # Un token que ya es compuesto no puede anidarse en otro compuesto.
            return None
        rol, aid = next(iter(m.items()))
        if rol in por_rol and por_rol[rol] != aid:
            # Dos tokens del mismo rol → ambiguo: no se propone nada.
            return None
        por_rol[rol] = aid
        detalle[t] = aid
    if len(por_rol) < 2:
        return None      # no hay composición de roles distintos que proponer
    return {"texto_crudo": str(texto_crudo).strip(), "atributos": por_rol,
            "tokens": detalle, "sin_resolver": sin_resolver}


def confirm_composite_alias(texto_crudo: str, origen: str = "manual") -> Alias:
    """
    Acepta la descomposición propuesta para `texto_crudo` y la almacena como
    alias propio del string crudo completo. Lanza ValueError si no hay
    propuesta vigente (nunca inventa una composición no propuesta).
    """
    key = _norm_txt(texto_crudo)
    e = pending_aliases.get(key)
    prop = (e or {}).get("propuesta") or decompose_layer_name(texto_crudo)
    if not prop:
        raise ValueError(f'No hay descomposición propuesta para "{texto_crudo}".')
    return register_alias(prop["texto_crudo"], prop["atributos"], origen)


def note_pending_alias(texto_crudo: str, origen: str = "manual"):
    """
    Registra un texto no reconocido en la bandeja de pendientes, junto con la
    descomposición sugerida (A.3) si la hay. La propuesta es solo eso.
    """
    if texto_crudo is None: return
    key = _norm_txt(texto_crudo)
    if not key or key in alias_registry: return
    if resolve_alias(texto_crudo): return
    e = pending_aliases.setdefault(key, {"texto_crudo": str(texto_crudo).strip(),
                                          "origenes": set(), "n_vistas": 0,
                                          "propuesta": None})
    e["origenes"].add(origen)
    e["n_vistas"] += 1
    if e.get("propuesta") is None:
        e["propuesta"] = decompose_layer_name(texto_crudo)


def resolve_or_note(texto_crudo: str, origen: str = "manual") -> Dict[str, str]:
    """
    Resuelve el alias a {rol: atributo_id}; si no resuelve, lo encola en
    pendientes (con propuesta de descomposición si aplica). Nunca inventa.
    """
    m = resolve_alias(texto_crudo)
    if not m:
        note_pending_alias(texto_crudo, origen)
    return m


def pending_alias_count() -> int:
    return len(pending_aliases)


def pending_with_proposal() -> List[Dict]:
    """Pendientes que traen una descomposición sugerida esperando confirmación."""
    return [e for e in pending_aliases.values() if e.get("propuesta")]


def _seed_default_aliases():
    """Alias evidentes de los códigos de sondaje y sus nombres oficiales."""
    base = {
        "Kfa": ["KFA", "Albitofiro", "ALB", "Albitófiro"],
        "Bht": ["BHT", "Brecha Hidrotermal", "Bx Hidrotermal", "BXH"],
        "Kpcli": ["KPCLI", "Lavas Inferiores"],
        "DL": ["dl"],
        "Fk": ["FK", "Feldespato potasica", "Feldespato potásica",
               "Potasica", "Potásica", "K-feldespato"],
        "Brecha_mixta": ["Brecha mixta", "Bx mixta"],
        "Kpcsb_sedimentaria": ["Brecha sedimentaria", "Bx sedimentaria"],
        "Kpcsb_basal": ["Brecha basal"],
        "Kpcs": ["Miembro Trinidad", "Trinidad"],
        "Lutitas_normales": ["Lutitas normales", "Lutita normal"],
        "Lutitas_metamorfoseadas": ["Lutitas metamorfoseadas", "Lutita metamorfoseada"],
        # (P2-T2.1) Códigos de estructura y sinónimos. V/vet es el caso
        # explícito del enunciado: mismo discriminador, dos strings.
        "ZFR": ["ZFR", "Zona fracturada"],
        "FRI": ["FRI", "Fractura interna"],
        "FM": ["FM", "Falla menor"],
        "V": ["V", "VET", "vet", "Vet", "Veta"],
        "ZF": ["ZF", "Zona de falla"],
        "FI": ["FI", "Falla interna"],
        "SD": ["SD", "Zona de cizalle", "Cizalle"],
        "Cto": ["Cto", "CTO", "Contacto"],
    }
    for aid, textos in base.items():
        if aid not in attr_registry: continue
        for t in textos:
            try: register_alias(t, aid, "manual")
            except (AliasConflict, ValueError, KeyError): pass


# ─── T1.5 (corregido por A.4) · ESTADO SIN-ASIGNAR QUE BLOQUEA ───────────────
# Una LITOLOGÍA con calidad 0 o sin banda de UCS no puede entrar al
# entrenamiento. El intento falla de forma ruidosa, nombrando qué atributos
# faltan y cuánto representan. La vía prevista para continuar es excluir
# EXPLÍCITAMENTE, con justificación registrada.
#
# (A.4) EL CHEQUEO ALCANZA SOLO A rol="litologia". La regla original —"calidad
# 0 bloquea"— habría hecho que Fk (feldespato potásica) bloqueara de forma
# permanente e insalvable: las alteraciones no tienen banda de UCS y nunca la
# van a tener, porque Karzulovic reporta por litología, no por
# litología×alteración. Alteraciones y estructuras se registran, componen
# dominio, y no participan del chequeo.
#
# LA BANDA DE UCS ES PROPIEDAD DE LA LITOLOGÍA. Bht+Fk y Bht+otra alteración
# son dominios DISTINTOS que heredan la MISMA banda como valor previo. Si el
# MWD muestra que difieren, eso es un HALLAZGO, no un error.

# atributo_id → {"justificacion": str, "fecha": str}
attribute_exclusions: Dict[str, Dict] = {}
# Metraje por atributo declarado desde los sondajes (lo puebla el cargador de
# sondajes cuando exista; vacío no es un default, es "aún no medido").
attribute_meters: Dict[str, float] = {}


def exclude_attribute(attr_id: str, justificacion: str):
    """Excluye explícitamente un atributo del entrenamiento, con justificación."""
    if attr_id not in attr_registry:
        raise KeyError(f"Atributo '{attr_id}' no existe en el registro.")
    j = (justificacion or "").strip()
    if not j:
        raise ValueError("La exclusión requiere una justificación explícita.")
    attribute_exclusions[attr_id] = {"justificacion": j, "fecha": time.strftime("%Y-%m-%d %H:%M")}


def unexclude_attribute(attr_id: str):
    attribute_exclusions.pop(attr_id, None)


def attribute_point_counts() -> Dict[str, int]:
    """Puntos MWD clasificados por atributo, contando TODOS los roles del punto."""
    counts: Dict[str, int] = {}
    for p in all_points():
        for aid in (getattr(p, "atributos", None) or {}).values():
            if aid: counts[aid] = counts.get(aid, 0) + 1
    return counts


def training_blockers() -> List[Dict]:
    """
    Atributos que impiden entrenar: de rol LITOLOGÍA, presentes en los datos, no
    excluidos explícitamente, y sin ancla de UCS utilizable.

    (A.4) Alteraciones y estructuras quedan fuera del chequeo por construcción:
    Attribute.entrenable() las declara aptas porque su rol no lleva banda.

    Cada entrada: {id, nombre, rol, motivo, metros, puntos}.
    """
    counts = attribute_point_counts()
    presentes = set(counts) | set(attribute_meters)
    # Un atributo referenciado por una capa cargada también cuenta como presente
    # aunque todavía no tenga puntos (el cruce puede no haberse corrido).
    for lay in layers.values():
        for aid in (getattr(lay, "atributos", None) or {}).values():
            if aid: presentes.add(aid)
    # (A.4) Rol de las identidades que TODAVÍA no están en el registro. Una
    # capa sin vocabulario asignado igual declara su rol vía layer_role_ids()
    # —que arma la identidad con el nombre de la capa bajo su `kind`—, y ese
    # rol basta para saber si le corresponde banda de UCS. Sin esto, una
    # falla sin alias bloqueaba el entrenamiento solo por no estar
    # registrada, aunque una estructura nunca vaya a tener ensayo uniaxial:
    # con los datos reales de Pucobre eran 10 fallas bloqueando (FChavito,
    # FPaola, FM1-FM4, FI1-FI3).
    rol_por_identidad: Dict[str, str] = {}
    for lay in layers.values():
        for rol, ident in layer_role_ids(lay).items():
            if ident: rol_por_identidad.setdefault(ident, rol)
    for p in all_points():
        for rol, ident in (getattr(p, "atributos", None) or {}).items():
            if ident: rol_por_identidad.setdefault(ident, rol)

    out = []
    for aid in sorted(presentes):
        if aid in attribute_exclusions: continue
        a = attr_registry.get(aid)
        if a is None:
            rol = rol_por_identidad.get(aid, "?")
            # Solo los roles que llevan banda de UCS pueden bloquear.
            if rol != "?" and rol not in ROLES_CON_BANDA_UCS: continue
            out.append({"id": aid, "nombre": aid, "rol": rol,
                        "motivo": "no está en el registro de vocabulario",
                        "metros": attribute_meters.get(aid), "puntos": counts.get(aid, 0)})
            continue
        ok, motivo = a.entrenable()
        if ok: continue
        out.append({"id": aid, "nombre": a.nombre_oficial, "rol": a.rol, "motivo": motivo,
                    "metros": attribute_meters.get(aid), "puntos": counts.get(aid, 0)})
    return out


def training_block_message(blockers: Optional[List[Dict]] = None) -> Optional[str]:
    """Mensaje de bloqueo, o None si no hay bloqueadores."""
    bl = training_blockers() if blockers is None else blockers
    if not bl: return None
    partes = []
    for b in bl:
        det = []
        if b.get("metros") is not None: det.append(f"{b['metros']:.1f} m".replace(".", ","))
        if b.get("puntos"): det.append(f"{b['puntos']} pts")
        partes.append(f"{b['id']}" + (f" {' · '.join(det)}" if det else ""))
    return (f"No se puede entrenar: {len(bl)} "
            f"litología{'s' if len(bl) != 1 else ''} sin banda de UCS asignada "
            f"({' · '.join(partes)}). "
            f"Asignar en el registro de vocabulario o excluir explícitamente.")


# ─── T1.4 reescrito por A.5 · RESOLUCIÓN DE TRASLAPE POR ROL ─────────────────
# Reemplaza la lógica `lito_hit[i] = name`, que hacía ganar a la última capa
# cargada y produjo un modelo degenerado con R² = 1,0. Leapfrog modela con
# métodos probabilísticos y las mallas pueden interponerse; el MWD es la tercera
# fuente que evalúa dónde acertó la interpolación.
#
# La tabla de casos se reduce a CUATRO REGLAS sobre el rol:
#
#   Conflicto    Dos atributos del MISMO rol en un punto → ambiguo, excluir,
#                contabilizar.
#   Composición  Atributos de roles DISTINTOS → se componen en un dominio.
#   Anidamiento  Dentro de un mismo rol, unidad + su subunidad → gana la
#                subunidad. NO es conflicto.
#   Predominio   rol="estructura" predomina sobre todo lo demás.
#
# La clave de dominio es el par (litologia, alteracion|None); la banda de UCS
# se hereda de la litología.
#
# EQUIVALENCIA DE EMPAQUETADO: las reglas operan sobre ATRIBUTOS CANÓNICOS, no
# sobre nombres de capa. Por eso el resultado es idéntico venga la información
# en una malla compuesta (Bht_Fk.dxf) o en dos mallas separadas que se
# traslapan. Cómo vino empaquetada no puede cambiar el dominio.
#
# Todo punto excluido por ambigüedad se contabiliza y reporta, nunca se
# descarta en silencio.

LAYER_KINDS = ATTR_ROLES

# Contabilidad de la última corrida de clasificación.
overlap_stats: Dict = {
    "n_puntos": 0,
    "n_ambiguos": 0,
    "n_subunidad_gana": 0,
    "n_compuestos": 0,   # puntos con litología + alteración
    "n_sin_lito": 0,
    "n_sin_clasificar": 0,
    "casos": {},         # "A | B" → nº de puntos
    "motivos": {},       # motivo → nº de puntos
}


def layer_role_ids(layer) -> Dict[str, str]:
    """
    {rol: identidad} que aporta una capa.

    La identidad es el ATRIBUTO CANÓNICO cuando la capa lo tiene asignado; si
    no, se usa el nombre de la capa bajo el rol que declare `kind`. Esa reserva
    mantiene funcionando las mallas todavía sin vocabulario asignado (y con
    ellas el canario, cuyo DXF no está en el registro).
    """
    attrs = getattr(layer, "atributos", None) or {}
    if attrs: return dict(attrs)
    kind = getattr(layer, "kind", "litologia")
    if kind not in ATTR_ROLES: kind = "litologia"
    return {kind: layer.name}


def set_layer_attributes(layer, atributos: Dict[str, str]):
    """
    Asigna el mapa {rol: atributo_id} a una capa y sincroniza `kind` y `nivel`.

    `kind` pasa a ser el rol predominante de la capa (estructura > litología >
    alteración), y `nivel` el del atributo de litología. Mantenerlos derivados
    evita que la capa declare un rol y el vocabulario otro.
    """
    layer.atributos = dict(atributos or {})
    if "estructura" in layer.atributos: layer.kind = "estructura"
    elif "litologia" in layer.atributos: layer.kind = "litologia"
    elif "alteracion" in layer.atributos: layer.kind = "alteracion"
    lito = layer.atributos.get("litologia")
    layer.nivel = attr_registry[lito].nivel if lito in attr_registry else None
    return layer


def _hit_meta(rol: str, ident: str) -> Dict:
    """Nivel y padre de una identidad; 'desconocido' si no es atributo canónico."""
    a = attr_registry.get(ident)
    if a is not None and a.rol == rol:
        return {"nivel": a.nivel, "padre": a.padre, "canonico": True}
    return {"nivel": "desconocido", "padre": None, "canonico": False}


def _resolve_one_role(rol: str, idents: List[str]) -> Tuple[Optional[str], str]:
    """
    Aplica Anidamiento y Conflicto dentro de UN rol.
    Devuelve (identidad_ganadora | None, motivo). motivo == "" es resolución
    limpia; "subunidad_gana" es limpia y además señala anidamiento.
    """
    unicos = sorted(set(idents))
    if not unicos: return None, ""
    if len(unicos) == 1: return unicos[0], ""

    info = [{"id": i, **_hit_meta(rol, i)} for i in unicos]
    unidades = [d for d in info if d["nivel"] == "unidad"]
    subunidades = [d for d in info if d["nivel"] == "subunidad"]
    desconocidas = [d for d in info if d["nivel"] == "desconocido"]

    # Sin nivel declarado no se puede distinguir un anidamiento legítimo de un
    # error de modelamiento: es ambiguo, nunca un ganador arbitrario.
    if desconocidas:
        return None, (f"traslape en rol '{rol}' con capa de nivel no declarado: "
                      + ", ".join(d["id"] for d in desconocidas))
    if len(subunidades) > 1:
        padres = {d["padre"] for d in subunidades}
        return None, (f"dos subunidades del mismo padre" if len(padres) == 1
                      else f"dos subunidades de padres distintos")
    if len(subunidades) == 1:
        sub = subunidades[0]
        ajenas = [u for u in unidades if u["id"] != sub["padre"]]
        if ajenas:
            return None, (f"subunidad traslapada con unidad ajena en rol '{rol}': "
                          + ", ".join(u["id"] for u in ajenas))
        return sub["id"], "subunidad_gana"   # Anidamiento
    return None, (f"dos unidades distintas" if rol == "litologia"
                  else f"dos atributos del rol '{rol}'")   # Conflicto


def resolve_overlap_by_role(hits: Dict[str, List[str]]) -> Tuple[Dict[str, str], str, bool]:
    """
    Resuelve el traslape completo de un punto.

    `hits` es {rol: [identidades...]} acumuladas de TODAS las mallas que
    contienen el punto. Devuelve:

        ({rol: identidad_ganadora}, motivo_ambiguo, hubo_anidamiento)

    motivo_ambiguo == "" significa resolución limpia. Cualquier otro valor
    describe un Conflicto: el punto se excluye y se contabiliza.
    """
    resuelto: Dict[str, str] = {}
    anidamiento = False
    for rol in sorted(hits):
        ganador, motivo = _resolve_one_role(rol, hits[rol])
        if motivo == "subunidad_gana":
            anidamiento = True; motivo = ""
        if motivo:
            return {}, motivo, anidamiento
        if ganador is not None:
            resuelto[rol] = ganador          # Composición: roles distintos conviven
    return resuelto, "", anidamiento


def make_dominio(lito: Optional[str], alteracion: Optional[str],
                 estructura: Optional[str]) -> Optional[str]:
    """
    Clave de dominio a partir de los atributos resueltos.

      · Predominio: con estructura presente, el dominio es "<lito>::<estructura>"
        (la estructura predomina sobre todo lo demás).
      · Si no, la clave es el par (litologia, alteracion|None), codificado como
        "<lito>" o "<lito>~<alteracion>".
      · Una alteración SOLA no define dominio.
    """
    if estructura: return f"{lito or ''}::{estructura}"
    if lito and alteracion: return f"{lito}~{alteracion}"
    return lito or None

@dataclass
class Layer:
    name: str; kind: str; triangles: np.ndarray
    bbox_min: np.ndarray; bbox_max: np.ndarray
    ucs_lab: Optional[float] = None; folder: str = "Litología"
    # Etiquetado caserón×litología (T2): el caserón se asigna por dropdown en
    # el árbol de capas; lito_alias permite matchear la litología del Excel
    # cuando el nombre de la capa DXF no coincide literal. ucs_lo/hi/mid son la
    # banda de laboratorio autocompletada desde geomech_bands (el usuario puede
    # sobrescribir ucs_lab manualmente sin perder la banda).
    caseron: Optional[str] = None; lito_alias: Optional[str] = None
    ucs_lo: Optional[float] = None; ucs_hi: Optional[float] = None
    ucs_mid: Optional[float] = None
    # (P1-T1.2 / A.2) Vínculo al registro de vocabulario canónico. Una capa
    # puede aportar VARIOS atributos de roles distintos: Bht_Fk.dxf trae
    # litología y alteración compuestas en un solo nombre, y debe producir el
    # mismo dominio que dos mallas separadas que se traslapan.
    #   atributos = {"litologia": "Bht", "alteracion": "Fk"}
    # `nivel` se toma del atributo de litología; sin atributo asignado queda
    # None → cualquier traslape con esta capa es ambiguo, nunca un ganador
    # arbitrario.
    atributos: Dict[str, str] = field(default_factory=dict)
    nivel: Optional[str] = None          # "unidad" | "subunidad" | None

    @property
    def atributo_id(self) -> Optional[str]:
        """Compatibilidad: el atributo de rol litología, si lo hay."""
        return self.atributos.get("litologia")

@dataclass
class MWDPoint:
    largo: float; vel: float; pp: float; pa: float
    pd: float; pr: float; pf: float; se: float; t: float
    este: float = 0.0; norte: float = 0.0; cota: float = 0.0
    raw_vel: float = 0.0; raw_pp: float = 0.0; raw_pa: float = 0.0
    raw_pd: float = 0.0; raw_pr: float = 0.0; raw_pf: float = 0.0
    entrenable: bool = True; norm_excluded: bool = False
    dominio: Optional[str] = None; lito: Optional[str] = None; estructura: Optional[str] = None
    ucs_ml: Optional[float] = None
    # (P3-3.4) Antes "ucs_confiable": el nombre era engañoso — no mide
    # confianza, arrastra el último valor de ucs_ml estable en los tramos
    # donde DI supera el umbral (discontinuidad detectada). Renombrado a
    # "UCS matriz" porque es la UCS de la matriz rocosa SIN discontinuidades.
    ucs_matriz: Optional[float] = None
    ucs_ml_prelim: bool = False
    # Intervalo de predicción del RF (percentiles 10/90 sobre los árboles).
    ucs_ml_p10: Optional[float] = None; ucs_ml_p90: Optional[float] = None
    di: Optional[float] = None; grupo: Optional[str] = None
    lito_inferida: Optional[str] = None; estructura_inferida: Optional[str] = None
    grupo_confianza: Optional[float] = None
    # Verificación de consistencia banda-laboratorio vs intervalo ML (T3):
    # "compatible" / "incompatible" / "ambiguo" / None (no evaluable).
    band_check: Optional[str] = None
    # Seteo real del equipo para el punto (T9): presión de percusión y avance
    # registrados en el CSV/Excel de seteo, si están disponibles.
    seteo_pp: Optional[float] = None; seteo_pa: Optional[float] = None
    # (P1-T1.4 / A.5) Resolución de traslape por rol. `atributos` es el mapa
    # {rol: atributo_id} resuelto para el punto — atributos CANÓNICOS, no
    # nombres de capa, para que el dominio no dependa de cómo vino empaquetada
    # la información. `alteracion` se COMPONE con la litología (Bht+Fk ≠
    # Bht+otra alteración); una alteración sola no define dominio.
    # `ambiguo` marca el punto excluido por Conflicto, con el motivo en
    # `ambiguo_motivo`: contabilizado y reportado, nunca descartado en silencio.
    atributos: Dict[str, str] = field(default_factory=dict)
    alteracion: Optional[str] = None
    ambiguo: bool = False
    ambiguo_motivo: Optional[str] = None

    @property
    def atributo_id(self) -> Optional[str]:
        """Compatibilidad: el atributo de rol litología, si lo hay."""
        return self.atributos.get("litologia")

@dataclass
class Well:
    well_name: str; plan_id: str; hole_id: str
    points: List[MWDPoint] = field(default_factory=list)
    collar: Optional[Dict] = None; final_pt: Optional[Dict] = None
    origin: str = "matched"
    # Candidatos DQ×hole disponibles para este pozo (mismo hole_id, distintos
    # planes hermanos), cada uno con su error de coherencia de largo. Se usa
    # para poblar el dropdown de reasignación manual de pozos ambiguos.
    dq_candidates: List[Dict] = field(default_factory=list)
    # Caserón al que pertenece el pozo. Es la agrupación correcta para
    # LOCO-CV: una litología cruza varios caserones, un pozo no. Si queda
    # None, caseron_de_pozo() lo deriva del prefijo del plan_id.
    caseron: Optional[str] = None

# Estado global
layers: Dict[str, Layer] = {}
wells: Dict[str, Well] = {}
domains: Dict[str, Dict] = {}
domain_groups: List[Dict] = []
clean_filters: List[Dict] = []
# (P3-3.8) Corte de emboquillado VIGENTE. Antes vivía solo como el parámetro
# `cut_m` de apply_inicio_filter() y se perdía: recompute_filters() (llamada
# al borrar un filtro de limpieza) lo reseteaba EN SILENCIO a un default
# hardcodeado de 2.0 m, aunque el usuario hubiera fijado otro valor. Ahora se
# recuerda aquí, y recompute_filters() lo reaplica en vez de un literal.
inicio_cut_m: float = 2.0
excel_data: List[Dict] = []
# Bandas geomecánicas de laboratorio (T2): registros por caserón×litología.
#   by_pair    : {(caseron_norm, lito_norm): band}
#   by_lito    : {lito_norm: [band, ...]}          (misma litología, varios caserones)
#   by_caseron : {caseron_norm: [band, ...]}       (mismo caserón, varias litologías)
#   records    : lista completa de bandas parseadas
geomech_bands: Dict[str, Dict] = {"by_pair": {}, "by_lito": {}, "by_caseron": {}, "records": []}
# Resultados de la validación multipozo de posición de mallas (T4): lista de
# dicts por malla de estructura, poblada por run_validation_task en el hilo de
# fondo y renderizada por _mesh_validation_card en el Paso 5.
mesh_validation_results: List[Dict] = []
parse_warnings: List[str] = []
rf_model = None
rf_stats: Optional[Dict] = None
prelim_model = None
# (P3-3.7) Valores de Fernández et al. 2023 (doi:10.1016/j.ijmst.2023.02.004),
# predeterminados. Se exponen en la UI como editables, con botón de
# restauración a estos mismos valores.
DI_DEFAULTS = {"window": 14, "threshold": 1.5,
              "weights": {"pp": 0.35, "pr": 0.20, "pd": 0.25, "pf": 0.20}}
di_config = {"params": ["pp","pr","pd","pf"], "weights": dict(DI_DEFAULTS["weights"]),
            "window": DI_DEFAULTS["window"]}
di_threshold: float = DI_DEFAULTS["threshold"]


def di_config_is_default() -> bool:
    return (di_config["window"] == DI_DEFAULTS["window"]
            and di_threshold == DI_DEFAULTS["threshold"]
            and di_config["weights"] == DI_DEFAULTS["weights"])


def di_config_summary() -> str:
    """
    (P3-3.7) Línea de una sola línea con los parámetros DI vigentes, para
    anteponer a las exportaciones que dependen de ellos (predicciones,
    dominios, DI↔RQD, resumen del kit): cualquier cambio respecto a
    Fernández et al. 2023 altera todo aguas abajo (DI, UCS matriz, agrupación
    de dominios) y debe quedar declarado en lo que se exporta, no solo en la
    pantalla donde se cambió.
    """
    w = di_config["weights"]
    linea = (f"DI: ventana={di_config['window']} umbral={di_threshold:g} "
            f"pesos(PP={w.get('pp')},DP={w.get('pd')},FP={w.get('pf')},RP={w.get('pr')})")
    linea += (" [valores por defecto, Fernández et al. 2023]" if di_config_is_default()
              else " [MODIFICADO respecto a Fernández et al. 2023]")
    return linea
group_interval_m: float = 2.0
ucs_range = dict(ucs_min=UCS_CONFIG["default_min"], ucs_max=UCS_CONFIG["default_max"])
cal_factors = {k: 1.0 for k in ("vel","pp","pa","pd","pr","pf","se")}
global_center: Optional[Dict[str, float]] = None

wz_state = {
    'step1':{'dxf_loaded':False,'xml_loaded':False},
    'step2':{'calibrated':False,'cleaned':False},
    'step3':{'di_computed':False},
    'step4':{'model_trained':False},
    'step5':{'grouped':False,'predicted':False},
}

# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  P2 — SONDAJES: parser, desurvey y selección de pozos                   ║
# ║                                                                          ║
# ║  Incorpora los sondajes con testigo como fuente de verdad INDEPENDIENTE ║
# ║  del MWD, y resuelve qué pozos son relevantes para un conjunto de       ║
# ║  caserones dado (mallas DXF de litología cargadas en ese momento).      ║
# ╚══════════════════════════════════════════════════════════════════════════╝

@dataclass
class DrillHole:
    """
    Sondaje con testigo. `trace` es el resultado de desurvey_hole() —
    [(profundidad, Este, Norte, Cota), ...] — y es la fuente para ubicar
    cualquier tramo (litología/estructura/geomecánica/densidad) en UTM.

    `lithology`/`structures`/`geomec`/`density` son listas de dicts con
    'from'/'to' en profundidad (md), no en UTM: la posición se resuelve con
    trace_interp() cuando se necesita.
    """
    holeid: str
    x_utm: float; y_utm: float; z_utm: float
    length: Optional[float] = None
    # (depth, azimuth, dip) tal como se leyeron, sin ordenar todavía.
    surveys: List[Tuple[float, float, float]] = field(default_factory=list)
    trace: List[Tuple[float, float, float, float]] = field(default_factory=list)
    # True si desurvey_hole() tuvo que sintetizar una segunda estación por
    # tener solo una (T2.2) — declarado en `warnings`, nunca silencioso.
    trace_extended: bool = False
    lithology: List[Dict] = field(default_factory=list)
    structures: List[Dict] = field(default_factory=list)
    geomec: List[Dict] = field(default_factory=list)
    density: List[Dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # (T2.2) Banda espacial norte-sur, poblada por compute_spatial_bands().
    banda: Optional[str] = None
    # (T2.4) Resultado del último cruce traza↔malla.
    estado: Optional[str] = None          # "intersecta" | "cercano" | "lejano" | None
    dist_min_m: Optional[float] = None
    malla_cercana: Optional[str] = None
    metros_dentro: float = 0.0
    # (T2.5) Métricas por pozo.
    metros_por_unidad: Dict[str, float] = field(default_factory=dict)
    n_estructuras: int = 0
    rqd_mediana: Optional[float] = None
    rmr_mediana: Optional[float] = None
    # (T2.6) None = selección automática (deriva de `estado`); True/False =
    # anulación manual explícita, en cualquiera de los dos sentidos, que
    # sobrevive a un recálculo del cruce (refresh_drillhole_selection no la
    # toca).
    seleccion_manual: Optional[bool] = None

    def seleccionado(self) -> bool:
        if self.seleccion_manual is not None:
            return self.seleccion_manual
        return self.estado == "intersecta"

    def length_declarado(self) -> float:
        """
        Profundidad total a usar para completar el trazado más allá de la
        última estación conocida: la mayor entre `length` (header) y el
        'to' más profundo logueado en cualquiera de las cuatro tablas.
        """
        tos = [self.length or 0.0]
        for coll in (self.lithology, self.structures, self.geomec, self.density):
            tos.extend(r["to"] for r in coll if r.get("to") is not None)
        return max(tos) if tos else 0.0


drillholes: Dict[str, DrillHole] = {}
# (T2.2) Agregados por banda espacial: {"Sur"/"Centro"/"Norte": {...}}.
spatial_bands: Dict[str, Dict] = {}
# (T2.4) Umbral de distancia por defecto para el estado "cercano". El
# enunciado no fija un valor: se documenta aquí y queda editable en la UI.
DRILLHOLE_NEAR_DISTANCE_M = 25.0
# (T2.4) Resolución de muestreo de la traza para el cruce contra mallas.
DRILLHOLE_TRACE_STEP_M = 1.0
# (T2.3) Tolerancia para considerar dos tramos de litología "consecutivos".
DRILLHOLE_CONTACT_GAP_EPS_M = 0.05

# ─── T2.1 · LECTOR DE LOS SEIS CSV ────────────────────────────────────────────
# Separador ';', terminación CRLF, codificación latin-1, clave holeid, valor
# centinela -999. Mapeo TOLERANTE de columnas: distintas minas usan
# azimuth_utm o azimuth, agregan subunidad, etc. — el lector no falla por eso.

DRILLHOLE_SENTINEL = -999.0
_DH_HOLEID = ["holeid", "hole_id", "id_sondaje", "pozo", "id"]
_DH_FROM = ["from", "desde"]
_DH_TO = ["to", "hasta"]

# spec[kind][campo_canónico] = (candidatos_de_nombre, "text"|"num")
DRILLHOLE_COLS = {
    "header": {
        "holeid": (_DH_HOLEID, "text"),
        "x_utm": (["x_utm", "este", "x", "easting"], "num"),
        "y_utm": (["y_utm", "norte", "y", "northing"], "num"),
        "z_utm": (["z_utm", "cota", "z", "elevation", "elev"], "num"),
        "length": (["length", "largo", "profundidad_total", "eot", "total_depth"], "num"),
    },
    "survey": {
        "holeid": (_DH_HOLEID, "text"),
        "depth": (["depth", "profundidad", "md", "prof"], "num"),
        "azimuth": (["azimuth_utm", "azimuth", "azimut", "brujula"], "num"),
        "dip": (["dip", "inclinacion", "inclinación", "buzamiento"], "num"),
        "equipo": (["equipo_desviacion", "equipo", "tool", "herramienta"], "text"),
    },
    "lithology": {
        "holeid": (_DH_HOLEID, "text"),
        "from": (_DH_FROM, "num"), "to": (_DH_TO, "num"),
        "unidad": (["unidad", "litologia", "lito", "subunidad", "codigo"], "text"),
    },
    "structure": {
        "holeid": (_DH_HOLEID, "text"),
        "from": (_DH_FROM, "num"), "to": (_DH_TO, "num"),
        "structure": (["structure", "estructura", "tipo_estructura", "codigo"], "text"),
    },
    "geomec": {
        "holeid": (_DH_HOLEID, "text"),
        "from": (_DH_FROM, "num"), "to": (_DH_TO, "num"),
        "rqd": (["rqd"], "num"), "rmr": (["rmr"], "num"),
    },
    "density": {
        "holeid": (_DH_HOLEID, "text"),
        "from": (_DH_FROM, "num"), "to": (_DH_TO, "num"),
        "density": (["density", "densidad", "dens", "gamma"], "num"),
    },
}
DRILLHOLE_KINDS = tuple(DRILLHOLE_COLS)


def guess_drillhole_kind(fname: str) -> Optional[str]:
    """Adivina cuál de los 6 CSV es `fname` por palabras clave en el nombre."""
    n = _norm_txt(fname)
    if "header" in n or "collar" in n: return "header"
    if "survey" in n or "desviacion" in n: return "survey"
    if "lithology" in n or "litologia" in n: return "lithology"
    if "structure" in n or "estructura" in n: return "structure"
    if "geomec" in n: return "geomec"
    if "density" in n or "densidad" in n: return "density"
    return None


def _find_drillhole_col(cols_norm: Dict[str, str], candidates: List[str]) -> Optional[str]:
    """Coincidencia exacta (normalizada) primero; substring como reserva."""
    for c in candidates:
        cn = _norm_txt(c)
        if cn in cols_norm: return cols_norm[cn]
    for c in candidates:
        cn = _norm_txt(c)
        if not cn: continue
        for norm, orig in cols_norm.items():
            if cn in norm: return orig
    return None


def _read_drillhole_table(raw_bytes: bytes, kind: str) -> pd.DataFrame:
    """
    Lee uno de los seis CSV de sondaje. Columnas canónicas de salida según
    DRILLHOLE_COLS[kind]; el centinela -999 se convierte en nulo en todos los
    campos numéricos. No falla por columnas EXTRA (p.ej. 'subunidad'): esas
    simplemente se ignoran.
    """
    try:
        df = pd.read_csv(_io.BytesIO(raw_bytes), sep=";", encoding="latin-1")
    except Exception as e:
        raise RuntimeError(f"CSV de sondaje ({kind}) ilegible: {e}")
    df.columns = [str(c).strip() for c in df.columns]
    cols_norm = {_norm_txt(c): c for c in df.columns}
    spec = DRILLHOLE_COLS[kind]
    out = pd.DataFrame(index=df.index)
    faltan = []
    for canon, (cands, dtype) in spec.items():
        col = _find_drillhole_col(cols_norm, cands)
        if col is None:
            if canon in ("holeid", "from", "to"):
                faltan.append(canon)
            out[canon] = None
            continue
        if dtype == "text":
            # Ojo: astype(str) sobre NaN da el string "nan", no un nulo. Se
            # evalúa pd.notna ANTES de convertir para no dejar pasar ese
            # literal como si fuera un código real.
            out[canon] = df[col].apply(lambda v: str(v).strip() if pd.notna(v) else None)
        else:
            s = pd.to_numeric(df[col], errors="coerce")
            out[canon] = s.mask(s == DRILLHOLE_SENTINEL)
    if faltan:
        raise RuntimeError(f"CSV de sondaje ({kind}): faltan columnas obligatorias "
                           f"{faltan}. Columnas presentes: {list(df.columns)}.")
    return out


def load_drillhole_csvs(files: Dict[str, bytes]) -> Dict:
    """
    Construye `drillholes` a partir de hasta seis tablas ya identificadas por
    `kind` ({"header","survey","lithology","structure","geomec","density"}).

    header y survey son OBLIGATORIAS (sin ellas no hay collar ni desviación).
    Las otras cuatro son opcionales; su ausencia se declara en el resultado,
    nunca se sustituye por datos inventados.

    (T1.1) Cada collar pasa por el guardián de sitio: uno fuera de la
    envolvente del sitio activo no se carga sin confirmación explícita.

    (T2.1) Los códigos de litología y de estructura se resuelven contra el
    registro de vocabulario de P1 (resolve_or_note): lo no reconocido cae en
    la bandeja de pendientes, visible y contabilizada, nunca se inventa.

    Devuelve {"holes": n, "warnings": [...], "faltantes": [...]}.
    """
    if "header" not in files or "survey" not in files:
        raise RuntimeError("Se requieren al menos las tablas 'header' y 'survey' "
                           "para construir los sondajes.")
    tables = {k: _read_drillhole_table(raw, k) for k, raw in files.items()}
    warnings_local: List[str] = []
    faltantes = [k for k in ("lithology", "structure", "geomec", "density") if k not in files]
    if faltantes:
        warnings_local.append(f"Tablas ausentes (declaradas, no sustituidas): "
                              f"{', '.join(faltantes)}.")

    drillholes.clear()
    hdr = tables["header"]
    for _, row in hdr.iterrows():
        hid = row["holeid"]
        if not hid or pd.isna(row["x_utm"]) or pd.isna(row["y_utm"]) or pd.isna(row["z_utm"]):
            warnings_local.append(f'"{hid}": collar con coordenadas incompletas, omitido.')
            continue
        verdict = site_guard(este=float(row["x_utm"]), norte=float(row["y_utm"]),
                             etiqueta=hid, tipo="collar de sondaje", token=f"sondaje:{hid}")
        if not verdict["ok"]:
            warnings_local.append(verdict["mensaje"]); log_warn(verdict["mensaje"])
            continue
        drillholes[hid] = DrillHole(
            holeid=hid, x_utm=float(row["x_utm"]), y_utm=float(row["y_utm"]),
            z_utm=float(row["z_utm"]),
            length=float(row["length"]) if pd.notna(row.get("length")) else None,
        )

    surv = tables["survey"]
    surv = surv[surv["holeid"].isin(drillholes)].sort_values(["holeid", "depth"])
    for hid, g in surv.groupby("holeid", sort=False):
        dh = drillholes[hid]
        for _, r in g.iterrows():
            if pd.isna(r["depth"]) or pd.isna(r["azimuth"]) or pd.isna(r["dip"]):
                dh.warnings.append("Estación de desviación con dato faltante, omitida.")
                continue
            dh.surveys.append((float(r["depth"]), float(r["azimuth"]), float(r["dip"])))
    for hid, dh in drillholes.items():
        if not dh.surveys:
            msg = f'Sondaje "{hid}": sin estaciones de desviación válidas.'
            dh.warnings.append(msg); warnings_local.append(msg)

    if "lithology" in tables:
        for _, r in tables["lithology"].iterrows():
            dh = drillholes.get(r["holeid"])
            if dh is None or pd.isna(r["from"]) or pd.isna(r["to"]) or not r.get("unidad"):
                continue
            unidad_raw = r["unidad"]
            aid = resolve_or_note(unidad_raw, "sondaje_unidad").get("litologia")
            dh.lithology.append({"from": float(r["from"]), "to": float(r["to"]),
                                 "unidad": unidad_raw, "atributo_id": aid})

    if "structure" in tables:
        for _, r in tables["structure"].iterrows():
            dh = drillholes.get(r["holeid"])
            if dh is None or pd.isna(r["from"]) or pd.isna(r["to"]) or not r.get("structure"):
                continue
            raw = r["structure"]
            aid = resolve_or_note(raw, "sondaje_estructura").get("estructura")
            dh.structures.append({"from": float(r["from"]), "to": float(r["to"]),
                                  "codigo": raw, "atributo_id": aid, "tipo": "logueada"})

    if "geomec" in tables:
        for _, r in tables["geomec"].iterrows():
            dh = drillholes.get(r["holeid"])
            if dh is None or pd.isna(r["from"]) or pd.isna(r["to"]):
                continue
            dh.geomec.append({
                "from": float(r["from"]), "to": float(r["to"]),
                "rqd": float(r["rqd"]) if pd.notna(r.get("rqd")) else None,
                "rmr": float(r["rmr"]) if pd.notna(r.get("rmr")) else None,
            })

    if "density" in tables:
        for _, r in tables["density"].iterrows():
            dh = drillholes.get(r["holeid"])
            if dh is None or pd.isna(r["from"]) or pd.isna(r["to"]):
                continue
            dh.density.append({"from": float(r["from"]), "to": float(r["to"]),
                               "densidad": float(r["density"]) if pd.notna(r.get("density")) else None})

    for dh in drillholes.values():
        dh.lithology.sort(key=lambda x: x["from"])
        dh.structures.sort(key=lambda x: x["from"])
        dh.geomec.sort(key=lambda x: x["from"])
        dh.density.sort(key=lambda x: x["from"])

    return {"holes": len(drillholes), "warnings": warnings_local, "faltantes": faltantes}


# ─── T2.2 · DESURVEY POR CURVATURA MÍNIMA ─────────────────────────────────────

def desurvey_min_curvature(collar_ENZ, surveys):
    """
    surveys: lista ordenada de (depth, azimuth, dip). dip negativo hacia
    abajo. Devuelve lista de (depth, Este, Norte, Cota). Curvatura mínima,
    validada contra los 11 pozos MPC.
    """
    E, N, Z = collar_ENZ
    pts = [(0.0, E, N, Z)]
    for i in range(len(surveys) - 1):
        d1, a1, i1 = surveys[i]
        d2, a2, i2 = surveys[i + 1]
        md = d2 - d1
        if md <= 0:
            continue
        I1, A1 = math.radians(90 + i1), math.radians(a1)
        I2, A2 = math.radians(90 + i2), math.radians(a2)
        cb = math.cos(I2 - I1) - math.sin(I1) * math.sin(I2) * (1 - math.cos(A2 - A1))
        cb = max(-1.0, min(1.0, cb))
        b = math.acos(cb)
        rf = 1.0 if b < 1e-9 else 2 / b * math.tan(b / 2)   # factor de razón
        dN = md / 2 * (math.sin(I1)*math.cos(A1) + math.sin(I2)*math.cos(A2)) * rf
        dE = md / 2 * (math.sin(I1)*math.sin(A1) + math.sin(I2)*math.sin(A2)) * rf
        dZ = md / 2 * (math.cos(I1) + math.cos(I2)) * rf
        E += dE; N += dN; Z -= dZ
        pts.append((d2, E, N, Z))
    return pts


def desurvey_hole(dh: DrillHole) -> List[Tuple[float, float, float, float]]:
    """
    Desurveya un DrillHole. Criterio de aceptación: los 11 pozos MPC deben
    desurveyarse SIN EXCEPCIÓN.

    Casos declarados (nunca silenciosos):
      · sin estaciones          → traza = solo el collar; advertencia.
      · una sola estación       → se asume trazado recto con ese azimut/
        inclinación hasta la profundidad total declarada (header o el 'to'
        más profundo logueado), para poder ubicar tramos más allá de esa
        única lectura. `trace_extended=True` y advertencia explícita.
    """
    surveys = sorted(dh.surveys, key=lambda s: s[0])
    dh.trace_extended = False
    if not surveys:
        msg = f'Sondaje "{dh.holeid}": sin estaciones de desviación; traza = collar.'
        if msg not in dh.warnings: dh.warnings.append(msg)
        log_warn(msg)
        dh.trace = [(0.0, dh.x_utm, dh.y_utm, dh.z_utm)]
        return dh.trace
    if len(surveys) == 1:
        d0, a0, i0 = surveys[0]
        total = dh.length_declarado()
        if total > d0 + 1e-9:
            msg = (f'Sondaje "{dh.holeid}": una sola estación de desviación (en '
                   f'{d0:.1f} m). Se asume trazado recto con azimut {a0:.2f}° / '
                   f'inclinación {i0:.2f}° hasta la profundidad declarada '
                   f'({total:.1f} m).')
            if msg not in dh.warnings: dh.warnings.append(msg)
            log_warn(msg)
            surveys = [(d0, a0, i0), (total, a0, i0)]
            dh.trace_extended = True
    dh.trace = desurvey_min_curvature((dh.x_utm, dh.y_utm, dh.z_utm), surveys)
    return dh.trace


def desurvey_all_holes():
    for dh in drillholes.values():
        desurvey_hole(dh)


def trace_interp(trace, depth: float) -> Tuple[float, float, float]:
    """
    Interpolación lineal (Este, Norte, Cota) a una profundidad arbitraria
    entre estaciones desurveyadas. Fuera de rango: se sostiene el valor del
    extremo más cercano (no se extrapola más allá de lo declarado).
    """
    if not trace: return (float("nan"), float("nan"), float("nan"))
    if depth <= trace[0][0]: return trace[0][1:]
    if depth >= trace[-1][0]: return trace[-1][1:]
    for i in range(len(trace) - 1):
        d1, d2 = trace[i][0], trace[i + 1][0]
        if d1 <= depth <= d2:
            t = (depth - d1) / (d2 - d1) if d2 > d1 else 0.0
            return tuple(trace[i][j+1] + t*(trace[i+1][j+1]-trace[i][j+1]) for j in range(3))
    return trace[-1][1:]


def sample_trace(trace, step: float = DRILLHOLE_TRACE_STEP_M):
    """Muestrea la traza a resolución `step` [m], para el cruce con mallas."""
    if not trace: return []
    d0, d1 = trace[0][0], trace[-1][0]
    if d1 <= d0: return [trace[0]]
    n_steps = max(int((d1 - d0) / step), 1)
    depths = [d0 + k*step for k in range(n_steps)] + [d1]
    return [(d, *trace_interp(trace, d)) for d in depths]


# ─── T2.2 · REPARTO ESPACIAL EN TERCIOS NORTE-SUR ─────────────────────────────

def compute_spatial_bands() -> Dict[str, Dict]:
    """
    Divide el eje northing en tres tercios IGUALES EN RANGO (no en cantidad
    de pozos) sobre la nube COMPLETA de puntos desurveyados de todos los
    sondajes — no solo los collares, para que un pozo inclinado no quede mal
    encasillado por un límite calculado únicamente con bocas de pozo.

    Cada pozo se etiqueta por la northing de SU PROPIO collar contra esos dos
    límites. Devuelve {"Sur"/"Centro"/"Norte": {n_pozos, m_litologia,
    n_estructuras, cota_min, cota_max, holeids}}.
    """
    all_n = [p[2] for dh in drillholes.values() for p in dh.trace]
    spatial_bands.clear()
    labels = ("Sur", "Centro", "Norte")
    for lbl in labels:
        spatial_bands[lbl] = {"n_pozos": 0, "m_litologia": 0.0, "n_estructuras": 0,
                              "cota_min": None, "cota_max": None, "holeids": []}
    if not all_n:
        return spatial_bands
    n_lo, n_hi = min(all_n), max(all_n)
    span = (n_hi - n_lo) or EPS
    b1 = n_lo + span / 3.0
    b2 = n_lo + 2 * span / 3.0
    for hid, dh in drillholes.items():
        lbl = "Sur" if dh.y_utm < b1 else ("Centro" if dh.y_utm < b2 else "Norte")
        dh.banda = lbl
        b = spatial_bands[lbl]
        b["n_pozos"] += 1; b["holeids"].append(hid)
        b["m_litologia"] += sum(r["to"] - r["from"] for r in dh.lithology)
        b["n_estructuras"] += sum(1 for r in dh.structures if r.get("tipo") == "logueada")
        zs = [p[3] for p in dh.trace] or [dh.z_utm]
        zmn, zmx = min(zs), max(zs)
        b["cota_min"] = zmn if b["cota_min"] is None else min(b["cota_min"], zmn)
        b["cota_max"] = zmx if b["cota_max"] is None else max(b["cota_max"], zmx)
    for b in spatial_bands.values():
        b["m_litologia"] = round(b["m_litologia"], 1)
    return spatial_bands


# ─── T2.3 · CONTACTOS DERIVADOS ───────────────────────────────────────────────

def derive_contacts(dh: DrillHole) -> List[Dict]:
    """
    Deriva contactos de los límites entre tramos CONSECUTIVOS de la tabla de
    litología, marcados con tipo='contacto_derivado' (nunca 'logueada', para
    no confundirlos con estructuras registradas por el geólogo). Serán las
    etiquetas del discriminador fractura-contacto en una sesión posterior;
    aquí solo se generan y se almacenan.

    Solo se deriva un contacto donde los tramos son contiguos (tolerancia
    DRILLHOLE_CONTACT_GAP_EPS_M) y la unidad cambia. Un salto real entre
    tramos no permite ubicar el contacto con certeza y se deja sin derivar.
    """
    contactos = []
    lito = sorted(dh.lithology, key=lambda x: x["from"])
    for i in range(len(lito) - 1):
        a, b = lito[i], lito[i + 1]
        if abs(b["from"] - a["to"]) > DRILLHOLE_CONTACT_GAP_EPS_M:
            continue
        if _norm_txt(a["unidad"]) == _norm_txt(b["unidad"]):
            continue
        depth = (a["to"] + b["from"]) / 2.0
        contactos.append({
            "from": depth, "to": depth,
            "codigo": f'{a["unidad"]}→{b["unidad"]}', "atributo_id": "Cto",
            "tipo": "contacto_derivado",
            "unidad_antes": a["unidad"], "unidad_despues": b["unidad"],
        })
    return contactos


def refresh_drillhole_contacts():
    for dh in drillholes.values():
        dh.structures = [s for s in dh.structures if s.get("tipo") != "contacto_derivado"]
        dh.structures.extend(derive_contacts(dh))
        dh.structures.sort(key=lambda x: x["from"])


# ─── T2.4 · INTERSECCIÓN TRAZA↔MALLA EN TRES ESTADOS ──────────────────────────
# Reutiliza points_in_mesh (rayo vertical + grid XY) tal cual, contra las
# mallas ya cargadas cuando se leen los sondajes.

def _mesh_vertices(layer) -> np.ndarray:
    if not hasattr(layer, "_verts_cache"):
        layer._verts_cache = layer.triangles.reshape(-1, 3) if layer.triangles.size else np.zeros((0, 3))
    return layer._verts_cache


def _bbox_dist(points: np.ndarray, layer) -> np.ndarray:
    """Distancia (0 si está dentro del bbox) de cada punto al bbox de la capa."""
    lo, hi = layer.bbox_min, layer.bbox_max
    d = np.maximum(np.maximum(lo - points, points - hi), 0.0)
    return np.linalg.norm(d, axis=1)


def _min_dist_to_layer(points: np.ndarray, layer, vert_chunk: int = 4000) -> np.ndarray:
    """
    Distancia APROXIMADA de cada punto al vértice más cercano de la malla
    (no a la superficie exacta: puede sobrestimar frente a una cara plana,
    lejos de cualquier vértice). Suficiente para el flag 'cercano' de la UI,
    documentado como aproximación. El bbox filtra primero mallas evidentemente
    lejanas, para no pagar el costo fino en ellas.
    """
    out = _bbox_dist(points, layer)
    verts = _mesh_vertices(layer)
    cand = np.where(out < DRILLHOLE_NEAR_DISTANCE_M * 3)[0]
    if cand.size == 0 or verts.size == 0:
        return out
    pts = points[cand]
    best = np.full(len(pts), np.inf)
    for vstart in range(0, len(verts), vert_chunk):
        vv = verts[vstart:vstart + vert_chunk]
        d = np.sqrt(((pts[:, None, :] - vv[None, :, :]) ** 2).sum(-1)).min(axis=1)
        best = np.minimum(best, d)
    out[cand] = np.minimum(out[cand], best)
    return out


def _sum_inside_length(samples, inside_mask) -> float:
    """Metros de traza dentro de alguna malla, integrados a la resolución de
    muestreo (T2.4/T2.5); el error queda acotado por DRILLHOLE_TRACE_STEP_M."""
    total = 0.0
    for i in range(len(samples) - 1):
        if inside_mask[i]:
            total += samples[i + 1][0] - samples[i][0]
    return round(total, 2)


def compute_drillhole_mesh_intersections(kinds=("litologia",), near_m: Optional[float] = None):
    """
    (T2.4) Clasifica cada sondaje en tres estados contra las mallas cargadas
    de los `kinds` dados (por defecto solo litología: son las que representan
    caserones/dominios).

        Intersecta  algún punto de la traza cae dentro de alguna malla → seleccionado por defecto
        Cercano     no intersecta, pasa a menos de `near_m`             → NO seleccionado por defecto
        Lejano      fuera de ese rango                                  → NO seleccionado por defecto

    Sin mallas cargadas de esos `kinds`, el estado queda None — declarado,
    nunca "lejano" por default silencioso.
    """
    near_m = DRILLHOLE_NEAR_DISTANCE_M if near_m is None else near_m
    relevant = [lay for lay in layers.values() if lay.kind in kinds]
    if not relevant:
        for dh in drillholes.values():
            dh.estado = None; dh.dist_min_m = None; dh.malla_cercana = None
            dh.metros_dentro = 0.0
        return

    for dh in drillholes.values():
        if not dh.trace:
            desurvey_hole(dh)
        samples = sample_trace(dh.trace)
        if not samples:
            dh.estado = None; dh.dist_min_m = None; dh.malla_cercana = None
            dh.metros_dentro = 0.0
            continue
        coords = np.array([(s[1], s[2], s[3]) for s in samples], dtype=np.float64)
        valid = np.all(np.isfinite(coords), axis=1)

        inside_any = np.zeros(len(samples), dtype=bool)
        for lay in relevant:
            try:
                mask = np.zeros(len(samples), dtype=bool)
                if valid.any():
                    mask[valid] = points_in_mesh(coords[valid], lay)
                inside_any |= mask
            except Exception as e:
                log_warn(f'Intersección traza↔malla "{lay.name}" en "{dh.holeid}": {e}')

        dh.metros_dentro = _sum_inside_length(samples, inside_any)
        n_in = int(inside_any.sum())

        if n_in > 0:
            dh.estado = "intersecta"; dh.dist_min_m = 0.0; dh.malla_cercana = None
            continue

        nearest_layer, nearest_dist = None, float("inf")
        if valid.any():
            for lay in relevant:
                try:
                    d = _min_dist_to_layer(coords[valid], lay)
                    if d.size and float(d.min()) < nearest_dist:
                        nearest_dist = float(d.min()); nearest_layer = lay.name
                except Exception as e:
                    log_warn(f'Distancia traza↔malla "{lay.name}" en "{dh.holeid}": {e}')

        if nearest_layer is None:
            dh.estado = "lejano"; dh.dist_min_m = None; dh.malla_cercana = None
        else:
            dh.estado = "cercano" if nearest_dist < near_m else "lejano"
            dh.dist_min_m = round(nearest_dist, 1); dh.malla_cercana = nearest_layer


# ─── T2.5 · MÉTRICAS POR POZO ─────────────────────────────────────────────────

def compute_drillhole_metrics_basic():
    """Metros por unidad y nº de estructuras: no dependen de mallas cargadas,
    solo de las propias tablas del sondaje. Se calculan siempre."""
    for dh in drillholes.values():
        mpu: Dict[str, float] = {}
        for r in dh.lithology:
            mpu[r["unidad"]] = mpu.get(r["unidad"], 0.0) + (r["to"] - r["from"])
        dh.metros_por_unidad = {k: round(v, 2) for k, v in mpu.items()}
        dh.n_estructuras = sum(1 for r in dh.structures if r.get("tipo") == "logueada")


def compute_drillhole_rqd_rmr_medians(kinds=("litologia",)):
    """
    RQD/RMR medianos SOLO del tramo que efectivamente intersecta una malla
    relevante. Si el pozo no intersecta nada (o no hay geomecánica logueada),
    quedan en None: no hay 'tramo intersectado' del que promediar, y forzar
    el global del pozo sería un default silencioso.
    """
    relevant = [lay for lay in layers.values() if lay.kind in kinds]
    for dh in drillholes.values():
        if dh.estado != "intersecta" or not dh.geomec or not relevant:
            dh.rqd_mediana = None; dh.rmr_mediana = None
            continue
        rqds, rmrs = [], []
        for r in dh.geomec:
            mid = (r["from"] + r["to"]) / 2.0
            e, n, z = trace_interp(dh.trace, mid)
            if not np.isfinite(e): continue
            pt = np.array([[e, n, z]], dtype=np.float64)
            dentro = any(points_in_mesh(pt, lay)[0] for lay in relevant)
            if not dentro: continue
            if r.get("rqd") is not None: rqds.append(r["rqd"])
            if r.get("rmr") is not None: rmrs.append(r["rmr"])
        dh.rqd_mediana = round(float(np.median(rqds)), 1) if rqds else None
        dh.rmr_mediana = round(float(np.median(rmrs)), 1) if rmrs else None


def refresh_drillhole_selection(kinds=("litologia",), near_m: Optional[float] = None):
    """Orquesta T2.2-T2.5 completo: desurvey → bandas → contactos → cruce →
    métricas. Es lo que dispara el botón 'Recalcular selección' de la UI, y
    lo que corre automáticamente al terminar de cargar los CSV."""
    desurvey_all_holes()
    compute_spatial_bands()
    refresh_drillhole_contacts()
    compute_drillhole_metrics_basic()
    compute_drillhole_mesh_intersections(kinds=kinds, near_m=near_m)
    compute_drillhole_rqd_rmr_medians(kinds=kinds)


# ─── SISTEMA DE TAREAS EN SEGUNDO PLANO (progreso + log para operaciones largas) ─
# Permite ejecutar operaciones potencialmente largas (cruce geométrico + ML)
# en un hilo aparte, con progreso y log consultables desde el navegador
# mediante polling (dcc.Interval), en vez de bloquear el callback de Dash
# (que dejaría la UI congelada sin ningún feedback, como reportó el usuario).
task_state = {
    "running": False,      # True mientras el hilo de fondo trabaja
    "progress": 0,         # 0-100
    "stage": "",            # descripción de la etapa actual
    "log": [],              # lista de líneas de log con timestamp
    "error": None,           # mensaje de error si algo falló
    "result": None,          # resultado final (stats del modelo) si terminó OK
    "done": False,           # True cuando la tarea terminó (con o sin error)
}
task_lock = threading.Lock()

# Segunda tarea de fondo (T4, validación multipozo de mallas). Estado separado
# de task_state a propósito: la validación puede correr sin pisar el flujo del
# ML (cada tarea tiene su propio dcc.Interval de polling); ambas comparten
# task_lock, que solo protege lecturas/escrituras breves de los dicts.
val_task_state = {
    "running": False, "progress": 0, "stage": "", "log": [],
    "error": None, "result": None, "done": False,
}

def task_log(msg, stage=None, progress=None):
    with task_lock:
        ts = time.strftime("%H:%M:%S")
        task_state["log"].append(f"[{ts}] {msg}")
        if len(task_state["log"]) > 300:
            task_state["log"].pop(0)
        if stage is not None: task_state["stage"] = stage
        if progress is not None: task_state["progress"] = progress
    print(f"[TASK] {msg}")

def run_ml_task(ucs_min, ucs_max):
    """
    Ejecuta el pipeline completo (cruce geométrico + índice de dominios +
    entrenamiento RF) en un hilo de fondo, reportando avance a task_state.
    """
    with task_lock:
        task_state.update(running=True, progress=0, stage="Iniciando…",
                           log=[], error=None, result=None, done=False)
    try:
        task_log("Iniciando cruce geométrico DXF ↔ MWD...", "Cruce geométrico (Möller-Trumbore)", 5)
        t0 = time.time()
        classify_all_wells_cached()
        task_log(f"Cruce geométrico completado en {time.time()-t0:.1f}s.", progress=45)

        task_log("Construyendo índice de dominios...", "Índice de dominios", 50)
        build_domain_index()
        all_pts = list(all_points())
        n_ucs = sum(1 for p in all_pts if p.dominio and domains.get(p.dominio,{}).get("ucs_lab"))
        task_log(f"Índice construido: {n_ucs}/{len(all_pts)} puntos con UCS asignado.", progress=55)

        task_log("Entrenando Random Forest...", "Entrenamiento Random Forest", 60)
        t0 = time.time()
        stats = train_rf(ucs_min, ucs_max)
        task_log(f"Entrenamiento completado en {time.time()-t0:.1f}s.", progress=85)

        if "error" in stats:
            task_log(f"⚠ {stats['error']}", progress=100)
            with task_lock:
                task_state.update(running=False, done=True, error=stats["error"])
            return
        if stats.get("cv_warning"):
            task_log(f"⚠ {stats['cv_warning']}")

        task_log("Generando predicciones UCS para todos los pozos...", "Prediciendo UCS", 90)
        predict_all_wells()
        wz_state['step4']['model_trained'] = True
        task_log(f"✅ Listo. R²={stats['r2_train']} RMSE={stats['rmse_train']} MPa N={stats['n_train']}", "Completado", 100)
        with task_lock:
            task_state.update(running=False, done=True, result=stats)
    except Exception as e:
        tb = traceback.format_exc()
        task_log(f"❌ ERROR: {e}\n{tb}", "Error", 100)
        with task_lock:
            task_state.update(running=False, done=True, error=str(e))


def log_warn(msg):
    parse_warnings.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
    if len(parse_warnings) > 500: parse_warnings.pop(0)
    print(f"⚠  {msg}")

def set_center(norte, este, cota):
    global global_center
    if global_center is None:
        global_center = {'norte':float(norte),'este':float(este),'cota':float(cota)}
        log_warn(f'globalCenter fijado: N={norte:.1f} E={este:.1f} Z={cota:.1f}')

def all_points():
    for w in wells.values():
        yield from w.points

# ─── COHERENCIA MW↔DQ (matching robusto con multi-DQ hermanos) ─────────────────
# Tolerancia de coherencia de largo: |largo_max_MWD − dist(collar,final)| / largo
# Validado con pozo real H5: 0.09 m sobre 36.07 m (0.3%). Un DQ del plan
# equivocado (abanico hermano desplazado) normalmente rompe esta coherencia.
COHERENCE_TOL = 0.05

def _dist3d(a, b):
    """Distancia euclidiana 3D entre dos puntos {norte,este,cota}."""
    return float(np.sqrt(
        (a["este"]  - b["este"]) **2 +
        (a["norte"] - b["norte"])**2 +
        (a["cota"]  - b["cota"]) **2))

def _coherence_err(largo_max, collar, final_pt):
    """
    Error relativo entre el largo máximo del MWD y la distancia euclidiana
    collar→final del DQ candidato. Un match correcto lo cumple (~0.3%); un DQ
    del plan hermano equivocado suele violarlo (collar desplazado).
    """
    if largo_max is None or largo_max <= 0:
        return float("inf")
    return abs(largo_max - _dist3d(collar, final_pt)) / largo_max

def _plan_short(pid):
    """Etiqueta corta del plan_id (ej. 'MGN_3025_PR01_TH_P40' → 'P40')."""
    m = re.findall(r"P\d+", pid or "")
    return m[-1] if m else (pid or "?")

def _plan_prefix_sim(pid_a, pid_b):
    """Largo del prefijo común entre dos plan_id (similitud para ordenar)."""
    s = 0
    for c1, c2 in zip(pid_a or "", pid_b or ""):
        if c1 == c2: s += 1
        else: break
    return s

def match_and_place_wells(dq_results, mw_by_hole):
    """
    Matching robusto MW↔DQ con multi-DQ hermanos + colocación espacial.

    Para cada pozo MWD elige el DQ×hole cuyo collar/final CUMPLE la coherencia
    de largo (|largo_max − dist(collar,final)|/largo_max < COHERENCE_TOL),
    probando candidatos en orden: match exacto de plan_id primero, luego DQ
    hermanos ordenados por similitud de prefijo de plan_id. Si ningún candidato
    cumple, el pozo queda origin="ambiguous" en posición ficticia (para
    reasignar a mano). Puebla el dict global `wells` e interpola las coordenadas
    de cada punto por su parámetro t (largo/largo_max). Devuelve un dict con los
    contadores {matched, fallback, ambiguous, no_dq}.

    Aislada de on_xml para poder testear el matching sin la capa Dash.
    """
    # Índice por hole_id de todos los DQ (fallback por hole)
    all_holes = {}
    for pid, dq in dq_results.items():
        for hid, tiro in dq["tiros"].items():
            all_holes.setdefault(hid, []).append((pid, tiro))

    counts = {"matched": 0, "fallback": 0, "ambiguous": 0, "no_dq": 0}
    for key, mw_list in mw_by_hole.items():
        best = max(mw_list, key=lambda m: m["largo_max"])
        pid = best["plan_id"]; hid = best["hole_id"]; largo_max = best["largo_max"]

        # ── Lista ORDENADA de candidatos DQ para este hole_id ──
        # 1º el match exacto de plan_id (si existe), luego los DQ hermanos
        # ordenados por similitud de prefijo de plan_id (descendente). Se
        # deduplica por plan_id (cada plan aporta a lo más un tiro por hole).
        candidates = []  # [(pid_dq, tiro)]
        seen_pids = set()
        if pid in dq_results and hid in dq_results[pid].get("tiros", {}):
            candidates.append((pid, dq_results[pid]["tiros"][hid]))
            seen_pids.add(pid)
        if hid in all_holes:
            for pid_dq, tiro in sorted(all_holes[hid],
                                       key=lambda x: -_plan_prefix_sim(pid, x[0])):
                if pid_dq in seen_pids: continue
                candidates.append((pid_dq, tiro))
                seen_pids.add(pid_dq)

        # Metadatos de todos los candidatos (para el dropdown de reasignación)
        cand_info = [{
            "plan_id": pid_dq, "hole_id": hid or "",
            "collar": tiro["collar"], "final_pt": tiro["final_pt"],
            "err_pct": round(_coherence_err(largo_max, tiro["collar"], tiro["final_pt"]) * 100, 2),
        } for pid_dq, tiro in candidates]

        # ── Elegir el primer candidato que cumpla la coherencia de largo ──
        collar = final_pt = None; origin = "no_dq"
        chosen_pid = None; discarded = []
        for pid_dq, tiro in candidates:
            err = _coherence_err(largo_max, tiro["collar"], tiro["final_pt"])
            if err < COHERENCE_TOL:
                collar, final_pt = tiro["collar"], tiro["final_pt"]
                chosen_pid = pid_dq
                break
            discarded.append((pid_dq, err))

        if chosen_pid is not None:
            if chosen_pid == pid:
                origin = "matched"; counts["matched"] += 1
            else:
                origin = "fallback_hole"; counts["fallback"] += 1
                log_warn(f'MW "{key}" plan="{pid}" hole={hid}: usado DQ hermano '
                         f'"{chosen_pid}" (coherencia OK).')
        elif candidates:
            # Había candidatos por hole_id pero NINGUNO cumple coherencia:
            # pozo ambiguo → posición ficticia + registro de descartados.
            origin = "ambiguous"; counts["ambiguous"] += 1
            det = ", ".join(f'{_plan_short(p)} (err {e*100:.1f}%)' for p, e in discarded)
            log_warn(f'MW "{key}" plan="{pid}" hole={hid}: AMBIGUO, ningún DQ '
                     f'cumple coherencia <{COHERENCE_TOL*100:.0f}%. Descartados: {det}. '
                     f'Posición ficticia; reasignar manualmente en el árbol de capas.')
        else:
            counts["no_dq"] += 1
            log_warn(f'MW "{key}": sin DQ. Posición ficticia.')

        pts = best["puntos"]
        if not pts:
            log_warn(f'MW "{key}": 0 puntos, omitido.'); continue
        # (P1-T1.1) Guardián por coordenadas sobre el collar real. Solo aplica a
        # pozos con posición verdadera: los de posición ficticia (sin DQ) heredan
        # el centro global y su distancia no informa nada sobre su procedencia.
        if collar:
            verdict = site_guard(este=collar["este"], norte=collar["norte"],
                                 etiqueta=key, tipo="collar de pozo", token=f"pozo:{key}")
            if not verdict["ok"]:
                counts["fuera_sitio"] = counts.get("fuera_sitio", 0) + 1
                log_warn(verdict["mensaje"] + " Pozo NO cargado.")
                continue
        if collar and final_pt:
            if global_center is None:
                set_center(collar["norte"], collar["este"], collar["cota"])
            for p in pts:
                p.este  = collar["este"]  + p.t*(final_pt["este"]  - collar["este"])
                p.norte = collar["norte"] + p.t*(final_pt["norte"] - collar["norte"])
                p.cota  = collar["cota"]  + p.t*(final_pt["cota"]  - collar["cota"])
        else:
            cx = global_center["este"] if global_center else 0
            cy = global_center["norte"] if global_center else 0
            cz = global_center["cota"] if global_center else 0
            for p in pts:
                p.este = cx; p.norte = cy; p.cota = cz - p.largo
        wells[key] = Well(well_name=key, plan_id=pid, hole_id=hid or "",
                          points=pts, collar=collar, final_pt=final_pt, origin=origin,
                          dq_candidates=cand_info)
    return counts

# ─── PARSERS ──────────────────────────────────────────────────────────────────
def parse_dxf(path, fname):
    try:
        doc, _ = ezdxf.recover.readfile(path)
    except Exception as e:
        raise RuntimeError(f"DXF ilegible: {e}")
    tris, skipped = [], 0
    for ent in doc.modelspace().query("3DFACE"):
        try:
            v0 = np.array(ent.dxf.vtx0, dtype=np.float64)
            v1 = np.array(ent.dxf.vtx1, dtype=np.float64)
            v2 = np.array(ent.dxf.vtx2, dtype=np.float64)
            v3 = np.array(ent.dxf.vtx3 if ent.dxf.hasattr("vtx3") else ent.dxf.vtx2, dtype=np.float64)
            if not all(np.isfinite(v).all() for v in (v0,v1,v2,v3)):
                skipped += 1; continue
            tris.append([v0,v1,v2])
            if not np.allclose(v3, v2): tris.append([v0,v2,v3])
        except: skipped += 1
    if not tris: raise RuntimeError("sin caras 3DFACE válidas")
    if skipped: log_warn(f'DXF "{fname}": {skipped} caras omitidas.')
    return np.array(tris, dtype=np.float64), skipped

# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  SESIÓN E — CACHÉ EN DISCO, orientada al cuello de botella REAL          ║
# ║                                                                          ║
# ║  E.5 (perfilado con archivos reales del repo) mostró que el ray casting ║
# ║  no es el costo dominante: 1,6 s para clasificar 262.500 puntos contra  ║
# ║  la malla más grande del repo (Bht.dxf, 92.918 triángulos). El costo    ║
# ║  real es PARSEAR el DXF — 12,5 s y +210 MB solo para leer y triangular  ║
# ║  esa misma malla, independiente de cuántos puntos se clasifiquen contra ║
# ║  ella. El caché apunta ahí, no al ray casting.                          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

CACHE_DIR = os.environ.get(
    "GEOMECH_CACHE_DIR", os.path.join(os.getcwd(), ".geomech_cache"))
DXF_CACHE_DIR = os.path.join(CACHE_DIR, "dxf")


def _content_hash(data: bytes) -> str:
    """Clave de caché determinística a partir de los bytes crudos del archivo."""
    return hashlib.sha256(data).hexdigest()[:24]


def parse_dxf_cached(raw_bytes: bytes, fname: str) -> Tuple[np.ndarray, int]:
    """
    Envoltorio con caché en disco sobre parse_dxf(), keyed por el HASH DEL
    CONTENIDO del archivo — la geometría triangulada de una malla es una
    función pura de sus propios bytes, NO depende del registro de
    vocabulario (eso solo importa para clasificar, ver
    vocab_classification_signature). Dos archivos con nombres distintos y
    el mismo contenido comparten caché; el mismo nombre con contenido
    distinto (una malla reemplazada) no colisiona nunca.

    Escritura atómica: se escribe a un archivo temporal en el mismo
    directorio y se renombra con os.replace() al terminar, para que una
    interrupción a medio escribir nunca deje un .npz truncado que un
    acierto de caché posterior leería como válido.
    """
    key = _content_hash(raw_bytes)
    os.makedirs(DXF_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(DXF_CACHE_DIR, f"{key}.npz")
    if os.path.exists(cache_path):
        data = np.load(cache_path)
        tris, skipped = data["triangles"], int(data["skipped"])
        if skipped:
            log_warn(f'DXF "{fname}": {skipped} caras omitidas (desde caché).')
        return tris, skipped
    tmp = tempfile.NamedTemporaryFile(suffix=".dxf", delete=False)
    try:
        tmp.write(raw_bytes); tmp.close()
        tris, skipped = parse_dxf(tmp.name, fname)
    finally:
        os.unlink(tmp.name)
    # np.savez_compressed le añade ".npz" a un nombre de archivo que no
    # termine en eso, así que se le pasa un file handle ya abierto (no
    # aplica la magia de extensión) para poder controlar el nombre exacto
    # del temporal y renombrarlo de forma atómica.
    tmp_cache = f"{cache_path}.tmp{os.getpid()}"
    with open(tmp_cache, "wb") as fh:
        np.savez_compressed(fh, triangles=tris, skipped=np.array(skipped))
    os.replace(tmp_cache, cache_path)
    return tris, skipped


def vocab_classification_signature() -> str:
    """
    Hash determinístico de TODO lo que afecta la salida de
    classify_all_wells(): la geometría de cada malla cargada (por
    contenido, no por nombre de archivo) más el rol/nivel/padre de cada
    atributo del registro de vocabulario — que es exactamente lo que
    layer_role_ids()/resolve_overlap_by_role() consultan.

    Deliberadamente NO incluye banda de UCS, calidad, fuente ni
    exclusiones: esos campos gobiernan el ENTRENAMIENTO (ver
    training_composition_report), no la clasificación geométrica, y
    cambiarlos no debe invalidar una clasificación ya calculada.
    """
    partes = []
    for name, lay in sorted(layers.items()):
        tris_hash = hashlib.sha256(lay.triangles.tobytes()).hexdigest()[:16]
        atributos_str = ",".join(f"{k}={v}" for k, v in sorted((lay.atributos or {}).items()))
        partes.append(f"L:{name}|{tris_hash}|{atributos_str}|"
                      f"caseron={lay.caseron}|nivel={lay.nivel}")
    for aid, a in sorted(attr_registry.items()):
        partes.append(f"A:{aid}|rol={a.rol}|nivel={a.nivel}|padre={a.padre}")
    blob = "\n".join(partes).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:24]


_last_classify_signature: Optional[str] = None


def classify_all_wells_cached(force: bool = False) -> bool:
    """
    (E.2, "ningún callback puede disparar una reclasificación completa")
    Memoiza classify_all_wells() contra vocab_classification_signature():
    si nada de lo que afecta la clasificación cambió desde la última
    corrida, no se vuelve a recorrer ningún punto — el resultado ya escrito
    en p.dominio/p.lito/... sigue siendo válido tal cual.

    Devuelve True si reclasificó, False si reutilizó el resultado vigente.
    `force=True` ignora la firma (para un botón explícito de "recalcular").
    """
    global _last_classify_signature
    sig = vocab_classification_signature()
    if not force and sig == _last_classify_signature:
        return False
    classify_all_wells()
    _last_classify_signature = sig
    return True


def _fval(elem, tag, ns=""):
    node = elem.find(f"{ns}{tag}") if elem is not None else None
    if node is None or not node.text: return None
    try: return float(node.text.strip())
    except: return None

def parse_dq(path, fname):
    """Parsea DQ IREDES. TMatrix: row 0→Norte, row 1→Este, row 2→Cota."""
    try: root = ET.parse(path).getroot()
    except Exception as e: raise RuntimeError(f"XML ilegible: {e}")
    tmat = np.zeros((4,4))
    tmn = root.find(f".//{IR}TMatrix")
    if tmn is not None:
        for i, col in enumerate(tmn.findall(f"{IR}Col")[:4]):
            try:
                for j, ax in enumerate(["x","y","z","w"]):
                    n = col.find(f"{IR}{ax}")
                    tmat[j,i] = float(n.text) if n is not None and n.text else 0.0
            except: pass
    def lu(lx, ly, lz):
        return {
            "norte": tmat[0,0]*lx + tmat[0,1]*ly + tmat[0,2]*lz + tmat[0,3],
            "este":  tmat[1,0]*lx + tmat[1,1]*ly + tmat[1,2]*lz + tmat[1,3],
            "cota":  tmat[2,0]*lx + tmat[2,1]*ly + tmat[2,2]*lz + tmat[2,3],
        }
    pn = root.find(f".//{IR}PlanIdRef")
    plan_id = (pn.text or "").strip() if pn is not None else ""
    # Fecha de emisión del DQ: es el criterio para decidir cuál revisión de un
    # mismo abanico gana cuando dos discrepan (ver merge_dq_siblings). Sin
    # ella el "ganador" dependería del orden en que el sistema de archivos
    # devuelve los nombres, que es arbitrario.
    fn = root.find(f".//{IR}FileCreateDate")
    fecha = (fn.text or "").strip() if fn is not None else ""
    tiros, skipped, t0 = {}, 0, time.time()
    hq_list = root.findall(f".//{DR}HoleQualityData")
    for h, hq in enumerate(hq_list):
        if h % 256 == 0 and time.time() - t0 > PARSE_BUDGET_S:
            log_warn(f'DQ "{fname}": timeout, omitidos {len(hq_list)-h} tiros.'); break
        try:
            hole = hq.find(f"{DR}Hole")
            if hole is None: skipped += 1; continue
            hid = (hole.findtext(f"{DR}HoleId") or "").strip()
            sp, ep = hole.find(f"{DR}StartPoint"), hole.find(f"{DR}EndPoint")
            if not hid or sp is None or ep is None: skipped += 1; continue
            coords = [_fval(sp,"PointX",IR),_fval(sp,"PointY",IR),_fval(sp,"PointZ",IR),
                      _fval(ep,"PointX",IR),_fval(ep,"PointY",IR),_fval(ep,"PointZ",IR)]
            if any(v is None or not np.isfinite(v) for v in coords): skipped+=1; continue
            tiros[hid] = {"collar":lu(*coords[:3]), "final_pt":lu(*coords[3:])}
        except: skipped += 1
    if skipped: log_warn(f'DQ "{fname}": {skipped} tiros omitidos.')
    return {"plan_id": plan_id, "tiros": tiros, "fecha": fecha, "fname": fname}


# Desplazamiento de collar entre revisiones de un mismo tiro sobre el cual el
# desacuerdo deja de ser tolerancia de relevamiento y pasa a ser un hallazgo
# que hay que mirar. En PCS_1043 la mediana de los tiros que difieren es
# 1,3 m, pero hay 34 casos sobre 20 m: no son la misma perforación.
DQ_MERGE_WARN_M = 5.0


def merge_dq_siblings(dq_list: List[Dict]) -> Tuple[Dict[str, Dict], Dict]:
    """
    Fusiona los DQ que comparten plan_id (revisiones sucesivas del mismo
    abanico) en un solo plan por id, uniendo sus tiros.

    Un abanico real se re-releva varias veces y cada revisión trae un
    subconjunto distinto de tiros: PCS_1043 llega con 56 archivos DQ para 34
    planes, y el plan P107 tiene cuatro revisiones con 23, 14, 13 y 13 tiros.
    Quedarse con UNA sola —la primera o la última en llegar— pierde los tiros
    que solo aparecen en las otras, y con ellos todo el MWD que los
    referencia (sin fusionar: 345 de 468 pozos ambiguos; fusionando: 9).

    Cuando dos revisiones dan coordenadas DISTINTAS para el mismo tiro gana
    la más reciente por `fecha`, pero el desacuerdo NUNCA se resuelve en
    silencio: se devuelve en el reporte con su magnitud, y los que superan
    DQ_MERGE_WARN_M quedan además como advertencia visible. Un collar que se
    corre 20 m entre revisiones es un dato geológico, no ruido.

    Devuelve (merged, reporte):
      merged   {plan_id: {"plan_id","tiros","fecha","fname"}}
      reporte  {"n_archivos","n_planes","n_tiros","n_descartados","conflictos"}
               conflictos: [{plan_id, hole_id, dist_m, gana, pierde}, ...]
    """
    # Orden estable por fecha: el último en escribirse gana, y como el orden
    # es por fecha (no por el orden de llegada de los archivos), el resultado
    # no depende de cómo el sistema de archivos devolvió los nombres.
    ordenados = sorted(dq_list, key=lambda d: (d.get("fecha") or "", d.get("fname") or ""))
    merged: Dict[str, Dict] = {}
    procedencia: Dict[Tuple[str, str], Dict] = {}   # (plan,hole) -> dq que lo puso
    conflictos: List[Dict] = []
    n_descartados = 0
    for dq in ordenados:
        pid = (dq.get("plan_id") or "").strip()
        tiros = dq.get("tiros") or {}
        # Sin plan_id o sin tiros no hay nada que fusionar: un archivo así
        # (p.ej. un plan de perforación mal clasificado como DQ) entraría
        # como plan fantasma y contaminaría el matching.
        if not pid or not tiros:
            n_descartados += 1
            continue
        destino = merged.setdefault(
            pid, {"plan_id": pid, "tiros": {}, "fecha": dq.get("fecha", ""),
                  "fname": dq.get("fname", "")})
        for hid, t in tiros.items():
            previo = destino["tiros"].get(hid)
            if previo is not None:
                d = _collar_dist(previo, t)
                if d > 1e-3:
                    antes = procedencia.get((pid, hid), {})
                    conflictos.append({
                        "plan_id": pid, "hole_id": hid, "dist_m": round(d, 3),
                        "gana": f'{dq.get("fname","?")} ({dq.get("fecha","sin fecha")})',
                        "pierde": f'{antes.get("fname","?")} ({antes.get("fecha","sin fecha")})',
                    })
            destino["tiros"][hid] = t
            procedencia[(pid, hid)] = dq
        # El plan hereda la fecha/archivo de la revisión más reciente que lo tocó.
        destino["fecha"] = dq.get("fecha", "")
        destino["fname"] = dq.get("fname", "")

    grandes = [c for c in conflictos if c["dist_m"] > DQ_MERGE_WARN_M]
    for c in grandes[:20]:
        log_warn(f'DQ "{c["plan_id"]}" tiro {c["hole_id"]}: el collar se desplaza '
                 f'{c["dist_m"]:g} m entre revisiones. Se usa {c["gana"]}, se descarta '
                 f'{c["pierde"]}. Verifica cuál corresponde al pozo perforado.')
    if len(grandes) > 20:
        log_warn(f'DQ: {len(grandes)-20} desplazamiento(s) grande(s) más, no listados.')
    if conflictos:
        log_warn(f'DQ: {len(conflictos)} tiro(s) con coordenadas distintas entre '
                 f'revisiones del mismo plan ({len(grandes)} sobre {DQ_MERGE_WARN_M:g} m). '
                 f'Gana siempre la revisión más reciente.')
    if n_descartados:
        log_warn(f'DQ: {n_descartados} archivo(s) sin plan_id o sin tiros, descartados.')
    reporte = {
        "n_archivos": len(dq_list), "n_planes": len(merged),
        "n_tiros": sum(len(v["tiros"]) for v in merged.values()),
        "n_descartados": n_descartados, "conflictos": conflictos,
    }
    return merged, reporte


def _collar_dist(a: Dict, b: Dict) -> float:
    """Distancia entre los collares de dos versiones del mismo tiro."""
    try:
        ca, cb = a["collar"], b["collar"]
        return float(np.sqrt(sum((ca[k] - cb[k]) ** 2 for k in ("este", "norte", "cota"))))
    except Exception:
        return 0.0

def parse_mw(path, fname):
    """
    Val = LT | ROP | PP | FP(Feed=AP) | DP | RP | FLP(Flush=FP). Simba COPROD.

    (E.3 — Escala) Streaming con ET.iterparse en vez de ET.parse().getroot():
    con ~150 pozos por caserón, materializar los 150 árboles DOM completos en
    memoria a la vez no es viable en Colab. Cada <Sample> se procesa y se
    libera (elem.clear()) apenas se extrae su <Val>, en vez de acumular el
    documento entero antes de empezar. PlanIdRef/MWDholeId/MWDparams
    aparecen antes que los <Sample> en el orden del documento IREDES, así
    que un solo pase basta.
    """
    plan_id, hole_id = "", None
    declarados: List[str] = []
    declarados_cerrado = False
    n_extra_decl = 0

    def _cerrar_declarados():
        nonlocal declarados_cerrado, n_extra_decl
        if declarados_cerrado: return
        declarados_cerrado = True
        # Orden inmutable de `Val`: LT | ROP | PP | FP | DP | RP | FLP. Exactamente 7.
        # Los equipos declaran a veces columnas extra (Simba COPROD emite OPT1,
        # "DRMWDoption"); se descartan del uso, pero la convención exige
        # REPORTARLAS UNA VEZ en la carga: un campo excedente silencioso es
        # indistinguible de un cambio de esquema del equipo, que sí
        # invalidaría el orden de los 7.
        n_extra_decl = max(len(declarados) - MWD_VAL_FIELDS, 0)
        if n_extra_decl:
            log_warn(f'MWD "{fname}": {n_extra_decl} campo(s) excedente(s) declarado(s) '
                     f'y descartado(s): {", ".join(declarados[MWD_VAL_FIELDS:])}. '
                     f'Se usan los {MWD_VAL_FIELDS} de la convención '
                     f'({" | ".join(MWD_VAL_ORDER)}).')

    puntos, largo_max, skipped, t0 = [], 0.0, 0, time.time()
    n_extra_val = 0             # muestras con más valores que campos declarados
    n_procesadas = 0
    try:
        for _, elem in ET.iterparse(path, events=("end",)):
            tag = elem.tag
            if tag == f"{IR}PlanIdRef":
                if not plan_id: plan_id = (elem.text or "").strip()
                elem.clear()
            elif tag == f"{DR}MWDholeId":
                if hole_id is None: hole_id = (elem.text or "").strip() or None
                elem.clear()
            elif tag == f"{DR}Parameter":
                declarados.append((elem.text or "").strip())
                elem.clear()
            elif tag == f"{DR}Sample":
                _cerrar_declarados()   # todo <Parameter> ya cerró antes que el primer <Sample>
                if n_procesadas % 512 == 0 and time.time() - t0 > PARSE_BUDGET_S:
                    log_warn(f'MWD "{fname}": timeout tras procesar {n_procesadas} '
                             f'muestra(s); el resto del archivo se omite.')
                    elem.clear()
                    break
                try:
                    vn = elem.find(f"{DR}Val")
                    if vn is None or not vn.text: skipped += 1
                    else:
                        parts = [float(x) for x in vn.text.strip().split()]
                        if len(parts) < 7: skipped += 1
                        else:
                            if len(parts) > MWD_VAL_FIELDS and not n_extra_decl: n_extra_val += 1
                            lt, rop, pp, ap, dp, rp, flp = parts[:7]
                            if not all(np.isfinite(v) for v in (lt,rop,pp,ap,dp,rp,flp)):
                                skipped += 1
                            else:
                                se = (pp + rp + ap) / (rop + EPS)
                                puntos.append(MWDPoint(
                                    largo=lt, vel=rop, pp=pp, pa=ap, pd=dp, pr=rp, pf=flp,
                                    se=se, t=0.0, raw_vel=rop, raw_pp=pp, raw_pa=ap,
                                    raw_pd=dp, raw_pr=rp, raw_pf=flp,
                                ))
                                if lt > largo_max: largo_max = lt
                except Exception:
                    skipped += 1
                n_procesadas += 1
                elem.clear()
    except Exception as e:
        raise RuntimeError(f"XML ilegible: {e}")
    _cerrar_declarados()   # archivo sin ningún <Sample>: igual se reporta el excedente

    if not hole_id:
        m = re.search(r"H(\d+)_", fname, re.I)
        if m: hole_id = m.group(1)
    if not plan_id:
        m2 = re.search(r"MW(.+?)H\d+_", fname, re.I)
        if m2: plan_id = m2.group(1)

    if skipped: log_warn(f'MWD "{fname}": {skipped} muestras omitidas.')
    # Excedente NO declarado en MWDparams: se reporta igual, una sola vez.
    if n_extra_val:
        log_warn(f'MWD "{fname}": {n_extra_val} muestra(s) con más de {MWD_VAL_FIELDS} '
                 f'valores en <Val> sin declararlos en <MWDparams>; el excedente se '
                 f'descarta. Verifica que el orden {" | ".join(MWD_VAL_ORDER)} siga vigente.')
    for p in puntos: p.t = p.largo/largo_max if largo_max > 0 else 0.0
    return {"plan_id": plan_id, "hole_id": hole_id, "largo_max": largo_max, "puntos": puntos}

def is_dq(fname, root_tag=""):
    return "DRPQual" in root_tag or fname.upper().startswith("DQ")

def guess_kind(fname):
    """
    Tipo de malla por nombre de archivo. Es solo una SUGERENCIA inicial: el
    usuario la corrige en el árbol de capas. La alteración se separa de la
    litología porque se compone con ella en vez de competir (T1.4).
    """
    fl = _norm_txt(fname)
    if any(x in fl for x in ("falla", "fault", "struct", "fractura", "dique", "contacto")):
        return "estructura"
    if any(x in fl for x in ("alteracion", "alter", "argilic", "potasic", "propilit",
                             "filic", "sericit", "silicif")):
        return "alteracion"
    return "litologia"

def parse_excel(path):
    try:
        df = pd.read_excel(path, header=0)
        df.columns = [str(c).strip().lower() for c in df.columns]
    except Exception as e:
        raise RuntimeError(f"Excel ilegible: {e}")
    col_map = {
        "caseron":["caseron","caserón","sector"],"perfil":["perfil","nivel","galeria"],
        "tiro":["tiro","hole","id","nro","numero"],
        "vel":["vel","rop","velocidad"],"pp":["pp","percusion","percusión"],
        "pr":["pr","rp","rotacion","rotación"],"pa":["pa","ap","avance"],
        "pd":["pd","dp","damper"],"pf":["pf","fp","flujo"],
        "ucs_excel":["ucs","resistencia","mpa","ucs_prom"],
        "seteo_pp":["seteo pp","set pp","pp set","seteo_pp","sp","spp"],
        "seteo_pa":["seteo pa","set pa","pa set","seteo_pa","sa","spa"],
    }
    def find_col(cands):
        for c in cands:
            hits = [col for col in df.columns if c in col]
            if hits: return hits[0]
        return None
    mapping = {k: find_col(v) for k,v in col_map.items()}
    rows = []
    for _, row in df.iterrows():
        r = {}
        for k, col in mapping.items():
            if col and col in df.columns:
                v = row[col]
                if k in ("caseron","perfil","tiro"):
                    r[k] = str(v).strip() if pd.notna(v) else None
                else:
                    try: r[k] = float(v) if pd.notna(v) else None
                    except: r[k] = None
            else: r[k] = None
        if r.get("tiro") is None: continue
        ucs = r.get("ucs_excel")
        if ucs is not None and (ucs < UCS_CONFIG["physical_min"] or ucs > UCS_CONFIG["physical_max"]):
            log_warn(f'Excel: UCS={ucs} MPa fuera físico, tiro {r.get("tiro")} omitido.')
            continue
        # seteo fields pass-through (already float|None from mapping above)
        rows.append(r)
    return rows

# ─── EXCEL GEOMECÁNICO caserón×litología (T2) ─────────────────────────────────
# Columnas por índice (fila de encabezados = índice 2, datos desde índice 3):
#   2=Caserón · 3=Nivel · 23=Litología · 24=UCS[MPa] · 25=RMR · 26=RQD · 27=GSI
GEO_COL = {"caseron":2, "nivel":3, "litologia":23, "ucs":24, "rmr":25, "rqd":26, "gsi":27}
GEO_SHEET = "BUDGET_S_2026_V02"
GEO_HEADER_ROW = 2   # 0-indexado; datos desde GEO_HEADER_ROW+1

def _norm_txt(s):
    """Normaliza texto para matching: minúsculas, sin acentos, sin espacios extra."""
    if s is None: return ""
    s = str(s).strip().lower()
    trans = str.maketrans("áàäâãéèëêíìïîóòöôõúùüûñ", "aaaaaeeeeiiiiooooouuuun")
    return " ".join(s.translate(trans).split())

def _parse_band(raw):
    """
    Parsea un rango geomecánico tolerante a 'lo - hi', 'lo a hi' o valor único.
    Devuelve (lo, mid, hi) o None si no hay número. UCS/RMR/RQD/GSI son no
    negativos, así que se ignoran signos (un '-' es separador, no negativo).
    """
    if raw is None: return None
    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none", "-", "—", "s/i", "sin dato"):
        return None
    nums = re.findall(r"\d+(?:[.,]\d+)?", s)
    if not nums: return None
    vals = [float(n.replace(",", ".")) for n in nums]
    lo, hi = (vals[0], vals[0]) if len(vals) == 1 else (min(vals[0], vals[1]), max(vals[0], vals[1]))
    return lo, (lo + hi) / 2.0, hi

def parse_geomech_excel(path, sheet=GEO_SHEET):
    """
    Parsea el Excel geomecánico caserón×litología. Devuelve una lista de
    registros {caseron, litologia, ucs_lo, ucs_mid, ucs_hi, rmr_raw,
    rqd_lo, rqd_mid, rqd_hi, gsi_raw}. Salta filas sin litología.
    Lee por índice de columna (header=None) para no depender de los nombres.
    """
    try:
        xls = pd.ExcelFile(path)
        sh = sheet if sheet in xls.sheet_names else xls.sheet_names[0]
        df = pd.read_excel(path, sheet_name=sh, header=None)
    except Exception as e:
        raise RuntimeError(f"Excel geomecánico ilegible: {e}")

    def cell(row, key):
        j = GEO_COL[key]
        if j >= df.shape[1]: return None
        v = row.iloc[j]
        return v if pd.notna(v) else None

    records = []
    for i in range(GEO_HEADER_ROW + 1, df.shape[0]):
        row = df.iloc[i]
        lito = cell(row, "litologia")
        caseron = cell(row, "caseron")
        if lito is None or not str(lito).strip():
            continue  # fila sin litología → se salta
        ucs_b = _parse_band(cell(row, "ucs"))
        rqd_b = _parse_band(cell(row, "rqd"))
        rec = {
            "caseron": str(caseron).strip() if caseron is not None else "",
            "litologia": str(lito).strip(),
            "ucs_lo":  ucs_b[0] if ucs_b else None,
            "ucs_mid": ucs_b[1] if ucs_b else None,
            "ucs_hi":  ucs_b[2] if ucs_b else None,
            "rmr_raw": None if cell(row, "rmr") is None else str(cell(row, "rmr")).strip(),
            "rqd_lo":  rqd_b[0] if rqd_b else None,
            "rqd_mid": rqd_b[1] if rqd_b else None,
            "rqd_hi":  rqd_b[2] if rqd_b else None,
            "gsi_raw": None if cell(row, "gsi") is None else str(cell(row, "gsi")).strip(),
        }
        records.append(rec)
    index_geomech_bands(records)
    return records

def index_geomech_bands(records):
    """Reconstruye los índices globales geomech_bands a partir de los registros."""
    geomech_bands["by_pair"].clear()
    geomech_bands["by_lito"].clear()
    geomech_bands["by_caseron"].clear()
    geomech_bands["records"] = list(records)
    for rec in records:
        cn, ln = _norm_txt(rec["caseron"]), _norm_txt(rec["litologia"])
        geomech_bands["by_pair"][(cn, ln)] = rec
        geomech_bands["by_lito"].setdefault(ln, []).append(rec)
        if cn:
            geomech_bands["by_caseron"].setdefault(cn, []).append(rec)

def excel_caserones():
    """Lista ordenada de caserones presentes en el Excel geomecánico."""
    seen = []
    for rec in geomech_bands["records"]:
        c = rec["caseron"]
        if c and c not in seen: seen.append(c)
    return sorted(seen)

def excel_litologias():
    """Lista ordenada de litologías presentes en el Excel geomecánico."""
    seen = []
    for rec in geomech_bands["records"]:
        l = rec["litologia"]
        if l and l not in seen: seen.append(l)
    return sorted(seen)

def lito_identities(lito) -> set:
    """
    Todos los textos normalizados que denotan la misma litología: el propio
    texto, y —si resuelve a un atributo canónico— su id, su nombre oficial y
    todos sus alias.

    (A.2) Necesario desde que el dominio se expresa en atributos canónicos: un
    punto con p.lito == "Bht" debe seguir emparejando con una capa llamada
    "Bht_Fk" y con una fila de Excel que diga "Brecha Hidrotermal". Sin esto,
    asignar vocabulario a una capa haría que la verificación de banda dejara
    de evaluar EN SILENCIO.
    """
    if not lito: return set()
    out = {_norm_txt(lito)}
    aid = resolve_alias(lito).get("litologia")
    if aid and aid in attr_registry:
        a = attr_registry[aid]
        out.add(_norm_txt(a.id)); out.add(_norm_txt(a.nombre_oficial))
        for al in alias_registry.values():
            if al.atributos.get("litologia") == aid:
                out.add(_norm_txt(al.texto_crudo))
    return {t for t in out if t}


def lookup_band(caseron, litologia):
    """
    Banda de una caserón×litología. Requiere caserón (decisión D1: la unidad de
    etiquetado es la intersección, no la litología global). Devuelve el record
    o None. Matching por texto normalizado (sin acentos/mayúsculas) y por
    cualquier alias canónico de la litología.
    """
    if not caseron or not litologia: return None
    cn = _norm_txt(caseron)
    directo = geomech_bands["by_pair"].get((cn, _norm_txt(litologia)))
    if directo is not None: return directo
    for ident in lito_identities(litologia):
        rec = geomech_bands["by_pair"].get((cn, ident))
        if rec is not None: return rec
    return None

def bands_for_caseron(caseron):
    """Todas las bandas (por litología) de un caserón dado."""
    if not caseron: return []
    return geomech_bands["by_caseron"].get(_norm_txt(caseron), [])

def apply_layer_band(layer):
    """
    Autocompleta la banda [ucs_lo, ucs_hi] y ucs_mid de una Layer si tiene
    caserón asignado y su nombre (o lito_alias) matchea una litología del Excel.
    Solo fija ucs_lab = ucs_mid si el usuario no lo había puesto a mano
    (comportamiento manual intacto). Devuelve True si autocompletó.
    """
    lito = layer.lito_alias or layer.name
    band = lookup_band(layer.caseron, lito)
    if band is None or band.get("ucs_mid") is None:
        return False
    layer.ucs_lo, layer.ucs_mid, layer.ucs_hi = band["ucs_lo"], band["ucs_mid"], band["ucs_hi"]
    if layer.ucs_lab is None:
        layer.ucs_lab = round(float(band["ucs_mid"]), 1)
    return True

# ─── MOTOR GEOMECÁNICO ────────────────────────────────────────────────────────
def _moller_trumbore_batch(origins, direction, tris, eps=1e-7):
    v0, v1, v2 = tris[:,0,:], tris[:,1,:], tris[:,2,:]
    e1 = v1 - v0; e2 = v2 - v0
    pvec = np.cross(direction, e2)
    det = np.einsum("ti,ti->t", e1, pvec)
    valid = np.abs(det) > eps
    inv = np.where(valid, 1.0/np.where(valid, det, 1.0), 0.0)
    tvec = origins[:,None,:] - v0[None,:,:]
    u = np.einsum("nti,ti->nt", tvec, pvec) * inv
    qvec = np.cross(tvec, e1[None,:,:])
    v = np.einsum("nti,i->nt", qvec, direction) * inv
    t = np.einsum("nti,ti->nt", qvec, e2) * inv
    hit = valid[None,:] & (u>=0) & (u<=1) & (v>=0) & ((u+v)<=1) & (t>eps)
    return hit.sum(axis=1)

def _layer_grid(layer, target_tris_per_cell=8):
    """
    Grid espacial 2D (Este/Norte) cacheado en la Layer, válido SOLO para rayo
    VERTICAL (0,0,1). Con rayo vertical, un triángulo solo puede ser cruzado
    por un punto cuya proyección XY caiga dentro del bbox XY del triángulo —
    el rayo nunca "sale" del tubo XY de su celda de origen, a diferencia de un
    rayo oblicuo (que sí cruza celdas vecinas y por tanto invalidaría un grid
    2D simple). Este es el motivo por el que se fuerza rayo vertical en
    points_in_mesh: permite la aceleración espacial sin perder intersecciones.
    """
    if not hasattr(layer, "_grid"):
        tris = layer.triangles
        tri_bmin = tris.min(axis=1); tri_bmax = tris.max(axis=1)
        span = layer.bbox_max[:2] - layer.bbox_min[:2]
        n_tris = max(len(tris), 1)
        area = max(float(span[0]) * float(span[1]), 1.0)
        cell = max(float(np.sqrt(area * target_tris_per_cell / n_tris)), 0.5)
        layer._grid_cell = cell
        gx0 = np.floor((tri_bmin[:,0]-layer.bbox_min[0])/cell).astype(np.int32)
        gy0 = np.floor((tri_bmin[:,1]-layer.bbox_min[1])/cell).astype(np.int32)
        gx1 = np.floor((tri_bmax[:,0]-layer.bbox_min[0])/cell).astype(np.int32)
        gy1 = np.floor((tri_bmax[:,1]-layer.bbox_min[1])/cell).astype(np.int32)
        grid = {}
        for ti in range(n_tris):
            for cx in range(gx0[ti], gx1[ti]+1):
                for cy in range(gy0[ti], gy1[ti]+1):
                    grid.setdefault((cx,cy), []).append(ti)
        layer._grid = {k: np.array(v, dtype=np.int64) for k,v in grid.items()}
    return layer._grid_cell, layer._grid

def points_in_mesh(points, layer, batch=256):
    """
    points (N,3) [Este, Norte, Cota] → bool (N,). Triángulos en el mismo sistema.

    IMPORTANTE: usa rayo estrictamente VERTICAL (0,0,1), no oblicuo. Esto es
    lo que permite acotar candidatos con un grid espacial 2D en XY sin perder
    intersecciones (ver _layer_grid). Una versión anterior usaba un rayo
    oblicuo (0.577,0.577,0.577) combinado con este mismo grid, lo cual es
    matemáticamente inválido: el rayo oblicuo cruza celdas vecinas en su
    trayectoria, así que acotar candidatos por la celda de origen del punto
    perdía la mayoría de las intersecciones reales (bug que causó que solo
    ~7% de los puntos se detectaran dentro de la malla, en vez del ~82% real).
    """
    n = len(points)
    inside = np.zeros(n, dtype=bool)
    lo = layer.bbox_min - 1.0; hi = layer.bbox_max + 1.0
    cand = np.where(np.all((points >= lo) & (points <= hi), axis=1))[0]
    if cand.size == 0: return inside

    cell, grid = _layer_grid(layer)
    ray = np.array([0.0, 0.0, 1.0], dtype=np.float64)   # vertical: requisito para que el grid XY sea válido

    pts_c = points[cand]
    gx = np.floor((pts_c[:,0] - layer.bbox_min[0]) / cell).astype(np.int32)
    gy = np.floor((pts_c[:,1] - layer.bbox_min[1]) / cell).astype(np.int32)
    cell_keys = {}
    for local_i, (cx, cy) in enumerate(zip(gx, gy)):
        cell_keys.setdefault((int(cx), int(cy)), []).append(local_i)

    for (cx, cy), local_idxs in cell_keys.items():
        tri_idx = grid.get((cx, cy))
        if tri_idx is None or tri_idx.size == 0:
            continue
        sub_tris = layer.triangles[tri_idx]
        local_idxs = np.array(local_idxs, dtype=np.int64)
        sub_pts = pts_c[local_idxs]
        for start in range(0, len(sub_pts), batch):
            chunk = sub_pts[start:start+batch]
            cnt = _moller_trumbore_batch(chunk, ray, sub_tris)
            hit = (cnt % 2) == 1
            global_idx = cand[local_idxs[start:start+batch]]
            inside[global_idx] = hit
    return inside

def classify_all_wells():
    """
    Clasifica cada punto MWD contra las mallas cargadas, resolviendo traslapes
    con las cuatro reglas por rol (A.5).

    Ya NO se sobrescribe con la última malla que acierta (`lito_hit[i] = name`):
    se acumulan TODOS los aciertos, agrupados POR ROL y expresados en atributos
    canónicos, y se resuelven con resolve_overlap_by_role(). Un punto con
    Conflicto se marca `ambiguo` y queda fuera del dominio, pero contabilizado
    en overlap_stats — nunca descartado en silencio.

    Como las reglas operan sobre atributos canónicos y no sobre nombres de
    capa, una malla compuesta (Bht_Fk.dxf) y dos mallas separadas que se
    traslapan producen EL MISMO dominio.
    """
    layer_items = list(layers.items())
    overlap_stats.update({"n_puntos": 0, "n_ambiguos": 0, "n_subunidad_gana": 0,
                          "n_compuestos": 0, "n_sin_lito": 0, "n_sin_clasificar": 0,
                          "casos": {}, "motivos": {}})
    for wn, well in wells.items():
        pts = well.points
        if not pts: continue
        try:
            coords = np.array([[p.este, p.norte, p.cota] for p in pts], dtype=np.float64)
            valid = np.all(np.isfinite(coords), axis=1)
            # Acumular TODOS los aciertos por punto y por rol, no solo el último.
            hits: List[Dict[str, List[str]]] = [{} for _ in pts]
            for name, layer in layer_items:
                try:
                    roles = layer_role_ids(layer)
                    if not roles: continue
                    mask = np.zeros(len(pts), dtype=bool)
                    if valid.any():
                        mask[valid] = points_in_mesh(coords[valid], layer)
                    for i in np.where(mask)[0]:
                        for rol, ident in roles.items():
                            hits[i].setdefault(rol, []).append(ident)
                except Exception as e:
                    log_warn(f'Clasificación "{name}" en "{wn}": {e}')
            for i, p in enumerate(pts):
                overlap_stats["n_puntos"] += 1
                resuelto, motivo, anidado = resolve_overlap_by_role(hits[i])
                if anidado: overlap_stats["n_subunidad_gana"] += 1
                p.ambiguo = False; p.ambiguo_motivo = None
                if motivo:
                    # Conflicto: se excluye el punto del dominio y se contabiliza.
                    p.ambiguo = True; p.ambiguo_motivo = motivo
                    p.atributos = {}
                    p.lito = None; p.alteracion = None; p.estructura = None
                    p.dominio = None
                    overlap_stats["n_ambiguos"] += 1
                    caso = " | ".join(f"{r}:{'+'.join(sorted(set(v)))}"
                                      for r, v in sorted(hits[i].items()))
                    overlap_stats["casos"][caso] = overlap_stats["casos"].get(caso, 0) + 1
                    overlap_stats["motivos"][motivo] = overlap_stats["motivos"].get(motivo, 0) + 1
                    continue
                p.atributos = resuelto
                lh = resuelto.get("litologia")
                ah = resuelto.get("alteracion")
                eh = resuelto.get("estructura")
                p.lito, p.alteracion, p.estructura = lh, ah, eh
                p.dominio = make_dominio(lh, ah, eh)
                if lh is None: overlap_stats["n_sin_lito"] += 1
                if lh and ah: overlap_stats["n_compuestos"] += 1
                if p.dominio is None: overlap_stats["n_sin_clasificar"] += 1
        except Exception as e:
            log_warn(f'Clasificación pozo "{wn}": {e}')

def parse_dominio(d: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """(litologia, alteracion, estructura) a partir de la clave de dominio."""
    if not d or d == "(sin dominio)": return None, None, None
    izq, _, est = d.partition("::")
    lito, _, alt = izq.partition("~")
    return (lito or None), (alt or None), (est or None)


def _manual_ucs_for(lito_id: str) -> Optional[float]:
    """
    Sobrescritura manual de UCS aplicable a una identidad de litología.
    Es una decisión explícita del usuario y gana sobre el registro.
    """
    for lay in layers.values():
        if lay.ucs_lab is None: continue
        if layer_role_ids(lay).get("litologia") == lito_id:
            return lay.ucs_lab
    return None


def build_domain_index():
    """
    Indexa dominios y les adosa el ancla de UCS.

    (A.5) La clave de dominio es el par (litologia, alteracion|None) más la
    estructura predominante, expresada en ATRIBUTOS CANÓNICOS. Por eso el
    índice se construye desde la propia clave del dominio y no recorriendo
    capas por nombre: así Bht_Fk (malla compuesta) y Bht+Fk (mallas separadas)
    caen en el mismo dominio y heredan la misma banda.

    LA BANDA DE UCS ES PROPIEDAD DE LA LITOLOGÍA. Bht+Fk y Bht+otra alteración
    son dominios distintos que heredan la MISMA banda como valor previo; si el
    MWD muestra que difieren, eso es un hallazgo, no un error.
    """
    domains.clear()
    for p in all_points():
        d = p.dominio or "(sin dominio)"
        if d not in domains:
            domains[d] = {"count": 0, "ucs_lab": None, "atributo_id": None,
                          "alteracion_id": None, "estructura_id": None,
                          "pi_factor": None, "calidad": None, "fuente_ucs": None}
        domains[d]["count"] += 1
    for d, info in domains.items():
        lito, alt, est = parse_dominio(d)
        info["alteracion_id"] = alt
        info["estructura_id"] = est
        if not lito: continue
        attr = attr_registry.get(lito)
        if attr is not None and attr.rol != "litologia": attr = None
        manual = _manual_ucs_for(lito)
        ucs = manual if manual is not None else (attr.ucs_ancla() if attr else None)
        if ucs is not None:
            info["ucs_lab"] = ucs
            info["fuente_ucs"] = ("manual" if manual is not None
                                  else (attr.fuente if attr else None))
        if attr is not None:
            info["atributo_id"] = attr.id
            info["pi_factor"] = attr.pi_factor()
            info["calidad"] = attr.calidad

def apply_calibration():
    cf = cal_factors
    for p in all_points():
        for k in ("vel","pp","pa","pd","pr","pf"):
            setattr(p, k, getattr(p, f"raw_{k}") * cf[k])
        p.se = (p.pp + p.pr + p.pa) / (p.vel + EPS) * cf.get("se", 1.0)

def derive_cal_factors_from_excel():
    var_map = {"vel":"vel","pp":"pp","pr":"pr","pa":"pa","pd":"pd","pf":"pf"}
    esums = {k:0.0 for k in var_map}; rsums = {k:0.0 for k in var_map}; counts = {k:0 for k in var_map}
    for ex in excel_data:
        wkey = next((k for k in wells if str(ex.get("perfil","")) in k and str(ex.get("tiro","")) in k), None)
        if not wkey: continue
        pts = wells[wkey].points
        if not pts: continue
        for k in var_map:
            v_excel = ex.get(k)
            if v_excel is None or not np.isfinite(v_excel): continue
            raw_vals = [getattr(p, f"raw_{k}") for p in pts if np.isfinite(getattr(p, f"raw_{k}", 0))]
            if not raw_vals: continue
            rmean = np.mean(raw_vals)
            if rmean == 0: continue
            esums[k] += v_excel; rsums[k] += rmean; counts[k] += 1
    return {k: round(esums[k]/rsums[k], 4) for k in var_map if counts[k] > 0 and rsums[k] > 0}

def apply_seteo_from_excel():
    """
    Propaga los campos seteo_pp / seteo_pa de los registros excel_data a los
    MWDPoint del pozo correspondiente. El valor de seteo es constante por tiro
    (el operador lo fija antes de perforar), así que se asigna igualmente a
    todos los puntos del pozo. Sólo actúa si la fila excel tiene al menos uno
    de los dos campos no None.
    """
    for ex in excel_data:
        spp = ex.get("seteo_pp")
        spa = ex.get("seteo_pa")
        if spp is None and spa is None:
            continue
        wkey = next((k for k in wells
                     if str(ex.get("perfil","")) in k and str(ex.get("tiro","")) in k), None)
        if wkey is None:
            continue
        for p in wells[wkey].points:
            if spp is not None: p.seteo_pp = spp
            if spa is not None: p.seteo_pa = spa

def apply_inicio_filter(cut_m):
    """(P3-3.8) Recuerda el corte vigente en `inicio_cut_m`, para que
    recompute_filters() pueda reaplicarlo sin caer a un default hardcodeado."""
    global inicio_cut_m
    inicio_cut_m = float(cut_m)
    for well in wells.values():
        for p in well.points:
            if p.largo < cut_m: p.entrenable = False
            elif not p.norm_excluded: p.entrenable = True

def add_norm_filter(var_name, method):
    all_pts = list(all_points())
    vals = np.array([getattr(p, var_name) for p in all_pts
                     if getattr(p, var_name, None) is not None and
                     np.isfinite(getattr(p, var_name))], dtype=np.float64)
    if vals.size == 0: return None
    q25, q75 = np.percentile(vals, [25, 75]); iqr = q75-q25
    lmap = {
        "outliers_iqr":("IQR 1.5×", q25-1.5*iqr, q75+1.5*iqr),
        "q25_q75":("Q25-Q75", q25, q75),
        "whisker5":("5%-95%", *np.percentile(vals,[5,95])),
        "quantile_reg":("Q10-Q90", *np.percentile(vals,[10,90])),
    }
    label, lo, hi = lmap.get(method, ("rango", float(vals.min()), float(vals.max())))
    before = sum(1 for p in all_pts if p.entrenable)
    for well in wells.values():
        for p in well.points:
            v = getattr(p, var_name, None)
            if v is not None and (v < lo or v > hi):
                p.entrenable = False; p.norm_excluded = True
    after = sum(1 for p in all_points() if p.entrenable)
    filt = {"varName":var_name,"method":method,"label":label,
            "lo":round(float(lo),3),"hi":round(float(hi),3),
            "removed":before-after,"after":after,"total":len(all_pts)}
    clean_filters.append(filt)
    return filt

def _moving_variance(arr, half):
    n = len(arr); kernel = np.ones(2*half+1)
    counts = np.convolve(np.ones(n), kernel, mode="same")
    sums = np.convolve(arr, kernel, mode="same")
    sums2 = np.convolve(arr**2, kernel, mode="same")
    mean = sums/counts
    return np.maximum(sums2/counts - mean**2, 0.0)

def di_profile(points, window, params=None, weights=None):
    """
    (T7b) Calcula el perfil DI de una lista de puntos MWD SIN efectos
    laterales: no lee ni escribe p.di, solo usa las variables MWD (pp/pr/etc.)
    de cada punto. Función pura extraída de compute_di (que ahora delega en
    ésta) para poder recalcular el DI con otras ventanas/parámetros —p.ej. el
    análisis de sensibilidad del Paso 3— sin sobrescribir el DI oficial de los
    puntos. Misma fórmula exacta que antes del refactor (regresión: idénticos
    p.di para ventana=14, ver test_di_rqd.py / test suite T7).

    Devuelve un array (len(points),) con el DI, o None si len(points) < window.
    """
    params = params if params is not None else di_config["params"]
    weights = weights if weights is not None else di_config["weights"]
    half = window // 2
    n = len(points)
    if n < window:
        return None
    total_w = sum(weights.get(k, 0) for k in params) or 1.0
    norm_w = {k: weights.get(k, 0) / total_w for k in params}
    total = np.zeros(n)
    for k in params:
        arr = np.array([getattr(p, k) for p in points], dtype=np.float64)
        mv = _moving_variance(arr, half)
        std = mv.std() or 1e-9
        z = (mv - mv.mean()) / std
        total += norm_w[k] * z**2
    return np.sqrt(total)

def compute_di():
    cfg = di_config
    for wn, well in wells.items():
        pts = well.points; n = len(pts)
        if n < cfg["window"]:
            log_warn(f'DI "{wn}": {n} pts, mín={cfg["window"]}.'); continue
        try:
            di = di_profile(pts, cfg["window"], cfg["params"], cfg["weights"])
            if di is None: continue
            for i, p in enumerate(pts): p.di = float(di[i])
        except Exception as e:
            log_warn(f'DI "{wn}": {e}')

# ─── SENSIBILIDAD DE LA VENTANA DEL DI (T7) ────────────────────────────────────
DI_SENSITIVITY_WINDOWS = (10, 14, 20)

def _count_fused_peaks(largos, di_arr, threshold, min_gap_m=0.5):
    """
    (T7c) Cuenta picos DI > threshold sobre un array (largos, di) arbitrario
    —no ligado a p.di ni a Well—, fusionando eventos consecutivos separados
    menos de min_gap_m en un solo pico (mismo criterio de agrupación que
    di_peaks, T4b, pero aplicado a un perfil recalculado en memoria).
    """
    idx = [i for i in range(len(di_arr)) if di_arr[i] > threshold]
    if not idx: return 0
    count = 1
    last_l = largos[idx[0]]
    for i in idx[1:]:
        l = largos[i]
        if l - last_l >= min_gap_m: count += 1
        last_l = l
    return count

def di_sensitivity_analysis(well, windows=DI_SENSITIVITY_WINDOWS):
    """
    (T7b) Recalcula el DI de `well` con cada ventana de `windows` usando la
    función PURA di_profile (sin tocar p.di). Devuelve
    {"largos":[...], "profiles":{window: array|None}, "rows":[{ventana,
    n_picos, pct_sobre_umbral}, ...]} — insumo tanto del gráfico como de la
    tabla del análisis de sensibilidad del Paso 3.
    """
    pts = well.points
    largos = [p.largo for p in pts]
    profiles, rows = {}, []
    for w in windows:
        di = di_profile(pts, w, di_config["params"], di_config["weights"])
        profiles[w] = di
        if di is None:
            rows.append({"ventana": w, "n_picos": None, "pct_sobre_umbral": None})
            continue
        n_picos = _count_fused_peaks(largos, di, di_threshold)
        pct = 100.0 * float(np.sum(di > di_threshold)) / len(di)
        rows.append({"ventana": w, "n_picos": n_picos, "pct_sobre_umbral": round(pct, 1)})
    return {"largos": largos, "profiles": profiles, "rows": rows}

def build_di_sensitivity_figure(result):
    """(T7c) Perfiles DI superpuestos (uno por ventana) + línea de umbral."""
    fig = go.Figure()
    colors = {10: "#3B8BD4", 14: "#5DCAA5", 20: "#EF9F27"}
    largos = result["largos"]
    for w, di in result["profiles"].items():
        if di is None: continue
        fig.add_trace(go.Scatter(x=largos, y=di, mode="lines", name=f"ventana={w}",
                                 line=dict(color=colors.get(w, "#888"), width=1.3)))
    fig.add_hline(y=di_threshold, line_dash="dash", line_color="#E74C3C",
                 annotation_text=f"Umbral={di_threshold}")
    fig.update_layout(template="plotly_dark", paper_bgcolor="#0d0d1a", plot_bgcolor="#0d0d1a",
                      height=280, margin=dict(l=45, r=15, t=15, b=40),
                      xaxis_title="Profundidad [m]", yaxis_title="DI",
                      legend=dict(font=dict(size=10)))
    return fig

def build_di_sensitivity_content(well):
    """(T7c) Gráfico + tabla corta (n picos, % sobre umbral) por ventana."""
    result = di_sensitivity_analysis(well)
    fig = build_di_sensitivity_figure(result)
    table = dbc.Table([
        html.Thead(html.Tr([html.Th("Ventana"), html.Th("N picos"), html.Th("% sobre umbral")])),
        html.Tbody([html.Tr([
            html.Td(str(r["ventana"])),
            html.Td(str(r["n_picos"]) if r["n_picos"] is not None else "— (pozo corto)"),
            html.Td(f"{r['pct_sobre_umbral']}%" if r["pct_sobre_umbral"] is not None else "—"),
        ]) for r in result["rows"]]),
    ], bordered=False, size="sm", style={"fontSize":"11px", "color":"#ccc", "marginTop":"6px"})
    return html.Div([
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
        table,
    ])

def build_di_figure(well):
    """Perfil DI vs profundidad de un pozo, con línea de umbral."""
    pts = [p for p in well.points if p.di is not None]
    if not pts:
        return go.Figure()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[p.largo for p in pts], y=[p.di for p in pts],
        mode="lines", name="DI", line=dict(color="#5DCAA5", width=1.2),
    ))
    fig.add_hline(y=di_threshold, line_dash="dash", line_color="#E74C3C",
                 annotation_text=f"Umbral={di_threshold}")
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#0d0d1a", plot_bgcolor="#0d0d1a",
        height=300, margin=dict(l=45, r=15, t=30, b=40),
        title=f"Perfil DI — {well.well_name}",
        xaxis_title="Profundidad [m]", yaxis_title="DI",
    )
    return fig

# ─── VALIDACIÓN MULTIPOZO DE POSICIÓN DE MALLAS DXF (T4) ──────────────────────
# Un pico DI aislado en un pozo no prueba nada; la evidencia de que una malla
# está corrida es la CONSISTENCIA MULTIPOZO: si ≥3 pozos del mismo sector
# cruzan la misma estructura y sus picos DI apareados son coplanares entre sí
# pero sistemáticamente desplazados respecto de la malla, la malla es la
# sospechosa. Los primeros metros de cada tiro (emboquillado / daño por
# tronadura → picos DI falsos) se excluyen reutilizando p.entrenable.
VAL_MAX_OFFSET_M = 10.0   # descartar apareos cruce↔pico con |offset| mayor
VAL_MIN_WELLS = 3         # mínimo de pozos apareados para emitir veredicto

def well_mesh_crossings(well, layer):
    """
    (T4a) Profundidades (largo) donde el pozo ENTRA o SALE de la malla,
    detectadas como transiciones del estado dentro/fuera al aplicar
    points_in_mesh a los puntos del pozo en orden. La coordenada del cruce se
    interpola al punto medio entre el último punto de un estado y el primero
    del otro (muestreo MWD ~2 cm → error de interpolación despreciable).
    Devuelve [(largo_cruce, coord_utm(3,)), ...] con coord = [Este,Norte,Cota].
    """
    pts = well.points
    if len(pts) < 2: return []
    coords = np.array([[p.este, p.norte, p.cota] for p in pts], dtype=np.float64)
    valid = np.all(np.isfinite(coords), axis=1)
    if not valid.any(): return []
    inside = np.zeros(len(pts), dtype=bool)
    inside[valid] = points_in_mesh(coords[valid], layer)
    crossings = []
    for i in range(1, len(pts)):
        if not (valid[i] and valid[i-1]): continue
        if inside[i] != inside[i-1]:
            lc = 0.5 * (pts[i-1].largo + pts[i].largo)
            cc = 0.5 * (coords[i-1] + coords[i])
            crossings.append((float(lc), cc))
    return crossings

def di_peaks(well, min_gap_m=0.5):
    """
    (T4b) Profundidades de picos con DI > di_threshold. Picos separados menos
    de min_gap_m se fusionan en un solo evento (se toma el largo del máximo DI
    del grupo). Se ignoran los puntos con entrenable=False (excluye el
    emboquillado con el corte ya existente). Devuelve
    [(largo_pico, coord_utm(3,), di_max), ...].
    """
    cand = [(p.largo, np.array([p.este, p.norte, p.cota], dtype=np.float64), p.di)
            for p in well.points
            if p.entrenable and p.di is not None and np.isfinite(p.di)
            and p.di > di_threshold]
    if not cand: return []
    cand.sort(key=lambda c: c[0])
    grupos, grupo = [], [cand[0]]
    for c in cand[1:]:
        if c[0] - grupo[-1][0] < min_gap_m: grupo.append(c)
        else: grupos.append(grupo); grupo = [c]
    grupos.append(grupo)
    return [max(g, key=lambda c: c[2]) for g in grupos]

def _pair_crossings_peaks(well, layer, max_offset_m=VAL_MAX_OFFSET_M):
    """
    (T4c) Aparea cada cruce pozo↔malla con el pico DI más cercano del mismo
    pozo. Offset firmado = largo_pico − largo_cruce (positivo = el pico está
    MÁS PROFUNDO que la malla). Se descartan apareos con |offset| > max_offset_m.
    """
    crossings = well_mesh_crossings(well, layer)
    peaks = di_peaks(well)
    pares = []
    for lc, cc in crossings:
        if not peaks: break
        lp, cp, dv = min(peaks, key=lambda pk: abs(pk[0] - lc))
        off = lp - lc
        if abs(off) <= max_offset_m:
            pares.append({"pozo": well.well_name,
                          "largo_cruce": round(lc, 3), "largo_pico": round(lp, 3),
                          "offset": round(off, 3), "di_pico": round(float(dv), 3),
                          "cruce_pt": cc, "pico_pt": cp})
    return {"n_cruces": len(crossings), "pares": pares}

def _fit_plane_svd(points):
    """
    (T4d) Ajuste de plano por SVD: se centran los puntos y la normal del plano
    es el vector singular de MENOR valor singular. Devuelve (centroide,
    normal_unitaria, degenerado). Degenerado = puntos casi colineales (2º valor
    singular ~0), caso en que la normal es ambigua y no debe usarse.
    """
    P = np.asarray(points, dtype=np.float64)
    c = P.mean(axis=0)
    _, S, Vt = np.linalg.svd(P - c, full_matrices=False)
    n = Vt[-1]
    nrm = float(np.linalg.norm(n))
    if nrm == 0: return c, np.array([0.0, 0.0, 1.0]), True
    degen = len(P) < 3 or S[-2] < 1e-9 or (S[-2] / max(S[0], 1e-12)) < 1e-4
    return c, n / nrm, degen

def validate_mesh_positions(kinds=("estructura",), max_offset_m=VAL_MAX_OFFSET_M,
                            min_wells=VAL_MIN_WELLS, progress_cb=None):
    """
    (T4d/e) Validación multipozo de la posición de cada malla DXF de los tipos
    `kinds`. Por malla: cruces y picos por pozo, apareo cruce↔pico, y con ≥
    min_wells pozos apareados se calcula el offset medio ± std y un veredicto:
      · "consistente" si |offset medio| < 2·std  o  |offset medio| < 1.0 m
      · "posible desplazamiento de X m" en caso contrario.

    El offset PRIMARIO (veredicto) es a lo largo del pozo (largo_pico −
    largo_cruce), robusto siempre. Como métrica adicional (T4d) se ajusta un
    plano por SVD a los picos apareados y, si no es degenerado (picos no
    colineales), se reporta el offset NORMAL: distancia firmada de cada pico al
    plano medio de los cruces DXF a lo largo de la normal ajustada (la
    aproximación aceptada por la spec frente al triángulo-más-cercano, que es
    ambiguo en mallas rugosas). Si los picos son colineales (p.ej. pozos
    paralelos con picos a igual largo) la normal es ambigua y se omite.

    Pozos con posición ficticia (origin no_dq/ambiguous) se excluyen: su
    geometría no aporta evidencia de posición.
    """
    target = [(n, l) for n, l in layers.items() if l.kind in kinds]
    resultados = []
    total = max(len(target) * max(len(wells), 1), 1)
    done = 0
    for name, layer in target:
        pares_all = []
        pozos_cruzan, pozos_apareados = set(), set()
        for wn, well in wells.items():
            done += 1
            if progress_cb: progress_cb(done / total, f"{name} ↔ {wn}")
            if well.origin in ("no_dq", "ambiguous"):
                continue
            try:
                r = _pair_crossings_peaks(well, layer, max_offset_m)
            except Exception as e:
                log_warn(f'Validación "{name}" en "{wn}": {e}'); continue
            if r["n_cruces"]: pozos_cruzan.add(wn)
            if r["pares"]:
                pozos_apareados.add(wn)
                pares_all.extend(r["pares"])
        res = {"malla": name, "n_pozos_cruzan": len(pozos_cruzan),
               "n_pozos_apareados": len(pozos_apareados), "n_pares": len(pares_all),
               "offsets": [p["offset"] for p in pares_all],
               "offset_medio": None, "offset_std": None,
               "offset_normal_medio": None, "offset_normal_std": None,
               "veredicto": "sin datos", "detalle": pares_all}
        if len(pozos_apareados) >= min_wells:
            offs = np.array(res["offsets"], dtype=np.float64)
            om, osd = float(offs.mean()), float(offs.std())
            res["offset_medio"], res["offset_std"] = round(om, 3), round(osd, 3)
            # (T4d) plano SVD sobre los picos únicos (un pico puede aparearse a
            # dos cruces —entrada y salida—; para el plano cuenta una vez)
            uniq = {}
            for p in pares_all:
                uniq[(p["pozo"], p["largo_pico"])] = p["pico_pt"]
            ppts = list(uniq.values())
            if len(ppts) >= 3:
                _, npk, degen = _fit_plane_svd(ppts)
                if not degen:
                    c_ref = np.mean([p["cruce_pt"] for p in pares_all], axis=0)
                    # Orientar la normal hacia el avance del pozo, para que
                    # "positivo = más profundo" coincida con el offset por largo
                    adv = np.zeros(3)
                    for p in pares_all:
                        d = np.asarray(p["pico_pt"]) - np.asarray(p["cruce_pt"])
                        adv += d if p["offset"] >= 0 else -d
                    if float(np.dot(npk, adv)) < 0: npk = -npk
                    dn = [float(np.dot(np.asarray(v) - c_ref, npk)) for v in ppts]
                    res["offset_normal_medio"] = round(float(np.mean(dn)), 3)
                    res["offset_normal_std"] = round(float(np.std(dn)), 3)
            # (T4e) veredicto por consistencia
            if abs(om) < 2.0 * osd or abs(om) < 1.0:
                res["veredicto"] = "consistente"
            else:
                res["veredicto"] = f"posible desplazamiento de {om:+.1f} m"
        elif pares_all:
            res["veredicto"] = f"insuficiente (<{min_wells} pozos apareados)"
        resultados.append(res)
    return resultados

def run_validation_task():
    """Ejecuta validate_mesh_positions en hilo de fondo, reportando a val_task_state."""
    with task_lock:
        val_task_state.update(running=True, progress=0, stage="Iniciando…",
                              log=[], error=None, result=None, done=False)
    try:
        def cb(frac, msg):
            with task_lock:
                val_task_state["progress"] = int(5 + 90 * frac)
                val_task_state["stage"] = msg
        t0 = time.time()
        res = validate_mesh_positions(progress_cb=cb)
        mesh_validation_results.clear()
        mesh_validation_results.extend(res)
        n_desp = sum(1 for r in res if r["veredicto"].startswith("posible"))
        with task_lock:
            val_task_state.update(running=False, done=True, progress=100,
                                  stage="Completado",
                                  result={"n_mallas": len(res), "n_desplazadas": n_desp,
                                          "t": round(time.time() - t0, 1)})
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[VAL] ERROR: {e}\n{tb}")
        with task_lock:
            val_task_state.update(running=False, done=True, error=str(e), progress=100)

def export_validation_csv():
    """Detalle por pozo de la validación multipozo (para el botón de export)."""
    rows = []
    for r in mesh_validation_results:
        for p in r["detalle"]:
            rows.append({
                "malla": r["malla"], "pozo": p["pozo"],
                "largo_cruce_m": p["largo_cruce"], "largo_pico_m": p["largo_pico"],
                "offset_m": p["offset"], "di_pico": p["di_pico"],
                "este_pico": round(float(p["pico_pt"][0]), 3),
                "norte_pico": round(float(p["pico_pt"][1]), 3),
                "cota_pico": round(float(p["pico_pt"][2]), 3),
                "offset_medio_malla": r["offset_medio"],
                "offset_std_malla": r["offset_std"],
                "veredicto_malla": r["veredicto"],
            })
    return pd.DataFrame(rows)

# (P3-3.1) Guardia contra entrenamiento degenerado. Un R²=1,0 con una sola
# etiqueta distinta (o con clases de un puñado de muestras que el modelo
# memoriza) es síntoma de degeneración, no de éxito.
MIN_DISTINCT_LABELS = 2
MIN_SAMPLES_PER_LABEL = 5

def _degenerate_training_check(y: np.ndarray) -> Optional[str]:
    """None si el conjunto es entrenable; si no, el motivo del bloqueo."""
    if y.size == 0:
        return "sin puntos de entrenamiento."
    vals, counts = np.unique(y, return_counts=True)
    if vals.size < MIN_DISTINCT_LABELS:
        return (f"una sola etiqueta de UCS distinta en todo el conjunto "
                f"({vals[0]:g} MPa, n={counts[0]}). El modelo no tendría "
                f"variabilidad que aprender.")
    pocas = [(v, c) for v, c in zip(vals, counts) if c < MIN_SAMPLES_PER_LABEL]
    if pocas:
        detalle = " · ".join(f"{v:g} MPa: {c}" for v, c in pocas)
        return (f"{len(pocas)} etiqueta(s) de UCS con menos de "
                f"{MIN_SAMPLES_PER_LABEL} muestras cada una ({detalle}). "
                f"Reúne más puntos o excluye esas litologías.")
    return None


# (P3-3.2/3.8) Orden canónico del embudo de entrenamiento. Una sola función
# recorre los puntos UNA vez y produce X/y/groups Y el reporte de composición
# en el MISMO pase, con las MISMAS condiciones en el MISMO orden — así el
# reporte que ve el usuario no puede divergir en silencio de lo que el modelo
# realmente entrena. Incluye el corte de emboquillado (vía p.entrenable, que
# ya lo codifica), que antes se aplicaba sin figurar en ningún reporte.
TRAINING_FUNNEL_STAGES = [
    "total", "entrenable", "con_dominio", "sin_ambiguedad",
    "banda_ucs", "no_excluido", "rango_ucs", "roca_intacta",
]

def _training_funnel(ucs_min, ucs_max):
    """
    Devuelve (X, y, groups, n_excl_di, funnel). `funnel` es una lista de
    {"etapa","label","quedan","perdidos"} en el orden de TRAINING_FUNNEL_STAGES.
    """
    pts = list(all_points())
    labels = {
        "total": "Total de puntos MWD",
        "entrenable": f"Entrenable (emboquillado <{inicio_cut_m:g} m + filtros de limpieza)",
        "con_dominio": "Con dominio asignado (dentro de alguna malla)",
        "sin_ambiguedad": "Sin ambigüedad de traslape (A.5)",
        "banda_ucs": "Dominio con banda de UCS asignada",
        "no_excluido": "Atributo no excluido explícitamente (T1.5)",
        "rango_ucs": f"Etiqueta de UCS dentro de [{ucs_min:g}, {ucs_max:g}] MPa",
        "roca_intacta": f"DI ≤ umbral ({di_threshold:g}) — roca intacta",
    }
    X, y, groups = [], [], []
    n = {k: 0 for k in TRAINING_FUNNEL_STAGES}
    n["total"] = len(pts)
    for wn, well in wells.items():
        for p in well.points:
            if not p.entrenable: continue
            n["entrenable"] += 1
            if not p.dominio: continue
            n["con_dominio"] += 1
            # (P1-T1.4) Punto excluido por traslape irresoluble: ya
            # contabilizado en overlap_stats, no puede etiquetar nada.
            if getattr(p, "ambiguo", False): continue
            n["sin_ambiguedad"] += 1
            dom = domains.get(p.dominio)
            if not dom or dom.get("ucs_lab") is None: continue
            n["banda_ucs"] += 1
            # (P1-T1.5) Atributo excluido explícitamente por el usuario.
            if dom.get("atributo_id") in attribute_exclusions: continue
            n["no_excluido"] += 1
            ucs = dom["ucs_lab"]
            if ucs < ucs_min or ucs > ucs_max: continue
            n["rango_ucs"] += 1
            if p.di is not None and p.di > di_threshold: continue
            n["roca_intacta"] += 1
            X.append([getattr(p, k) for k in ML_FEATURES])
            y.append(ucs)
            groups.append(wn)
    funnel, prev = [], n["total"]
    for st in TRAINING_FUNNEL_STAGES:
        funnel.append({"etapa": st, "label": labels[st], "quedan": n[st],
                       "perdidos": prev - n[st]})
        prev = n[st]
    n_excl_di = n["rango_ucs"] - n["roca_intacta"]
    return (np.array(X, dtype=np.float64), np.array(y, dtype=np.float64),
            np.array(groups), n_excl_di, funnel)


def _get_train_data(ucs_min, ucs_max):
    """
    (T6a) Envoltorio de compatibilidad sobre _training_funnel: solo X/y/
    groups/n_excl. `groups` permite agrupar la validación cruzada por pozo
    (GroupKFold) y evitar que muestras vecinas del mismo tiro —a 2 cm entre
    sí y fuertemente autocorrelacionadas— terminen repartidas entre train y
    test, lo que infla artificialmente el R².
    """
    X, y, groups, n_excl, _ = _training_funnel(ucs_min, ucs_max)
    return X, y, groups, n_excl


def training_composition_report(ucs_min=None, ucs_max=None):
    """
    (P3-3.2) De dónde salen los datos de entrenamiento: total disponible,
    cuántos sobreviven cada filtro y por qué. Un entrenamiento con N=1.260
    sobre 12.000 puntos disponibles no puede aparecer sin esta explicación.
    """
    ucs_min = ucs_range["ucs_min"] if ucs_min is None else ucs_min
    ucs_max = ucs_range["ucs_max"] if ucs_max is None else ucs_max
    _, _, _, _, funnel = _training_funnel(ucs_min, ucs_max)
    return {"funnel": funnel,
            "n_total": funnel[0]["quedan"] if funnel else 0,
            "n_final": funnel[-1]["quedan"] if funnel else 0}

def train_rf(ucs_min=None, ucs_max=None):
    """
    (P1-T1.5) Antes de entrenar, verifica que ningún atributo presente en los
    datos quede sin banda de UCS y sin exclusión explícita. El bloqueo es
    ruidoso: nombra los atributos faltantes y cuánto representan.

    (P3-3.1) Después, verifica que el conjunto no sea degenerado: una sola
    etiqueta distinta de UCS, o clases con un puñado de muestras que el
    modelo memorizaría. Un R²=1,0 ahí es síntoma de degeneración, no de éxito.
    """
    global rf_model, rf_stats
    # `or` sería un default silencioso si llega 0.0 (un mínimo legítimo ahora
    # que el rango físico parte en 0): se distingue None explícitamente.
    ucs_min = ucs_range["ucs_min"] if ucs_min is None else ucs_min
    ucs_max = ucs_range["ucs_max"] if ucs_max is None else ucs_max
    bloqueo = training_block_message()
    if bloqueo:
        return {"error": bloqueo, "blockers": training_blockers()}
    X, y, groups, n_excl, funnel = _training_funnel(ucs_min, ucs_max)
    if len(X) < 10:
        return {"error": f"Insuficientes puntos ({len(X)} < 10).", "funnel": funnel}
    degenerado = _degenerate_training_check(y)
    if degenerado:
        return {"error": f"Entrenamiento degenerado: {degenerado}", "funnel": funnel}
    model = RandomForestRegressor(n_estimators=200, max_depth=8, min_samples_split=6,
                                    min_samples_leaf=3, max_features="sqrt", n_jobs=-1, random_state=42)
    model.fit(X, y)
    rf_model = model
    y_pred = model.predict(X)
    rmse_tr = float(np.sqrt(np.mean((y-y_pred)**2)))
    ss_tot = np.sum((y-y.mean())**2) or 1
    r2_tr = float(1 - np.sum((y-y_pred)**2)/ss_tot)
    rmsea = float(rmse_tr/np.sqrt(len(X)))
    # (T6b) CV AGRUPADA POR POZO (GroupKFold): las muestras MWD distan 2 cm
    # entre sí dentro de un mismo tiro y están fuertemente autocorrelacionadas;
    # un KFold aleatorio mezcla puntos del mismo pozo entre train y test y
    # produce fuga espacial que infla el R². GroupKFold garantiza que todo un
    # pozo cae entero en un solo lado del split. Con <3 pozos distintos no hay
    # forma de armar >=2 grupos de test razonables, así que se omite (n_grupos
    # < n_splits mínimo de 2 haría GroupKFold fallar igualmente).
    n_grupos = len(set(groups.tolist())) if groups.size else 0
    cv_scores = np.array([])
    cv_warning = None
    if n_grupos >= 3:
        k = min(5, n_grupos)
        try:
            gkf = GroupKFold(n_splits=k)
            cv_scores = cross_val_score(model, X, y, cv=gkf, groups=groups, scoring="r2")
        except Exception as e:
            cv_warning = f"CV agrupada falló: {e}"
    else:
        cv_warning = (f"CV agrupada requiere ≥3 pozos con etiqueta (hay {n_grupos}).")
    n_tr = int(len(X)*0.7); rmse_te = None
    if n_tr >= 5 and len(X)-n_tr >= 3:
        m2 = RandomForestRegressor(n_estimators=100, max_depth=8, n_jobs=-1, random_state=0)
        m2.fit(X[:n_tr], y[:n_tr])
        rmse_te = float(np.sqrt(np.mean((y[n_tr:] - m2.predict(X[n_tr:]))**2)))
    feat_imp = {}
    try:
        n_samp = min(len(X), 300)
        idx = np.random.choice(len(X), n_samp, replace=False)
        perm = permutation_importance(model, X[idx], y[idx], n_repeats=10, random_state=42, n_jobs=-1)
        feat_imp = {ML_LABELS[i]: round(float(perm.importances_mean[i]), 4) for i in range(len(ML_FEATURES))}
    except: pass
    stats = {
        "n_train": len(X), "n_excl_disc": n_excl, "funnel": funnel,
        # (A.6) El contador de ambiguos por Conflicto de traslape es parte del
        # reporte de composición del entrenamiento: sin él, los puntos que las
        # reglas descartaron desaparecerían de la vista.
        "n_excl_ambiguo": overlap_stats.get("n_ambiguos", 0),
        "n_compuestos": overlap_stats.get("n_compuestos", 0),
        "n_anidamiento": overlap_stats.get("n_subunidad_gana", 0),
        "overlap_motivos": dict(overlap_stats.get("motivos", {})),
        "r2_train": round(r2_tr, 3), "rmse_train": round(rmse_tr, 1),
        "rmsea": round(rmsea, 4),
        "cv_r2_mean": round(float(cv_scores.mean()), 3) if cv_scores.size else None,
        "cv_r2_std": round(float(cv_scores.std()), 3) if cv_scores.size else None,
        "cv_n_grupos": n_grupos, "cv_warning": cv_warning,
        "rmse_test": round(rmse_te, 1) if rmse_te else None,
        "overfit": round(rmse_te-rmse_tr, 1) if rmse_te else None,
        "feat_imp": feat_imp,
    }
    rf_stats = stats
    return stats

# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  P3-3.9 — ARMAZÓN DEL REPORTE DE JUSTIFICACIÓN DE VARIABLES             ║
# ║                                                                          ║
# ║  Cada función calcula sobre los datos vigentes y devuelve un resultado  ║
# ║  REAL en cuanto hay datos suficientes. Donde no los hay (p.ej. un solo  ║
# ║  caserón etiquetado para LOCO-CV), lo declara explícitamente — nunca    ║
# ║  inventa un número. Es el mismo principio que el resto del proyecto:    ║
# ║  nunca un default silencioso.                                          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

MULTICOLLINEARITY_THRESHOLD = 0.85
# Lineal/KNN/RF/HistGB son candidatos; MLP entra como CONTROL de complejidad
# (referencia de cuánto puede sobreajustar un modelo no lineal denso), no
# como candidato de producción.
COMPARISON_MODELS = ["Lineal", "KNN", "Random Forest", "HistGradientBoosting", "MLP (control)"]


def correlation_matrix_report(ucs_min=None, ucs_max=None):
    """
    Matriz de correlación de Pearson entre predictores (ML_FEATURES) sobre el
    conjunto de entrenamiento vigente, con detección de multicolinealidad
    (|r| > MULTICOLLINEARITY_THRESHOLD). Ante un par colineal, SUGIERE cuál
    quitar (el de menor correlación con la etiqueta UCS, se conserva el más
    predictivo) pero mantiene AMBAS variables por defecto: la exclusión es
    una decisión manual del usuario, no automática.
    """
    ucs_min = ucs_range["ucs_min"] if ucs_min is None else ucs_min
    ucs_max = ucs_range["ucs_max"] if ucs_max is None else ucs_max
    X, y, groups, _ = _get_train_data(ucs_min, ucs_max)
    if len(X) < 10:
        return {"status": "sin_datos",
                "motivo": f"Insuficientes puntos de entrenamiento ({len(X)} < 10)."}
    with np.errstate(invalid="ignore"):
        corr = np.corrcoef(X, rowvar=False)
        corr_y = np.array([np.corrcoef(X[:, i], y)[0, 1] for i in range(X.shape[1])])
    pairs = []
    for i in range(len(ML_FEATURES)):
        for j in range(i + 1, len(ML_FEATURES)):
            r = corr[i, j]
            if not np.isfinite(r) or abs(r) < MULTICOLLINEARITY_THRESHOLD: continue
            peor = ML_LABELS[i] if abs(corr_y[i]) < abs(corr_y[j]) else ML_LABELS[j]
            pairs.append({"a": ML_LABELS[i], "b": ML_LABELS[j], "r": round(float(r), 3),
                         "sugerencia_quitar": peor})
    return {"status": "ok", "n_samples": len(X), "features": ML_LABELS,
            "matrix": corr.tolist(), "corr_con_y": corr_y.tolist(),
            "pairs_flagged": pairs, "threshold": MULTICOLLINEARITY_THRESHOLD}


def _make_comparison_model(name):
    if name == "Lineal":
        return make_pipeline(StandardScaler(), LinearRegression())
    if name == "KNN":
        return make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=7))
    if name == "Random Forest":
        return RandomForestRegressor(n_estimators=200, max_depth=8, min_samples_split=6,
                                     min_samples_leaf=3, max_features="sqrt", n_jobs=-1,
                                     random_state=42)
    if name == "HistGradientBoosting":
        return HistGradientBoostingRegressor(max_depth=6, random_state=42)
    if name == "MLP (control)":
        return make_pipeline(StandardScaler(),
                             MLPRegressor(hidden_layer_sizes=(32, 16), max_iter=2000,
                                          random_state=42, early_stopping=True))
    raise ValueError(f"Modelo desconocido: {name}")


def model_comparison_report(with_se=True, ucs_min=None, ucs_max=None):
    """
    Compara Lineal, KNN, Random Forest, HistGradientBoosting y MLP (control)
    con la MISMA validación cruzada agrupada por pozo (GroupKFold) que usa
    train_rf, para que la comparación sea metodológicamente consistente con
    el modelo de producción. `with_se` decide si el proxy de energía
    específica de reacción entra como predictor.
    """
    ucs_min = ucs_range["ucs_min"] if ucs_min is None else ucs_min
    ucs_max = ucs_range["ucs_max"] if ucs_max is None else ucs_max
    X_full, y, groups, _ = _get_train_data(ucs_min, ucs_max)
    if len(X_full) < 10:
        return {"status": "sin_datos",
                "motivo": f"Insuficientes puntos de entrenamiento ({len(X_full)} < 10)."}
    feat_idx = list(range(len(ML_FEATURES))) if with_se else \
               [i for i, f in enumerate(ML_FEATURES) if f != "se"]
    X = X_full[:, feat_idx]
    n_grupos = len(set(groups.tolist())) if groups.size else 0
    if n_grupos < 3:
        return {"status": "sin_grupos",
                "motivo": f"CV agrupada por pozo requiere ≥3 pozos con etiqueta (hay {n_grupos})."}
    k = min(5, n_grupos)
    gkf = GroupKFold(n_splits=k)
    rows = []
    for name in COMPARISON_MODELS:
        try:
            model = _make_comparison_model(name)
            r2 = cross_val_score(model, X, y, cv=gkf, groups=groups, scoring="r2")
            rmse = -cross_val_score(model, X, y, cv=gkf, groups=groups,
                                    scoring="neg_root_mean_squared_error")
            rows.append({"modelo": name, "r2_mean": round(float(r2.mean()), 3),
                        "r2_std": round(float(r2.std()), 3),
                        "rmse_mean": round(float(rmse.mean()), 1),
                        "rmse_std": round(float(rmse.std()), 1), "error": None})
        except Exception as e:
            rows.append({"modelo": name, "r2_mean": None, "r2_std": None,
                        "rmse_mean": None, "rmse_std": None, "error": str(e)})
    return {"status": "ok", "with_se": with_se, "n_samples": len(X),
            "n_grupos": n_grupos, "k_splits": k, "rows": rows}


def caseron_de_pozo(well) -> Optional[str]:
    """
    Caserón al que pertenece un pozo.

    El caserón de un punto lo define su POZO —el abanico perforado—, no la
    litología que lo contiene: una litología cruza varios caserones por
    definición (en los datos reales de MPC, Bht está en los tres cargados),
    así que resolver el caserón desde la litología devuelve None por
    ambigüedad. Un pozo, en cambio, pertenece a exactamente uno.

    Prioridad: el caserón DECLARADO en el pozo; si no lo tiene, se deriva
    del prefijo del plan_id ("PCS_1043_PR01_TH_P07" -> "PCS_1043"), que es
    la convención de nomenclatura de Pucobre. La derivación es una
    heurística sobre el nombre, así que solo se usa cuando no hay dato
    explícito, y nunca sobrescribe uno.
    """
    c = getattr(well, "caseron", None)
    if c: return c
    pid = getattr(well, "plan_id", "") or ""
    m = re.match(r"^([A-Za-z]+_\d+)", pid)
    return m.group(1) if m else None


def _point_caseron_map(pts_por_pozo):
    """
    {id(punto): caserón|None} a partir del POZO de cada punto.

    `pts_por_pozo` es un iterable de (punto, nombre_de_pozo).
    """
    cache, out = {}, {}
    for p, wn in pts_por_pozo:
        if wn not in cache:
            cache[wn] = caseron_de_pozo(wells.get(wn)) if wn in wells else None
        out[id(p)] = cache[wn]
    return out


def cota_ablation_report(ucs_min=None, ucs_max=None):
    """
    Ablación EXPLÍCITA de la cota como predictor — nunca en el modelo de
    producción (train_rf/ML_FEATURES), prohibido por diseño porque el
    yacimiento es estratiforme y la cota es casi un proxy directo de la
    litología. Compara desempeño DENTRO-DEL-CASERÓN (GroupKFold por pozo,
    igual que siempre) contra LOCO-CV (dejando un caserón completo fuera),
    con y sin cota. Si "con cota" degrada mucho más en LOCO-CV que "sin
    cota", es evidencia de que el modelo memorizaba la posición en vez de
    leer el MWD — la razón de la prohibición.

    Requiere ≥2 caserones distintos con puntos etiquetados; si no los hay, lo
    declara en vez de fingir un resultado.
    """
    ucs_min = ucs_range["ucs_min"] if ucs_min is None else ucs_min
    ucs_max = ucs_range["ucs_max"] if ucs_max is None else ucs_max
    candidatos = []
    for wn, well in wells.items():
        for p in well.points:
            if not p.entrenable or not p.dominio: continue
            if getattr(p, "ambiguo", False): continue
            dom = domains.get(p.dominio)
            if not dom or dom.get("ucs_lab") is None: continue
            if dom.get("atributo_id") in attribute_exclusions: continue
            ucs = dom["ucs_lab"]
            if ucs < ucs_min or ucs > ucs_max: continue
            if p.di is not None and p.di > di_threshold: continue
            candidatos.append((p, wn, ucs))
    if len(candidatos) < 10:
        return {"status": "sin_datos",
                "motivo": f"Insuficientes puntos de entrenamiento ({len(candidatos)} < 10)."}
    caseron_map = _point_caseron_map([(c[0], c[1]) for c in candidatos])
    caserones = sorted({c for c in caseron_map.values() if c})
    if len(caserones) < 2:
        return {"status": "sin_caserones",
                "motivo": ("LOCO-CV (dejando-un-caserón-fuera) requiere ≥2 caserones "
                          f"distintos con puntos etiquetados; hay {len(caserones)}"
                          + (f" ({caserones[0]})" if caserones else "") + ". Esta ablación "
                          "queda lista para correr en cuanto haya un segundo caserón con "
                          "datos etiquetados.")}
    X_rows, y, groups_pozo, caseron_groups = [], [], [], []
    for p, wn, ucs in candidatos:
        c = caseron_map[id(p)]
        if not c: continue
        X_rows.append([getattr(p, k) for k in ML_FEATURES] + [p.cota])
        y.append(ucs); groups_pozo.append(wn); caseron_groups.append(c)
    X = np.array(X_rows, dtype=np.float64); y = np.array(y, dtype=np.float64)
    groups_pozo = np.array(groups_pozo); caseron_groups = np.array(caseron_groups)
    idx_sin_cota = list(range(len(ML_FEATURES)))
    idx_con_cota = list(range(len(ML_FEATURES) + 1))

    def _cv(X_sub, groups_arr, splitter):
        model = RandomForestRegressor(n_estimators=150, max_depth=8, n_jobs=-1, random_state=42)
        try:
            scores = cross_val_score(model, X_sub, y, cv=splitter, groups=groups_arr, scoring="r2")
            return round(float(scores.mean()), 3), None
        except Exception as e:
            return None, str(e)

    n_grupos_pozo = len(set(groups_pozo.tolist()))
    resultado = {"status": "ok", "n_samples": len(X), "caserones": caserones,
                "n_grupos_pozo": n_grupos_pozo}
    if n_grupos_pozo >= 3:
        gkf = GroupKFold(n_splits=min(5, n_grupos_pozo))
        resultado["dentro_caseron_sin_cota"] = _cv(X[:, idx_sin_cota], groups_pozo, gkf)
        resultado["dentro_caseron_con_cota"] = _cv(X[:, idx_con_cota], groups_pozo, gkf)
    else:
        motivo = f"requiere ≥3 pozos con etiqueta (hay {n_grupos_pozo})"
        resultado["dentro_caseron_sin_cota"] = (None, motivo)
        resultado["dentro_caseron_con_cota"] = (None, motivo)
    logo = LeaveOneGroupOut()
    resultado["loco_sin_cota"] = _cv(X[:, idx_sin_cota], caseron_groups, logo)
    resultado["loco_con_cota"] = _cv(X[:, idx_con_cota], caseron_groups, logo)

    r2_dc, _ = resultado["dentro_caseron_con_cota"]
    r2_lc, _ = resultado["loco_con_cota"]
    r2_ds, _ = resultado["dentro_caseron_sin_cota"]
    r2_ls, _ = resultado["loco_sin_cota"]
    if None not in (r2_dc, r2_lc, r2_ds, r2_ls):
        resultado["memorizacion_espacial_sospechosa"] = bool((r2_dc - r2_lc) > (r2_ds - r2_ls) + 0.1)
    else:
        resultado["memorizacion_espacial_sospechosa"] = None
    return resultado


def variable_justification_report():
    """Orquesta las cuatro secciones del reporte (P3-3.9) en una sola llamada."""
    return {
        "correlacion": correlation_matrix_report(),
        "importancia": (rf_stats or {}).get("feat_imp"),
        "comparacion_con_se": model_comparison_report(with_se=True),
        "comparacion_sin_se": model_comparison_report(with_se=False),
        "ablacion_cota": cota_ablation_report(),
    }


def predict_all_wells():
    if rf_model is None: return
    pts = list(all_points())
    if not pts: return
    X = np.array([[getattr(p, k) for k in ML_FEATURES] for p in pts], dtype=np.float64)
    # Intervalo de predicción a partir de los árboles individuales del RF:
    # matriz (n_arboles, n_puntos) y percentiles por columna (VECTORIZADO, sin
    # loop por punto). ucs_ml pasa a ser la MEDIANA de los árboles (p50).
    all_tree = np.stack([est.predict(X) for est in rf_model.estimators_])  # (T, N)
    p10 = np.percentile(all_tree, 10, axis=0)
    p50 = np.percentile(all_tree, 50, axis=0)
    p90 = np.percentile(all_tree, 90, axis=0)
    # (P1-T1.2) El ancho del intervalo se ensancha según la CALIDAD del ancla de
    # UCS del dominio: un ensayo del sitio con una sola probeta y un análogo de
    # otra mina no pueden producir la misma confianza. El factor se aplica
    # alrededor de la mediana; el resultado se acota al rango físico sin
    # truncamiento silencioso (el recorte se reporta en parse_warnings).
    lo_f, hi_f = UCS_CONFIG["physical_min"], UCS_CONFIG["physical_max"]
    n_recortados = 0
    for i, p in enumerate(pts):
        med = float(p50[i]); lo = float(p10[i]); hi = float(p90[i])
        dom = domains.get(p.dominio) if p.dominio else None
        f = (dom or {}).get("pi_factor")
        if f and f > 1.0:
            lo = med - (med - lo) * f
            hi = med + (hi - med) * f
        lo_c, hi_c = max(lo_f, lo), min(hi_f, hi)
        if lo_c != lo or hi_c != hi: n_recortados += 1
        p.ucs_ml     = round(med, 1)
        p.ucs_ml_p10 = round(lo_c, 1)
        p.ucs_ml_p90 = round(hi_c, 1)
        p.ucs_ml_prelim = False
    if n_recortados:
        log_warn(f"Intervalo de predicción: {n_recortados} punto(s) con extremos "
                 f"acotados al rango físico [{lo_f:g}, {hi_f:g}] MPa tras el "
                 f"ensanche por calidad del ancla.")
    # (P3-3.4) "UCS matriz": arrastra el último ucs_ml estable en los tramos
    # con discontinuidad (DI > umbral). No es una medida de confianza.
    for well in wells.values():
        last_stable = None
        for p in well.points:
            is_drop = p.di is not None and p.di > di_threshold
            if not is_drop:
                last_stable = p.ucs_ml
                p.ucs_matriz = p.ucs_ml
            else:
                p.ucs_matriz = last_stable
    # Verificación de consistencia banda↔intervalo (si hay bandas cargadas).
    band_consistency()

# ─── VERIFICACIÓN DE BANDA (consistencia laboratorio ↔ intervalo ML) (T3) ─────
def _resolve_caseron(lito):
    """
    Resuelve el caserón de una litología a partir de la Layer DXF que la
    representa (por nombre o lito_alias). Si varias capas comparten esa
    litología con distinto caserón, es ambiguo y se devuelve None.
    """
    if not lito: return None
    idents = lito_identities(lito)
    caserones = set()
    for layer in layers.values():
        if not layer.caseron: continue
        # La capa denota esa litología por su alias de Excel, por su nombre, o
        # por el atributo canónico que tenga asignado (que es lo que ahora
        # lleva p.lito).
        lay_idents = {_norm_txt(layer.lito_alias or ""), _norm_txt(layer.name)}
        canon = layer_role_ids(layer).get("litologia")
        if canon: lay_idents |= lito_identities(canon)
        if idents & {t for t in lay_idents if t}:
            caserones.add(layer.caseron)
    if len(caserones) == 1:
        return next(iter(caserones))
    return None  # 0 → sin caserón asignado; ≥2 → ambiguo, no resoluble

def band_consistency():
    """
    Para cada punto con litología (DXF o inferida) y caserón resoluble, compara
    su intervalo [p10, p90] contra la banda [ucs_lo, ucs_hi] de laboratorio de
    esa caserón×litología. Guarda p.band_check ∈ {compatible, incompatible,
    ambiguo} o None si no evaluable. No lanza excepciones por punto.
    """
    if not geomech_bands["records"]:
        for p in all_points(): p.band_check = None
        return
    for p in all_points():
        p.band_check = None
        try:
            lito = p.lito or p.lito_inferida
            if not lito or p.ucs_ml is None:
                continue
            caseron = _resolve_caseron(lito)
            band = lookup_band(caseron, lito)
            if band is None or band.get("ucs_lo") is None or band.get("ucs_hi") is None:
                continue
            lo, hi = band["ucs_lo"], band["ucs_hi"]
            med = p.ucs_ml
            p10 = p.ucs_ml_p10 if p.ucs_ml_p10 is not None else med
            p90 = p.ucs_ml_p90 if p.ucs_ml_p90 is not None else med
            intersecta = not (p90 < lo or p10 > hi)
            dentro = lo <= med <= hi
            # ¿La mediana cae en ≥2 bandas de litologías del mismo caserón?
            n_contienen = sum(1 for b in bands_for_caseron(caseron)
                              if b.get("ucs_lo") is not None and b.get("ucs_hi") is not None
                              and b["ucs_lo"] <= med <= b["ucs_hi"])
            if not intersecta:
                p.band_check = "incompatible"
            elif dentro and n_contienen < 2:
                p.band_check = "compatible"
            else:
                p.band_check = "ambiguo"
        except Exception:
            p.band_check = None

# ─── VALIDACIÓN INDEPENDIENTE DI ↔ RQD (T5) ────────────────────────────────────
# El RQD del Excel geomecánico proviene de mapeo/sondajes: es INDEPENDIENTE del
# MWD. Hipótesis: el DI medio por caserón anticorrelaciona con el RQD (más
# discontinuidades detectadas por MWD → roca más fracturada → menor RQD). Es la
# única validación externa del DI disponible en la mina.
DI_RQD_MIN_PUNTOS = 100

def di_vs_rqd_by_caseron(min_puntos=DI_RQD_MIN_PUNTOS):
    """
    (T5a) DI medio por caserón vs su RQD de laboratorio. Un caserón es
    evaluable si tiene al menos una Layer DXF con ese caserón asignado cuya
    banda caserón×litología incluya RQD (rqd_mid), y el conjunto de puntos MWD
    dentro de esas mallas (excluyendo entrenable=False, es decir el
    emboquillado) suma >= min_puntos.

    Si un caserón tiene MÁS DE UNA Layer asignada (varias litologías dentro
    del mismo caserón), se agrupan los puntos de todas ellas y el rqd_mid
    reportado es el promedio de las bandas de esas litologías ponderado por
    su cantidad de puntos (cada banda del Excel es en rigor caserón×litología,
    no puramente caserón; esta agregación es la aproximación al nivel caserón
    que pide la tarea).

    Devuelve lista de {caseron, di_medio, di_std, rqd_mid, n_puntos}.
    """
    by_cas = {}
    for layer in layers.values():
        if not layer.caseron: continue
        lito = layer.lito_alias or layer.name
        band = lookup_band(layer.caseron, lito)
        if band is None or band.get("rqd_mid") is None: continue
        by_cas.setdefault(layer.caseron, []).append((layer, band))

    resultados = []
    for caseron, layer_bands in by_cas.items():
        di_vals = []
        rqd_weighted_sum, n_total = 0.0, 0
        for layer, band in layer_bands:
            pts = [p for p in all_points()
                   if p.lito == layer.name and p.entrenable
                   and p.di is not None and np.isfinite(p.di)]
            if not pts: continue
            di_vals.extend(p.di for p in pts)
            rqd_weighted_sum += band["rqd_mid"] * len(pts)
            n_total += len(pts)
        if n_total < min_puntos: continue
        di_arr = np.array(di_vals, dtype=np.float64)
        resultados.append({
            "caseron": caseron,
            "di_medio": round(float(di_arr.mean()), 4),
            "di_std": round(float(di_arr.std()), 4),
            "rqd_mid": round(rqd_weighted_sum / n_total, 2),
            "n_puntos": n_total,
        })
    return sorted(resultados, key=lambda r: r["caseron"])

def spearman_rho(x, y):
    """
    (T5b) Correlación de Spearman implementada a mano con numpy (sin scipy,
    fuera de las dependencias permitidas): se rankea cada serie con
    argsort(argsort(·)) — equivalente a rankdata SIN manejo especial de
    empates (a diferencia de scipy.stats.rankdata, no promedia el rango de
    valores repetidos; cada elemento recibe un rango distinto según el orden
    estable de np.argsort) — y se aplica la correlación de Pearson sobre los
    rangos, que es la definición misma de Spearman. El offset de rango
    0-index vs 1-index no afecta el resultado: Pearson es invariante a
    desplazamientos constantes. Aceptable para las muestras pequeñas de
    caserones de este análisis, donde empates exactos de DI son improbables.
    Devuelve None si n<2 (con este método de rankeo, el vector de rangos es
    siempre una permutación 0..n-1 de varianza no nula para n>=2, incluso si
    los VALORES originales son constantes — el guard de varianza nula queda
    como defensa adicional, no se espera que dispare para n>=2).
    """
    x = np.asarray(x, dtype=np.float64); y = np.asarray(y, dtype=np.float64)
    n = len(x)
    if n < 2 or len(y) != n: return None
    rx = np.argsort(np.argsort(x)).astype(np.float64)
    ry = np.argsort(np.argsort(y)).astype(np.float64)
    rx -= rx.mean(); ry -= ry.mean()
    denom = np.sqrt(np.sum(rx**2) * np.sum(ry**2))
    if denom == 0: return None
    return float(np.sum(rx * ry) / denom)

def di_rqd_correlation(min_puntos=DI_RQD_MIN_PUNTOS):
    """
    (T5b) rho de Spearman entre di_medio y rqd_mid sobre los caserones
    evaluables de di_vs_rqd_by_caseron(). Con menos de 4 caserones se considera
    insuficiente para una correlación confiable: se omite rho (None) y se
    devuelve la advertencia. Devuelve {rho, n, data, warning}.
    """
    data = di_vs_rqd_by_caseron(min_puntos)
    n = len(data)
    if n < 4:
        return {"rho": None, "n": n, "data": data,
                "warning": "insuficientes caserones para correlación confiable"}
    rho = spearman_rho([d["di_medio"] for d in data], [d["rqd_mid"] for d in data])
    return {"rho": rho, "n": n, "data": data, "warning": None}

def build_di_rqd_figure(data):
    """(T5c) Scatter DI medio vs RQD por caserón; tamaño del marcador ~ n_puntos."""
    fig = go.Figure()
    if not data: return fig
    xs = [d["rqd_mid"] for d in data]
    ys = [d["di_medio"] for d in data]
    texts = [d["caseron"] for d in data]
    max_n = max(d["n_puntos"] for d in data) or 1
    sizes = [8 + 22 * (d["n_puntos"] / max_n) for d in data]
    hover = [f"{d['caseron']}<br>DI medio={d['di_medio']:.3f} ± {d['di_std']:.3f}"
             f"<br>RQD={d['rqd_mid']:.1f}<br>n={d['n_puntos']}" for d in data]
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers+text", text=texts, textposition="top center",
        textfont=dict(size=9, color="#aaa"),
        marker=dict(size=sizes, color="#3B8BD4", opacity=0.75,
                    line=dict(width=1, color="#0d0d1a")),
        hovertext=hover, hoverinfo="text",
    ))
    fig.update_layout(template="plotly_dark", paper_bgcolor="#0d0d1a", plot_bgcolor="#0d0d1a",
                      height=280, margin=dict(l=45, r=15, t=15, b=40),
                      xaxis_title="RQD medio [%]", yaxis_title="DI medio")
    return fig

def export_di_rqd_csv():
    return pd.DataFrame(di_vs_rqd_by_caseron())

def run_cross_ml(ucs_min=None, ucs_max=None):
    classify_all_wells_cached()
    build_domain_index()
    stats = train_rf(ucs_min, ucs_max)
    if "error" not in stats:
        predict_all_wells()
        wz_state['step4']['model_trained'] = True
    return stats

def train_prelim_from_excel():
    global prelim_model
    X, y = [], []
    for ex in excel_data:
        ucs = ex.get("ucs_excel")
        if ucs is None or not np.isfinite(ucs): continue
        vel,pp,pr,pa,pd,pf = [ex.get(k) for k in ("vel","pp","pr","pa","pd","pf")]
        if any(v is None or not np.isfinite(v) for v in (vel,pp,pr,pa,pd,pf)): continue
        se = (pp+pr+pa)/(vel+EPS)
        X.append([vel,pp,pa,pd,pr,pf,se]); y.append(ucs)
    if len(X) < 5: return {"error": f"Solo {len(X)} tiros válidos"}
    X, y = np.array(X), np.array(y)
    m = RandomForestRegressor(n_estimators=100, max_depth=6, n_jobs=-1, random_state=42)
    m.fit(X, y); prelim_model = m
    preds = m.predict(X)
    rmse = float(np.sqrt(np.mean((y-preds)**2)))
    r2 = float(1-np.sum((y-preds)**2)/(np.sum((y-y.mean())**2) or 1))
    pts = list(all_points())
    if pts:
        Xall = np.array([[getattr(p,k) for k in ML_FEATURES] for p in pts])
        pall = m.predict(Xall)
        for p, v in zip(pts, pall):
            p.ucs_ml = round(float(v),1); p.ucs_ml_prelim = True
    return {"n_train": len(X), "r2": round(r2,3), "rmse": round(rmse,1)}

def recompute_filters(cut_m=None):
    """
    Resetea 'entrenable' de todos los puntos y reaplica: corte de emboquillado
    + todos los filtros de clean_filters vigentes (en orden). Se usa al borrar
    un filtro individual, ya que los filtros son acumulativos y no se puede
    simplemente "des-marcar" un punto sin saber si otro filtro también lo
    excluía.

    (P3-3.8) `cut_m=None` reaplica el corte VIGENTE (`inicio_cut_m`), no un
    default hardcodeado: antes, borrar un filtro de limpieza reseteaba en
    silencio el corte de emboquillado del usuario a 2.0 m.
    """
    cut_m = inicio_cut_m if cut_m is None else cut_m
    for p in all_points():
        p.entrenable = True
        p.norm_excluded = False
    apply_inicio_filter(cut_m)
    filters_copy = list(clean_filters)
    clean_filters.clear()
    for f in filters_copy:
        add_norm_filter(f["varName"], f["method"])

def remove_filter(idx):
    """Elimina el filtro en la posición idx y recalcula entrenable desde cero."""
    if 0 <= idx < len(clean_filters):
        clean_filters.pop(idx)
        recompute_filters()
        return True
    return False

def _split_dominio(d):
    """(litología, estructura). La alteración compuesta ('lito~alt') se recorta."""
    if not d or d == "(sin dominio)": return None, None
    parts = d.split("::")
    lito, est = (parts[0], parts[1]) if len(parts) == 2 else (parts[0], None)
    if lito: lito = lito.split("~")[0]
    return (lito or None), (est or None)

def compute_domain_groups(tol_ucs=20.0, tol_di=0.15, interval_m=2.0):
    domain_groups.clear()
    intervals = []
    for wn, well in wells.items():
        try:
            gr = {}
            for p in well.points:
                if not p.entrenable or not p.dominio or p.ucs_ml is None: continue
                if p.di is None or not np.isfinite(p.di): continue
                gr.setdefault(int(p.largo//interval_m), []).append(p)
            for grp in gr.values():
                cnt = {}
                for p in grp: cnt[p.dominio] = cnt.get(p.dominio, 0) + 1
                dom_key = max(cnt, key=cnt.get)
                lito, est = _split_dominio(dom_key)
                if not lito and not est: continue
                intervals.append({
                    "lito":lito,"estructura":est,
                    "ucsMean":float(np.mean([p.ucs_ml for p in grp])),
                    "diMean":float(np.mean([p.di for p in grp])),
                    "pts":grp
                })
        except Exception as e: log_warn(f'Agrup "{wn}": {e}')
    for iv in intervals:
        found = next((g for g in domain_groups
                     if g["lito"]==iv["lito"] and g["estructura"]==iv["estructura"]
                     and abs(g["ucsMean"]-iv["ucsMean"])<=tol_ucs
                     and abs(g["diMean"]-iv["diMean"])<=tol_di), None)
        if found:
            n = found["n"]
            found["ucsMean"] = (found["ucsMean"]*n + iv["ucsMean"])/(n+1)
            found["diMean"] = (found["diMean"]*n + iv["diMean"])/(n+1)
            found["n"] += 1; found["count"] += len(iv["pts"])
            for p in iv["pts"]: p.grupo = found["id"]
            found["pts"].extend(iv["pts"])
        else:
            gid = f"G{len(domain_groups)+1}"
            g = {"id":gid,"lito":iv["lito"],"estructura":iv["estructura"],
                 "ucsMean":iv["ucsMean"],"diMean":iv["diMean"],
                 "n":1,"count":len(iv["pts"]),"pts":list(iv["pts"])}
            for p in iv["pts"]: p.grupo = gid
            domain_groups.append(g)
    wz_state['step5']['grouped'] = True
    return len(domain_groups)

def predict_unclassified(tol_ucs=20.0, tol_di=0.15, interval_m=2.0):
    if not domain_groups: return {"assigned":0,"total":0,"no_model":0}
    assigned = total = no_model = 0
    for well in wells.values():
        gr = {}
        for p in well.points:
            if p.dominio: continue
            total += 1
            if not p.entrenable or p.di is None or not np.isfinite(p.di): continue
            if p.ucs_ml is None: no_model += 1; continue
            gr.setdefault(int(p.largo//interval_m), []).append(p)
        for grp in gr.values():
            um = float(np.mean([p.ucs_ml for p in grp]))
            dm = float(np.mean([p.di for p in grp]))
            best, best_d = None, float("inf")
            for g in domain_groups:
                d = ((um-g["ucsMean"])/(tol_ucs or 1))**2 + ((dm-g["diMean"])/(tol_di or 1))**2
                if d < best_d: best_d, best = d, g
            if best:
                for p in grp:
                    p.grupo = best["id"]; p.lito_inferida = best["lito"]
                    p.estructura_inferida = best["estructura"]
                    p.grupo_confianza = float(1/(1+best_d**0.5))
                    assigned += 1
    wz_state['step5']['predicted'] = True
    # Reevaluar consistencia de banda incluyendo litologías inferidas.
    band_consistency()
    return {"assigned":assigned,"total":total,"no_model":no_model}

def _segments_by_domain(group_id, min_len=5):
    """
    Reconstruye segmentos continuos (mismo dominio, sin cortes de entrenable
    ni caídas DI) dentro de un dominio, atravesando todos los pozos. Cada
    segmento agrupa >= min_len muestras consecutivas.
    """
    segments = []
    for wn, well in wells.items():
        seg = []
        for p in well.points:
            ok = (p.grupo == group_id and p.entrenable
                  and p.vel is not None and np.isfinite(p.vel)
                  and p.se is not None and np.isfinite(p.se) and p.se < 800
                  and (p.di is None or p.di <= di_threshold))
            if ok:
                seg.append(p)
            else:
                if len(seg) >= min_len: segments.append((wn, seg))
                seg = []
        if len(seg) >= min_len: segments.append((wn, seg))
    return segments

def top_drilling(group_id, n=5, method="min_se_cv"):
    """
    Recomienda los N mejores segmentos de perforación de un dominio, según 3
    métodos posibles:

    - "min_se_cv": minimiza la VARIACIÓN INTERNA de SE dentro del segmento
      (coeficiente de variación dato a dato, cm a cm). Prioriza perforación
      MÁS ESTABLE/consistente, aunque su SE medio no sea el mínimo absoluto.
    - "min_se": minimiza directamente la SE media del segmento (menor energía
      específica = perforación más eficiente energéticamente).
    - "max_rop": maximiza la ROP media del segmento (mayor velocidad de
      penetración = mayor productividad).

    En los 3 casos, los segmentos candidatos pertenecen al MISMO dominio
    predicho por el modelo ML (grupo geomecánico), no se mezclan dominios.
    """
    segments = _segments_by_domain(group_id)
    if not segments:
        return []
    candidates = []
    for wn, seg in segments:
        se_arr = np.array([p.se for p in seg])
        vel_arr = np.array([p.vel for p in seg])
        se_cv = float(se_arr.std() / (se_arr.mean() or 1e-9))
        spp_vals = [p.seteo_pp for p in seg if p.seteo_pp is not None]
        spa_vals = [p.seteo_pa for p in seg if p.seteo_pa is not None]
        entry = {
            "well": wn, "largo": seg[len(seg)//2].largo, "n_pts": len(seg),
            "vel": float(vel_arr.mean()), "se": float(se_arr.mean()), "se_cv": round(se_cv, 4),
            "pp": float(np.mean([p.pp for p in seg])), "pr": float(np.mean([p.pr for p in seg])),
            "pa": float(np.mean([p.pa for p in seg])), "pd": float(np.mean([p.pd for p in seg])),
            "pf": float(np.mean([p.pf for p in seg])),
        }
        if len(spp_vals) >= len(seg) * 0.5:
            entry["seteo_pp"] = round(float(np.mean(spp_vals)), 1)
        if len(spa_vals) >= len(seg) * 0.5:
            entry["seteo_pa"] = round(float(np.mean(spa_vals)), 1)
        candidates.append(entry)
    if not candidates: return []

    if method == "min_se_cv":
        ranked = sorted(candidates, key=lambda c: c["se_cv"])
    elif method == "min_se":
        ranked = sorted(candidates, key=lambda c: c["se"])
    elif method == "max_rop":
        ranked = sorted(candidates, key=lambda c: -c["vel"])
    else:
        ranked = candidates

    return ranked[:n]

def export_domain_csv():
    rows = []
    for d, info in domains.items():
        pts = [p for p in all_points() if p.dominio == d]
        ucs_ml_v = [p.ucs_ml for p in pts if p.ucs_ml]
        di_v = [p.di for p in pts if p.di is not None]
        rows.append({"dominio":d,"n":info["count"],"ucs_lab":info.get("ucs_lab"),
                     "ucs_ml_media":round(np.mean(ucs_ml_v),1) if ucs_ml_v else None,
                     "di_media":round(np.mean(di_v),3) if di_v else None,
                     "grupo": pts[0].grupo if pts else None})
    return pd.DataFrame(rows)

def export_predictions_csv():
    rows = []
    for wn, well in wells.items():
        for p in well.points:
            rows.append({
                "pozo":wn,"largo":p.largo,"este":p.este,"norte":p.norte,"cota":p.cota,
                "vel":p.vel,"pp":p.pp,"pr":p.pr,"pa":p.pa,"pd":p.pd,"pf":p.pf,"se":p.se,
                "dominio":p.dominio or "","lito":p.lito or p.lito_inferida or "",
                "estructura":p.estructura or p.estructura_inferida or "",
                "ucs_ml":p.ucs_ml,"ucs_ml_p10":p.ucs_ml_p10,"ucs_ml_p90":p.ucs_ml_p90,
                "ucs_matriz":p.ucs_matriz,"di":p.di,
                "grupo":p.grupo or "","entrenable":int(p.entrenable),
                "band_check":p.band_check or "",
            })
    return pd.DataFrame(rows)

# ─── P3-3.3 · EXPORTACIONES DISTINGUIBLES CON CONFIRMACIÓN ───────────────────
# Antes: seis exportaciones (dominios.csv, predicciones.csv,
# validacion_mallas.csv, di_vs_rqd_por_caseron.csv, proyecto.gwz,
# kit_cap5.zip) con nombres indistinguibles entre sí de una sesión a otra, y
# sin ninguna confirmación antes de descargar. Ahora cada nombre incluye
# sitio + caserón(es) + fecha, y un diálogo muestra qué se exporta y cuántos
# registros antes de disparar la descarga.

def _slug(s: str) -> str:
    """Texto seguro para nombre de archivo: sin espacios ni acentos."""
    s = _norm_txt(s).replace(" ", "_")
    s = re.sub(r"[^a-z0-9_-]", "", s)
    return s or "x"

def _export_caseron_tag() -> str:
    casos = sorted({lay.caseron for lay in layers.values() if lay.caseron})
    if not casos: return "sin_caseron"
    if len(casos) == 1: return _slug(casos[0])
    return f"{len(casos)}caserones"

def export_filename(base: str, ext: str) -> str:
    """sitio + caserón(es) + fecha — para diferenciar las seis exportaciones
    en una misma carpeta de descargas."""
    site = active_site()["id"]
    stamp = time.strftime("%Y%m%d_%H%M")
    return f"{base}_{site}_{_export_caseron_tag()}_{stamp}.{ext}"

def _csv_with_metadata(df: pd.DataFrame, extra_lines: List[str]) -> str:
    """CSV con líneas de metadatos '#' antepuestas (parámetros DI vigentes:
    P3-3.7 exige que cualquier cambio quede registrado en lo que se exporta)."""
    encabezado = "\n".join(f"# {l}" for l in extra_lines)
    return encabezado + "\n" + df.to_csv(index=False)

def _export_descriptor(kind: str) -> Optional[Dict]:
    """
    Qué se va a exportar y cuántos registros, para el diálogo de confirmación.
    None si no hay nada que exportar — el llamador debe avisar en vez de
    abrir un diálogo vacío.
    """
    if kind == "dominios":
        n = len(domains)
        if n == 0: return None
        return {"kind": kind, "n": n, "unidad": "dominios",
                "filename": export_filename("dominios", "csv"),
                "desc": "Tabla resumen por dominio geomecánico (UCS/DI medios)."}
    if kind == "predicciones":
        n = len(list(all_points()))
        if n == 0: return None
        return {"kind": kind, "n": n, "unidad": "puntos MWD",
                "filename": export_filename("predicciones", "csv"),
                "desc": "Predicción de UCS punto a punto de todos los pozos cargados."}
    if kind == "validacion":
        df = export_validation_csv()
        if df.empty: return None
        return {"kind": kind, "n": len(df), "unidad": "pares cruce↔pico",
                "filename": export_filename("validacion_mallas", "csv"),
                "desc": "Validación multipozo de posición de mallas (T4)."}
    if kind == "di_rqd":
        df = export_di_rqd_csv()
        if df.empty: return None
        return {"kind": kind, "n": len(df), "unidad": "caserones",
                "filename": export_filename("di_vs_rqd", "csv"),
                "desc": "Correlación DI↔RQD por caserón (T5), validación externa del DI."}
    if kind == "proyecto":
        if not wells: return None
        n = len(wells)
        n_pts = sum(len(w.points) for w in wells.values())
        return {"kind": kind, "n": n, "unidad": "pozos",
                "filename": export_filename("proyecto", "gwz"),
                "desc": f"Sesión completa ({n_pts} puntos MWD, {len(layers)} mallas DXF, "
                       f"{len(drillholes)} sondajes). El modelo RF no se guarda."}
    if kind == "kit":
        if not wells: return None
        n = len(list(all_points()))
        return {"kind": kind, "n": n, "unidad": "puntos MWD",
                "filename": export_filename("kit_cap5", "zip"),
                "desc": f"Kit completo para el Capítulo 5: CSVs, figuras HTML y resumen "
                       f"({len(domains)} dominios, {len(wells)} pozos)."}
    return None

# ─── T10: PERSISTENCIA DE SESIÓN (save / load project) ───────────────────────
# El ZIP contiene:
#   project.json  — toda la información serializable (pozos, filtros, config,
#                   bandas geomecánicas, asignaciones de Layer, grupos)
#   triangles.npz — mallas DXF (triangles de cada Layer por nombre)
# El modelo RF NO se serializa: el usuario debe re-entrenar al cargar. Esto
# evita problemas de compatibilidad entre versiones de scikit-learn y mantiene
# el ZIP liviano (el entrenamiento sobre ~50 k puntos tarda <30 s).
import zipfile as _zipfile
import io as _io

def _point_to_dict(p):
    return {
        "largo":p.largo,"vel":p.vel,"pp":p.pp,"pa":p.pa,
        "pd":p.pd,"pr":p.pr,"pf":p.pf,"se":p.se,"t":p.t,
        "este":p.este,"norte":p.norte,"cota":p.cota,
        "raw_vel":p.raw_vel,"raw_pp":p.raw_pp,"raw_pa":p.raw_pa,
        "raw_pd":p.raw_pd,"raw_pr":p.raw_pr,"raw_pf":p.raw_pf,
        "entrenable":p.entrenable,"norm_excluded":p.norm_excluded,
        "dominio":p.dominio,"lito":p.lito,"estructura":p.estructura,
        "ucs_ml":p.ucs_ml,"ucs_matriz":p.ucs_matriz,
        "ucs_ml_prelim":p.ucs_ml_prelim,
        "ucs_ml_p10":p.ucs_ml_p10,"ucs_ml_p90":p.ucs_ml_p90,
        "di":p.di,"grupo":p.grupo,
        "lito_inferida":p.lito_inferida,"estructura_inferida":p.estructura_inferida,
        "grupo_confianza":p.grupo_confianza,"band_check":p.band_check,
        "seteo_pp":p.seteo_pp,"seteo_pa":p.seteo_pa,
        "atributos":dict(p.atributos),"alteracion":p.alteracion,
        "ambiguo":p.ambiguo,"ambiguo_motivo":p.ambiguo_motivo,
    }

def _point_from_dict(d):
    p = MWDPoint(
        largo=d["largo"],vel=d["vel"],pp=d["pp"],pa=d["pa"],
        pd=d["pd"],pr=d["pr"],pf=d["pf"],se=d["se"],t=d.get("t",0.0),
        este=d.get("este",0.0),norte=d.get("norte",0.0),cota=d.get("cota",0.0),
        raw_vel=d.get("raw_vel",0.0),raw_pp=d.get("raw_pp",0.0),raw_pa=d.get("raw_pa",0.0),
        raw_pd=d.get("raw_pd",0.0),raw_pr=d.get("raw_pr",0.0),raw_pf=d.get("raw_pf",0.0),
        entrenable=d.get("entrenable",True),norm_excluded=d.get("norm_excluded",False),
    )
    for attr in ("dominio","lito","estructura","ucs_ml","ucs_matriz","ucs_ml_prelim",
                 "ucs_ml_p10","ucs_ml_p90","di","grupo","lito_inferida",
                 "estructura_inferida","grupo_confianza","band_check","seteo_pp","seteo_pa",
                 "atributos","alteracion","ambiguo","ambiguo_motivo"):
        if attr in d: setattr(p, attr, d[attr])
    # (P3-3.4) Compatibilidad: un .gwz anterior al renombre trae la clave
    # vieja "ucs_confiable" en vez de "ucs_matriz".
    if "ucs_matriz" not in d and "ucs_confiable" in d:
        p.ucs_matriz = d["ucs_confiable"]
    return p

# ─── P2 · PERSISTENCIA DE SONDAJES DENTRO DEL PROYECTO ───────────────────────
# Sin esto, recargar un .gwz perdería los sondajes y la selección manual del
# usuario (T2.6 exige que la selección persista en el estado de la app).

def _drillhole_to_dict(dh: DrillHole) -> Dict:
    return {
        "holeid": dh.holeid, "x_utm": dh.x_utm, "y_utm": dh.y_utm, "z_utm": dh.z_utm,
        "length": dh.length, "surveys": dh.surveys, "trace": dh.trace,
        "trace_extended": dh.trace_extended,
        "lithology": dh.lithology, "structures": dh.structures,
        "geomec": dh.geomec, "density": dh.density, "warnings": dh.warnings,
        "banda": dh.banda, "estado": dh.estado, "dist_min_m": dh.dist_min_m,
        "malla_cercana": dh.malla_cercana, "metros_dentro": dh.metros_dentro,
        "metros_por_unidad": dh.metros_por_unidad, "n_estructuras": dh.n_estructuras,
        "rqd_mediana": dh.rqd_mediana, "rmr_mediana": dh.rmr_mediana,
        "seleccion_manual": dh.seleccion_manual,
    }


def _drillhole_from_dict(d: Dict) -> DrillHole:
    dh = DrillHole(holeid=d["holeid"], x_utm=d["x_utm"], y_utm=d["y_utm"], z_utm=d["z_utm"],
                   length=d.get("length"))
    dh.surveys = [tuple(s) for s in d.get("surveys", [])]
    dh.trace = [tuple(p) for p in d.get("trace", [])]
    dh.trace_extended = d.get("trace_extended", False)
    dh.lithology = d.get("lithology", [])
    dh.structures = d.get("structures", [])
    dh.geomec = d.get("geomec", [])
    dh.density = d.get("density", [])
    dh.warnings = d.get("warnings", [])
    dh.banda = d.get("banda")
    dh.estado = d.get("estado")
    dh.dist_min_m = d.get("dist_min_m")
    dh.malla_cercana = d.get("malla_cercana")
    dh.metros_dentro = d.get("metros_dentro", 0.0)
    dh.metros_por_unidad = d.get("metros_por_unidad", {})
    dh.n_estructuras = d.get("n_estructuras", 0)
    dh.rqd_mediana = d.get("rqd_mediana")
    dh.rmr_mediana = d.get("rmr_mediana")
    dh.seleccion_manual = d.get("seleccion_manual")
    return dh


def save_project(path):
    """
    Guarda el estado actual en `path` (archivo .gwz, ZIP).
    rf_model NO se serializa (re-entrenar al cargar; documentado en la UI).
    """
    proj = {
        "version": 2,
        "wells": {
            wn: {
                "well_name": w.well_name, "plan_id": w.plan_id, "hole_id": w.hole_id,
                "collar": w.collar, "final_pt": w.final_pt, "origin": w.origin,
                "dq_candidates": w.dq_candidates,
                "points": [_point_to_dict(p) for p in w.points],
            }
            for wn, w in wells.items()
        },
        "layers_meta": {
            ln: {
                "name": lay.name, "kind": lay.kind, "folder": lay.folder,
                "ucs_lab": lay.ucs_lab, "caseron": lay.caseron,
                "lito_alias": lay.lito_alias,
                "ucs_lo": lay.ucs_lo, "ucs_hi": lay.ucs_hi, "ucs_mid": lay.ucs_mid,
                "atributos": dict(lay.atributos), "nivel": lay.nivel,
                "bbox_min": lay.bbox_min.tolist(), "bbox_max": lay.bbox_max.tolist(),
            }
            for ln, lay in layers.items()
        },
        # (P1-T1.7) El vocabulario viaja con el proyecto: sin él, un .gwz cargado
        # en otra sesión perdería los anclajes de UCS y las exclusiones
        # justificadas, y el bloqueo de entrenamiento se dispararía sin motivo.
        "vocabulario": export_vocabulary(),
        "sitio_activo": ACTIVE_SITE,
        "site_confirmed_tokens": sorted(site_confirmed_tokens),
        "attribute_meters": attribute_meters,
        "overlap_stats": {k: v for k, v in overlap_stats.items()},
        "domains": domains,
        "domain_groups": domain_groups,
        "clean_filters": clean_filters,
        "inicio_cut_m": inicio_cut_m,
        "cal_factors": cal_factors,
        "di_config": di_config,
        "di_threshold": di_threshold,
        "group_interval_m": group_interval_m,
        "ucs_range": ucs_range,
        "global_center": global_center,
        "geomech_records": geomech_bands["records"],
        "excel_data": excel_data,
        "parse_warnings": parse_warnings,
        "wz_state": wz_state,
        # (P2-T2.6) Sondajes + selección (auto o manual) + reparto espacial.
        "drillholes": {hid: _drillhole_to_dict(dh) for hid, dh in drillholes.items()},
        "spatial_bands": spatial_bands,
    }
    tris_npz = {}
    for ln, lay in layers.items():
        tris_npz[ln] = lay.triangles
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(proj, allow_nan=True))
        npz_buf = _io.BytesIO()
        np.savez_compressed(npz_buf, **{k.replace("/","_"): v for k, v in tris_npz.items()})
        zf.writestr("triangles.npz", npz_buf.getvalue())
    with open(path, "wb") as f:
        f.write(buf.getvalue())

def load_project(path):
    """
    Carga un proyecto desde `path` (.gwz). Limpia el estado global y lo
    reconstruye. El modelo RF NO se restaura (se muestra advertencia en la UI).
    """
    global di_threshold, group_interval_m, global_center, inicio_cut_m
    with _zipfile.ZipFile(path, "r") as zf:
        proj = json.loads(zf.read("project.json"))
        npz_data = np.load(_io.BytesIO(zf.read("triangles.npz")), allow_pickle=False)

    # Limpiar estado global
    wells.clear(); layers.clear(); domains.clear()
    domain_groups.clear(); clean_filters.clear()
    excel_data.clear(); parse_warnings.clear()
    geomech_bands["by_pair"].clear(); geomech_bands["by_lito"].clear()
    geomech_bands["by_caseron"].clear(); geomech_bands["records"].clear()
    drillholes.clear(); spatial_bands.clear()

    # Restaurar pozos
    for wn, wd in proj.get("wells", {}).items():
        pts = [_point_from_dict(pd_) for pd_ in wd["points"]]
        w = Well(well_name=wd["well_name"], plan_id=wd["plan_id"], hole_id=wd["hole_id"],
                 points=pts, collar=wd.get("collar"), final_pt=wd.get("final_pt"),
                 origin=wd.get("origin","loaded"), dq_candidates=wd.get("dq_candidates",[]))
        wells[wn] = w

    # Restaurar capas (meta + triángulos)
    for ln, lm in proj.get("layers_meta", {}).items():
        npz_key = ln.replace("/","_")
        tris = npz_data[npz_key] if npz_key in npz_data else np.zeros((0,3,3))
        lay = Layer(
            name=lm["name"], kind=lm["kind"], triangles=tris,
            bbox_min=np.array(lm["bbox_min"]), bbox_max=np.array(lm["bbox_max"]),
            ucs_lab=lm.get("ucs_lab"), folder=lm.get("folder","Litología"),
            caseron=lm.get("caseron"), lito_alias=lm.get("lito_alias"),
            ucs_lo=lm.get("ucs_lo"), ucs_hi=lm.get("ucs_hi"), ucs_mid=lm.get("ucs_mid"),
            atributos=dict(lm.get("atributos") or ({"litologia": lm["atributo_id"]}
                            if lm.get("atributo_id") else {})),
            nivel=lm.get("nivel"),
        )
        layers[ln] = lay

    # Restaurar colecciones y configuración
    domains.update(proj.get("domains", {}))
    domain_groups.extend(proj.get("domain_groups", []))
    clean_filters.extend(proj.get("clean_filters", []))
    inicio_cut_m = proj.get("inicio_cut_m", inicio_cut_m)
    cal_factors.update(proj.get("cal_factors", {}))
    di_config.update(proj.get("di_config", {}))
    di_threshold = proj.get("di_threshold", di_threshold)
    group_interval_m = proj.get("group_interval_m", group_interval_m)
    ucs_range.update(proj.get("ucs_range", {}))
    global_center = proj.get("global_center")
    excel_data.extend(proj.get("excel_data", []))
    parse_warnings.extend(proj.get("parse_warnings", []))
    wz_state.update(proj.get("wz_state", {}))
    if proj.get("geomech_records"):
        index_geomech_bands(proj["geomech_records"])
    # (P2-T2.6) Restaurar sondajes: la selección manual del usuario debe
    # sobrevivir a guardar/cargar el proyecto.
    for hid, dd in proj.get("drillholes", {}).items():
        drillholes[hid] = _drillhole_from_dict(dd)
    spatial_bands.update(proj.get("spatial_bands", {}))
    # (P1-T1.7) Restaurar vocabulario, exclusiones y confirmaciones de sitio.
    # Si el proyecto es anterior a P1 no trae vocabulario: se resiembra el
    # registro por defecto en vez de quedar vacío (que bloquearía todo).
    site_confirmed_tokens.clear()
    site_confirmed_tokens.update(proj.get("site_confirmed_tokens", []))
    site_pending_confirms.clear()
    attribute_meters.clear()
    attribute_meters.update(proj.get("attribute_meters", {}))
    overlap_stats.update(proj.get("overlap_stats", {}))
    vocab = proj.get("vocabulario")
    if vocab:
        res = import_vocabulary(vocab, replace=True)
        for e in res["errores"]:
            log_warn(f"Vocabulario al cargar proyecto: {e}")
    else:
        seed_attribute_registry(force=True)
        log_warn("Proyecto sin registro de vocabulario (anterior a P1): "
                 "se sembró el registro por defecto del sitio.")

# ─── P1-T1.7 · PERSISTENCIA DEL REGISTRO DE VOCABULARIO ──────────────────────
# Exporta/importa atributos + alias + exclusiones justificadas. Legible por
# humanos, versionable, y publicable como anexo de la memoria.

# (P1c-B.4) v2: agrega ucs_central, dispersion_min, dispersion_max, ucs_cv.
# Compatible hacia atrás: import_vocabulary filtra por Attribute.__dataclass_
# fields__, así que un registro v1 sin estos campos carga igual (quedan None).
VOCAB_SCHEMA_VERSION = 2


def export_vocabulary() -> Dict:
    """Registro completo como dict serializable (JSON legible)."""
    from dataclasses import asdict
    return {
        "schema": "mwd-geomech-vocabulario",
        "schema_version": VOCAB_SCHEMA_VERSION,
        "sitio_activo": ACTIVE_SITE,
        "sitio": active_site(),
        "exportado": time.strftime("%Y-%m-%d %H:%M:%S"),
        "calidad_catalogo": {str(k): v for k, v in QUALITY_LABELS.items()},
        "atributos": [asdict(a) for a in attr_registry.values()],
        "alias": [asdict(a) for a in alias_registry.values()],
        "exclusiones": [
            {"atributo_id": k, **v} for k, v in sorted(attribute_exclusions.items())
        ],
        "pendientes": [
            {"texto_crudo": v["texto_crudo"], "origenes": sorted(v["origenes"]),
             "n_vistas": v["n_vistas"],
             # La propuesta de descomposición (A.3) viaja como sugerencia; al
             # importar sigue requiriendo confirmación explícita.
             "propuesta": ((v.get("propuesta") or {}).get("atributos") or None)}
            for v in pending_aliases.values()
        ],
    }


def export_vocabulary_json(indent: int = 2) -> str:
    return json.dumps(export_vocabulary(), ensure_ascii=False, indent=indent)


def export_vocabulary_csv() -> str:
    """Vista tabular de los atributos (una fila por atributo), separador ';'."""
    cols = ["id", "nombre_oficial", "sitio", "rol", "nivel", "padre", "ucs_min", "ucs_max",
            "ucs_media", "ucs_central", "ucs_sd", "ucs_n", "ucs_cv",
            "dispersion_min", "dispersion_max", "alta_variabilidad",
            "calidad", "calidad_etiqueta", "pi_factor",
            "excluido", "justificacion_exclusion", "mi", "modulo_E", "poisson",
            "densidad", "fuente", "fecha", "alias", "notas"]
    rows = []
    for a in attr_registry.values():
        exc = attribute_exclusions.get(a.id)
        al = "|".join(sorted(x.texto_crudo for x in alias_registry.values()
                             if a.id in x.atributos.values()))
        rows.append({
            "id": a.id, "nombre_oficial": a.nombre_oficial, "sitio": a.sitio,
            "rol": a.rol, "nivel": a.nivel, "padre": a.padre or "", "ucs_min": a.ucs_min,
            "ucs_max": a.ucs_max, "ucs_media": a.ucs_media, "ucs_central": a.ucs_central,
            "ucs_sd": a.ucs_sd, "ucs_n": a.ucs_n, "ucs_cv": a.ucs_cv,
            "dispersion_min": a.dispersion_min, "dispersion_max": a.dispersion_max,
            "alta_variabilidad": "sí" if a.alta_variabilidad() else "no",
            "calidad": a.calidad,
            "calidad_etiqueta": QUALITY_LABELS.get(a.calidad, "?"),
            "pi_factor": a.pi_factor(), "excluido": "sí" if exc else "no",
            "justificacion_exclusion": (exc or {}).get("justificacion", ""),
            "mi": a.mi, "modulo_E": a.modulo_E, "poisson": a.poisson,
            "densidad": a.densidad, "fuente": a.fuente, "fecha": a.fecha,
            "alias": al, "notas": a.notas.replace("\n", " "),
        })
    return pd.DataFrame(rows, columns=cols).to_csv(index=False, sep=";")


def import_vocabulary(data, replace: bool = True) -> Dict:
    """
    Importa un registro exportado. `data` es un dict o una cadena JSON.
    Devuelve un resumen {atributos, alias, exclusiones, errores}. Los conflictos
    de alias se reportan, nunca se resuelven en silencio.
    """
    if isinstance(data, (str, bytes)):
        data = json.loads(data)
    if data.get("schema") != "mwd-geomech-vocabulario":
        raise ValueError("El archivo no es un registro de vocabulario válido.")
    errores = []
    if replace:
        attr_registry.clear(); alias_registry.clear()
        pending_aliases.clear(); attribute_exclusions.clear()
    campos = {f for f in Attribute.__dataclass_fields__}
    for d in data.get("atributos", []):
        try:
            attr_registry[d["id"]] = Attribute(**{k: v for k, v in d.items() if k in campos})
        except Exception as e:
            errores.append(f"atributo {d.get('id','?')}: {e}")
    for d in data.get("alias", []):
        try:
            # Compatibilidad hacia atrás: los export previos a A.2 traían un
            # `atributo_id` suelto en vez del mapa {rol: id}.
            destino = d.get("atributos") or d.get("atributo_id")
            register_alias(d["texto_crudo"], destino, d.get("origen", "manual"))
        except Exception as e:
            errores.append(f"alias «{d.get('texto_crudo','?')}»: {e}")
    for d in data.get("exclusiones", []):
        try:
            exclude_attribute(d["atributo_id"], d.get("justificacion", ""))
        except Exception as e:
            errores.append(f"exclusión {d.get('atributo_id','?')}: {e}")
    for d in data.get("pendientes", []):
        for o in d.get("origenes", ["manual"]):
            note_pending_alias(d["texto_crudo"], o)
    errores.extend(validate_attribute_tree())
    return {"atributos": len(attr_registry), "alias": len(alias_registry),
            "exclusiones": len(attribute_exclusions), "errores": errores}


# ─── T11: KIT DE EXPORTACIÓN "CAPÍTULO 5" ────────────────────────────────────
# Genera un ZIP con CSVs + figuras HTML standalone + resumen.txt para incluir
# directamente en el informe de tesis (Capítulo 5). La operación corre en hilo
# de fondo y reporta avance a kit_task_state (polling desde dcc.Interval).

kit_task_state = {
    "running": False, "progress": 0, "stage": "",
    "error": None, "bytes": None, "done": False,
    # (P3-3.3) Nombre descriptivo fijado al confirmar, usado al entregar el
    # ZIP cuando el hilo de fondo termina.
    "filename": "kit_cap5.zip",
}

def _build_kit_zip():
    """Genera el contenido del ZIP Cap.5 y lo retorna como bytes."""
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as zf:

        # 1. CSVs
        try:
            zf.writestr("predicciones.csv", export_predictions_csv().to_csv(index=False))
        except Exception: pass
        try:
            zf.writestr("dominios.csv", export_domain_csv().to_csv(index=False))
        except Exception: pass
        try:
            df_val = export_validation_csv()
            if not df_val.empty:
                zf.writestr("validacion_mallas.csv", df_val.to_csv(index=False))
        except Exception: pass
        try:
            df_rqd = export_di_rqd_csv()
            if not df_rqd.empty:
                zf.writestr("di_rqd.csv", df_rqd.to_csv(index=False))
        except Exception: pass

        # 2. Figuras HTML standalone
        def _html(fig):
            return fig.to_html(full_html=True, include_plotlyjs="cdn")

        # Visor 3D coloreado por dominio
        try:
            fig3d = build_3d_figure(color_by="grupo")
            zf.writestr("visor_3d_dominios.html", _html(fig3d))
        except Exception: pass

        # DI ↔ RQD scatter
        try:
            data_rqd = di_vs_rqd_by_caseron()
            if data_rqd:
                zf.writestr("di_vs_rqd.html", _html(build_di_rqd_figure(data_rqd)))
        except Exception: pass

        # Histograma de offsets (validación de mallas)
        try:
            if mesh_validation_results:
                fig_off = go.Figure()
                for r in mesh_validation_results:
                    if r.get("offsets"):
                        fig_off.add_trace(go.Histogram(x=r["offsets"], name=r["malla"],
                                                        nbinsx=20, opacity=0.7))
                fig_off.add_vline(x=0, line_dash="dash", line_color="#888")
                fig_off.update_layout(barmode="overlay", template="plotly_dark",
                                      xaxis_title="Offset [m]", yaxis_title="N pares")
                zf.writestr("offset_histogram.html", _html(fig_off))
        except Exception: pass

        # Perfil DI + sensibilidad del pozo con más datos
        best_well = max(wells.values(), key=lambda w: len(w.points)) if wells else None
        if best_well:
            try:
                fig_di = build_di_figure(best_well)
                zf.writestr("di_perfil.html", _html(fig_di))
            except Exception: pass
            try:
                sens_result = di_sensitivity_analysis(best_well)
                fig_sens = build_di_sensitivity_figure(sens_result)
                zf.writestr("di_sensibilidad.html", _html(fig_sens))
            except Exception: pass

        # 3. Resumen
        lines = ["MWD GeoMech Wizard — Resumen Cap. 5", "="*50]
        # (P3-3.7) Los parámetros DI vigentes se declaran SIEMPRE, no solo
        # cuando difieren del default: alteran DI, UCS matriz y agrupación de
        # dominios aguas abajo, y el kit debe decir con cuáles se generó.
        lines.append(di_config_summary())
        lines.append(f"Emboquillado: corte < {inicio_cut_m:g} m")
        lines.append(f"Pozos: {len(wells)}")
        lines.append(f"Puntos MWD: {sum(len(w.points) for w in wells.values())}")
        all_pts = list(all_points())
        n_class = sum(1 for p in all_pts if p.lito)
        pct_class = round(100.0*n_class/len(all_pts), 1) if all_pts else 0
        lines.append(f"Clasificados: {n_class} ({pct_class}%)")
        if rf_stats:
            lines.append(f"RF R²: {rf_stats.get('r2_train','-')} (entrena) | "
                         f"CV GroupKFold: {rf_stats.get('cv_r2_mean','-')}")
            lines.append(f"MAE entrena: {rf_stats.get('mae_train','-')} MPa")
        lines.append(f"Dominios: {len(domains)}")
        lines.append(f"Grupos geomecánicos: {len(domain_groups)}")
        if mesh_validation_results:
            verdicts = [r['veredicto'] for r in mesh_validation_results]
            lines.append(f"Validación mallas: {', '.join(verdicts)}")
        zf.writestr("resumen.txt", "\n".join(lines))
    return buf.getvalue()

def run_kit_task():
    with task_lock:
        kit_task_state.update(running=True, progress=0, stage="Generando kit…",
                               error=None, bytes=None, done=False)
    try:
        with task_lock: kit_task_state["stage"] = "CSVs…"; kit_task_state["progress"] = 10
        data = _build_kit_zip()
        with task_lock:
            kit_task_state.update(running=False, progress=100, stage="Listo.",
                                   bytes=data, done=True)
    except Exception as e:
        with task_lock:
            kit_task_state.update(running=False, done=True, error=str(e), progress=100)

# ─── VISOR 3D ─────────────────────────────────────────────────────────────────
COLOR_FIELDS = {
    "se":("SE [bar·min/m]",0,500,False),"vel":("ROP [m/min]",0,2.5,False),
    "pp":("Percusión [bar]",0,230,False),"pa":("Avance [bar]",0,150,False),
    "pr":("Rotación [bar]",0,100,False),"pd":("Damper [bar]",0,150,False),
    "pf":("Flujo [bar]",0,25,False),"ucs_ml":("UCS ML [MPa]",0,270,False),
    "ucs_matriz":("UCS matriz (sin discontinuidades) [MPa]",0,270,False),"di":("DI",0,3,False),
    "lito":("Litología DXF",None,None,True),"grupo":("Dominio agrupado",None,None,True),
    "lito_inferida":("Litología inferida",None,None,True),
    "band_check":("Consistencia de banda",None,None,True),
}

# Colores fijos para la consistencia de banda (categórico con semántica).
BAND_COLORS = {"compatible":"#2ECC71", "incompatible":"#E74C3C",
               "ambiguo":"#F1C40F", "—":"#7F8C8D"}

def _fmt_ucs_interval(p):
    """'182 [155–213] MPa' si hay intervalo; '182 MPa' o 'sin calcular'."""
    if p.ucs_ml is None:
        return "sin calcular"
    if p.ucs_ml_p10 is not None and p.ucs_ml_p90 is not None:
        return f"{p.ucs_ml:.0f} [{p.ucs_ml_p10:.0f}–{p.ucs_ml_p90:.0f}] MPa"
    return f"{p.ucs_ml:.0f} MPa"

REPORT_VARS = {
    "vel": "ROP [m/min]", "pp": "Percusión [bar]", "pa": "Avance [bar]",
    "pr": "Rotación [bar]", "pd": "Damper [bar]", "pf": "Flujo [bar]",
    "se": "SE [bar·min/m]", "di": "DI (discontinuidad)",
    "ucs_ml": "UCS ML [MPa]", "ucs_matriz": "UCS matriz (sin discontinuidades) [MPa]",
}
# (P3-3.6) Variables cuyo histograma se recorta EN LA VISTA a percentiles
# 1-99 (nunca se filtran ni se borran datos). SE se aplasta con valores
# extremos cuando ROP tiende a cero (P_percusión+P_rotación+P_avance)/ROP.
REPORT_HIST_CLIP_VARS = {"se"}

def well_basic_stats(well_name):
    """Estadísticas descriptivas básicas de un pozo: media, mediana, std, min, max por variable."""
    well = wells.get(well_name)
    if not well or not well.points: return {}
    stats = {}
    for k, label in REPORT_VARS.items():
        vals = np.array([getattr(p, k) for p in well.points
                         if getattr(p, k, None) is not None and np.isfinite(getattr(p, k))])
        if vals.size == 0: continue
        stats[k] = {
            "label": label, "media": float(np.mean(vals)), "mediana": float(np.median(vals)),
            "std": float(np.std(vals)), "min": float(np.min(vals)), "max": float(np.max(vals)),
            "n": int(vals.size),
        }
    return stats

def build_well_report_figure(well_name, hist_vars=None, profile_var="di"):
    """
    Reporte gráfico de un pozo: perfil de UNA variable elegida vs profundidad
    (P3-3.5: antes fijo en DI; ahora cualquier variable de REPORT_VARS, cruda
    o calculada) + histogramas de hasta 3 variables MWD seleccionadas por el
    usuario.

    (P3-3.6) El histograma de variables en REPORT_HIST_CLIP_VARS (SE: se
    aplasta cuando ROP tiende a cero) se recorta EN LA VISTA a los percentiles
    1-99 — los datos no se filtran ni se borran, solo cambia el rango visible
    del eje, y el subtítulo lo declara.
    """
    well = wells.get(well_name)
    if not well or not well.points:
        return go.Figure()
    profile_var = profile_var if profile_var in REPORT_VARS else "di"
    hist_vars = hist_vars or ["se", "pp", "vel"]
    hist_vars = [v for v in hist_vars if v in REPORT_VARS][:3]
    n_hist = len(hist_vars)

    specs = [[{"colspan": max(n_hist,1)}] + [None]*(max(n_hist,1)-1)]
    if n_hist:
        specs.append([{"type":"xy"}]*n_hist)
    hist_titles = []
    for v in hist_vars:
        t = f"Histograma {REPORT_VARS[v]}"
        if v in REPORT_HIST_CLIP_VARS: t += " (vista: P1–P99)"
        hist_titles.append(t)
    titles = [f"{REPORT_VARS[profile_var]} vs. Profundidad"] + hist_titles
    fig = make_subplots(
        rows=2 if n_hist else 1, cols=max(n_hist,1),
        specs=specs, subplot_titles=titles,
        row_heights=[0.55,0.45] if n_hist else [1.0], vertical_spacing=0.14,
    )

    largos = [p.largo for p in well.points]
    prof_vals = [getattr(p, profile_var, None) for p in well.points]
    fig.add_trace(go.Scatter(x=largos, y=prof_vals, mode="lines", name=REPORT_VARS[profile_var],
                              line=dict(color="#3B8BD4", width=1.5)), row=1, col=1)
    if profile_var == "di":
        fig.add_hline(y=di_threshold, line_dash="dash", line_color="#E74C3C",
                      annotation_text=f"Umbral={di_threshold}", row=1, col=1)
    fig.update_xaxes(title_text="Profundidad [m]", row=1, col=1)
    fig.update_yaxes(title_text=REPORT_VARS[profile_var], row=1, col=1)

    for i, v in enumerate(hist_vars):
        vals = [getattr(p, v) for p in well.points
                if getattr(p, v, None) is not None and np.isfinite(getattr(p, v))]
        fig.add_trace(go.Histogram(x=vals, marker_color=PALETTE[i % len(PALETTE)],
                                     name=REPORT_VARS[v], nbinsx=30), row=2, col=i+1)
        fig.update_xaxes(title_text=REPORT_VARS[v], row=2, col=i+1)
        if v in REPORT_HIST_CLIP_VARS and len(vals) >= 2:
            p1, p99 = np.percentile(vals, [1, 99])
            if p99 > p1:
                fig.update_xaxes(range=[p1, p99], row=2, col=i+1)

    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#0d0d1a", plot_bgcolor="#0d0d1a",
        showlegend=False, margin=dict(l=40,r=20,t=50,b=40), height=520,
    )
    return fig

# (E.4 — Escala) El visor 3D es el único gráfico que dibuja TODOS los pozos
# de un caserón a la vez (~262.500 puntos en escala real); el resto de los
# gráficos son por-pozo y quedan chicos por construcción (un pozo real no
# supera unos pocos miles de muestras). Ningún gráfico debe recibir 262.500
# puntos como marcadores — se recorta la VISTA, nunca la población que usan
# los cálculos.
MAX_VIZ_POINTS = 5000

def _submuestrear_indices(n: int, max_n: int) -> List[int]:
    """
    Índices espaciados regularmente para submuestrear `n` elementos a como
    máximo `max_n`, preservando el orden — a diferencia de un muestreo
    aleatorio, esto conserva la continuidad espacial de una traza (línea +
    marcadores) y garantiza que el primer punto (el collar del pozo) quede
    incluido siempre.
    """
    if n <= max_n or n == 0:
        return list(range(n))
    step = n / max_n
    return [int(i * step) for i in range(max_n)]

def build_3d_figure(color_by="se", hidden_layers=None, hidden_wells=None):
    """
    hidden_layers / hidden_wells: sets de nombres a OCULTAR (checkbox destildado).
    Se usa 'visible' (no se omite la traza) para que Plotly conserve el índice
    de trazas estable entre renders y uirevision funcione correctamente.

    (E.4) La VISTA se recorta a MAX_VIZ_POINTS puntos en total, repartidos
    proporcionalmente entre pozos (uno con más metraje aporta más puntos a
    la vista). well.points NUNCA se toca — el recorte vive solo en las
    listas locales que arma esta función para dibujar.
    """
    hidden_layers = hidden_layers or set()
    hidden_wells  = hidden_wells or set()
    fig = go.Figure()
    n_total_pts = sum(len(w.points) for w in wells.values())
    ratio = (MAX_VIZ_POINTS / n_total_pts) if n_total_pts > MAX_VIZ_POINTS else 1.0
    label, cmin, cmax, categorical = COLOR_FIELDS.get(color_by, ("",0,1,False))
    cat_map = {}
    if categorical:
        all_cats = sorted({getattr(p, color_by) or "—" for well in wells.values() for p in well.points})
        if color_by == "band_check":
            # Colores semánticos fijos (verde/rojo/amarillo/gris), no la paleta.
            cat_map = {c: BAND_COLORS.get(c, "#7F8C8D") for c in all_cats}
        else:
            cat_map = {c: PALETTE[i%len(PALETTE)] for i,c in enumerate(all_cats)}
    for idx, (name, layer) in enumerate(layers.items()):
        tris = layer.triangles
        if len(tris) == 0: continue
        x = tris[:,:,0].ravel(); y = tris[:,:,1].ravel(); z = tris[:,:,2].ravel()
        ii = list(range(0, len(tris)*3, 3))
        jj = list(range(1, len(tris)*3, 3))
        kk = list(range(2, len(tris)*3, 3))
        ucs_txt = f"UCS={layer.ucs_lab} MPa" if layer.ucs_lab else "sin UCS"
        col = PALETTE[idx % len(PALETTE)]
        fig.add_trace(go.Mesh3d(x=x,y=y,z=z,i=ii,j=jj,k=kk,opacity=0.28,name=name,color=col,
            hoverinfo="name+text",text=[f"{name} | {ucs_txt}"]*len(ii),
            showlegend=True,legendgroup="dxf",
            visible=True if name not in hidden_layers else "legendonly"))
    n_dibujados = 0
    for wn, well in wells.items():
        pts_full = well.points
        if not pts_full: continue
        # (E.4) Recorte SOLO de la vista: `pts` local, well.points intacto.
        if ratio < 1.0:
            # int() (piso), no round(): redondear cada pozo hacia arriba de
            # forma independiente puede acumular y superar MAX_VIZ_POINTS
            # entre varios pozos aunque cada uno individualmente respete la
            # proporción — el piso garantiza que la suma nunca lo supere.
            max_n_well = max(1, int(len(pts_full) * ratio))
            idx_view = _submuestrear_indices(len(pts_full), max_n_well)
            pts = [pts_full[i] for i in idx_view]
        else:
            pts = pts_full
        n_dibujados += len(pts)
        is_visible = True if wn not in hidden_wells else "legendonly"
        xs = [p.este for p in pts]; ys = [p.norte for p in pts]; zs = [p.cota for p in pts]
        # collar
        fig.add_trace(go.Scatter3d(x=[xs[0]],y=[ys[0]],z=[zs[0]],mode="markers",
            marker=dict(size=6,color="#111"),showlegend=False,
            hovertext=f"Collar {wn}: E={xs[0]:.1f} N={ys[0]:.1f} Z={zs[0]:.1f}",hoverinfo="text",
            visible=is_visible))
        if categorical:
            vals = [getattr(p, color_by) or "—" for p in pts]
            colors = [cat_map.get(v, "#888") for v in vals]
            hover = [f"<b>{wn}</b><br>{p.largo:.2f}m<br>{label}: {v}"
                     f"<br>UCS ML: {_fmt_ucs_interval(p)}"
                     f"<br>E={p.este:.1f} N={p.norte:.1f} Z={p.cota:.1f}"
                     for p,v in zip(pts,vals)]
            fig.add_trace(go.Scatter3d(x=xs,y=ys,z=zs,mode="lines+markers",name=wn,
                hovertext=hover,hoverinfo="text",line=dict(color="#333",width=1.5),
                marker=dict(size=2.5,color=colors,opacity=0.85),legendgroup="wells",
                visible=is_visible))
        else:
            # None (dato aún no calculado, ej. UCS antes de entrenar el ML) se
            # muestra explícito en el hover como "sin calcular" en vez de "0",
            # para no confundir "no hay dato" con "el valor real es 0".
            raw_vals_display = [getattr(p, color_by) for p in pts]
            raw_vals = [v if v is not None else 0 for v in raw_vals_display]
            hover = [f"<b>{wn}</b><br>{p.largo:.2f}m<br>{label}: "
                     f"{f'{vd:.2f}' if vd is not None else 'sin calcular'}"
                     f"<br>DI: {f'{p.di:.2f}' if p.di is not None else '—'}"
                     f"<br>UCS ML: {_fmt_ucs_interval(p)}"
                     f"<br>E={p.este:.1f} N={p.norte:.1f} Z={p.cota:.1f}"
                     for p,vd in zip(pts,raw_vals_display)]
            fig.add_trace(go.Scatter3d(x=xs,y=ys,z=zs,mode="lines+markers",name=wn,
                hovertext=hover,hoverinfo="text",line=dict(color="rgba(150,150,150,0.4)",width=1),
                marker=dict(size=2.5,color=raw_vals,colorscale="Plasma",cmin=cmin,cmax=cmax,
                            opacity=0.85,showscale=True,
                            colorbar=dict(title=dict(text=label,font=dict(size=10)),
                                          thickness=14,len=0.55,x=1.02)),legendgroup="wells",
                visible=is_visible))
    # (E.4) El conteo real se declara SIEMPRE, se haya recortado la vista o
    # no — omitirlo cuando "por suerte" cabe entero sería el mismo default
    # silencioso que el proyecto prohíbe en todo lo demás: el usuario nunca
    # debería tener que adivinar si está viendo el 100% o una muestra.
    titulo_conteo = (f"Mostrando {n_dibujados:,} de {n_total_pts:,} puntos MWD"
                     .replace(",", "."))
    fig.update_layout(paper_bgcolor="#0d0d1a",
        title=dict(text=titulo_conteo, font=dict(size=11, color="#888"),
                   x=0.01, xanchor="left", y=0.99, yanchor="top"),
        scene=dict(
            xaxis=dict(title=dict(text="Este (UTM m)",font=dict(size=11)),gridcolor="#222"),
            yaxis=dict(title=dict(text="Norte (UTM m)",font=dict(size=11)),gridcolor="#222"),
            zaxis=dict(title=dict(text="Cota (m.s.n.m.)",font=dict(size=11)),gridcolor="#222"),
            bgcolor="#070711",aspectmode="data",camera=dict(eye=dict(x=1.6,y=1.6,z=0.9))),
        margin=dict(l=0,r=0,t=24,b=0),
        legend=dict(font=dict(size=10),bgcolor="rgba(0,0,0,0.5)",x=0.01,y=0.99,
                    bordercolor="#333",borderwidth=1),
        uirevision="viewport")
    return fig

# ─── APP DASH ─────────────────────────────────────────────────────────────────
# (P1) Sembrar el registro de vocabulario ANTES de construir el layout: el
# contador de pendientes y el panel de vocabulario lo leen al renderizar.
seed_attribute_registry()
for _e in validate_attribute_tree():
    log_warn(f"Registro de vocabulario: {_e}")

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.SLATE],
                title=f"{APP_TITLE} v{APP_VERSION}", suppress_callback_exceptions=True)

def card(title, body):
    return dbc.Card([
        dbc.CardHeader([html.B(title)], style={"fontSize":"12px","padding":"7px 12px"}),
        dbc.CardBody(body, style={"padding":"10px 12px"}),
    ], className="mb-2", color="dark", outline=True)

def wz_prereq(step):
    """
    Determina si se puede NAVEGAR a `step`. Se calcula el "techo" (máximo
    paso desbloqueado según los datos actuales) y se permite cualquier paso
    <= techo, incluyendo retroceder libremente a pasos ya visitados.

    IMPORTANTE: el prerequisito de cada paso N es lo que se necesita para
    ENTRAR a N, no lo que se logra completando N. Por ejemplo, el Paso 3 (DI)
    solo requiere tener pozos cargados —el DI se calcula DENTRO del paso 3,
    así que exigir 'DI ya calculado' para entrar sería una contradicción que
    deja al usuario atrapado sin poder nunca alcanzar ese paso.
    """
    reached = 1
    if bool(wells): reached = 3          # con pozos ya se puede ir a Calibración (2) y DI (3)
    if any(p.di is not None for p in all_points()): reached = 4   # con DI calculado, se desbloquea ML (4)
    if rf_model is not None: reached = 5  # con modelo entrenado, se desbloquea Dominios (5)
    return step <= reached

def step_pills(active):
    labels = ["1·Datos","2·Calibración","3·DI","4·ML","5·Dominios"]
    done = [wz_state['step1']['xml_loaded'],wz_state['step2']['cleaned'],
            wz_state['step3']['di_computed'],wz_state['step4']['model_trained'],
            wz_state['step5']['grouped']]
    pills = []
    for i, (lbl, d) in enumerate(zip(labels, done)):
        step_n = i+1
        pills.append(dbc.Button(("✓ " if d else "") + lbl,
            id={"type":"pill","index":step_n}, n_clicks=0,
            color="info" if step_n == active else ("success" if d else "secondary"),
            outline=step_n != active, size="sm", className="me-1", disabled=not wz_prereq(step_n)))
    return pills

app.layout = dbc.Container(fluid=True, style={"height":"100vh","padding":0,"overflow":"hidden"}, children=[
    dbc.Toast(id="toast", header="Notificación", is_open=False, duration=5500,
              style={"position":"fixed","top":10,"right":10,"zIndex":9999,"minWidth":"350px"}),
    dbc.Navbar(dbc.Container(fluid=True, children=[
        html.Span([f"⛏ {APP_TITLE} v{APP_VERSION}"],
                  style={"fontSize":"13px","fontWeight":700,"color":"#e0e0e0","marginRight":"12px"}),
        html.Div(id="pills-bar", className="d-flex align-items-center gap-1 flex-wrap flex-grow-1"),
        # (P1-T1.8) Contador de pendientes SIEMPRE visible desde la vista
        # principal, no escondido en el panel de vocabulario.
        html.Div(id="vocab-badge", className="d-flex align-items-center",
                 style={"marginRight":"10px"}),
        # (P2-T2.6) Contador de sondajes seleccionados, visible desde la vista
        # principal igual que el badge de vocabulario.
        html.Div(id="drillhole-badge", className="d-flex align-items-center",
                 style={"marginRight":"10px"}),
        html.Div([html.Label("Color:", style={"fontSize":"11px","color":"#aaa","marginRight":"4px"}),
                  dcc.Dropdown(id="color-by",
                    options=[{"label":v[0],"value":k} for k,v in COLOR_FIELDS.items()],
                    value="se", clearable=False, style={"width":"155px","fontSize":"11px"})],
                 className="d-flex align-items-center"),
    ]), color="dark", dark=True, style={"minHeight":"46px","padding":"4px 12px"}),
    dbc.Row(style={"height":"calc(100vh - 46px)","margin":0}, children=[
        dbc.Col(width=4, style={"height":"100%","padding":0,"borderRight":"1px solid #222",
                                 "display":"flex","flexDirection":"column","background":"#0d0d1a"}, children=[
            html.Div(id="wz-content", style={"flex":1,"overflowY":"auto","padding":"10px"}),
            html.Div(style={"borderTop":"1px solid #222","padding":"8px","maxHeight":"210px",
                             "overflowY":"auto","background":"#0a0a14"}, children=[
                html.Small("CAPAS DXF Y POZOS", style={"color":"#555","letterSpacing":"1px","fontSize":"10px"}),
                html.Div(id="layer-tree"),
            ]),
        ]),
        dbc.Col(width=8, style={"height":"100%","padding":0,"position":"relative"}, children=[
            dcc.Loading(dcc.Graph(id="viewport-3d", figure=build_3d_figure(),
                                    style={"height":"100%"},
                                    config={"displayModeBar":"hover","scrollZoom":True}),
                        type="circle", color="#3B8BD4"),
            html.Div(id="center-info", style={"position":"absolute","top":"10px","left":"10px",
                "background":"rgba(0,0,0,0.6)","color":"#aaa","padding":"4px 10px",
                "fontSize":"10px","borderRadius":"4px","fontFamily":"monospace","zIndex":100}),
        ]),
    ]),
    dcc.Upload(id="up-dxf", multiple=True, children=html.Div(), style={"display":"none"}),
    dcc.Upload(id="up-xml", multiple=True, children=html.Div(), style={"display":"none"}),
    dcc.Upload(id="up-excel", multiple=False, children=html.Div(), style={"display":"none"}),
    dcc.Upload(id="up-geomech", multiple=False, children=html.Div(), style={"display":"none"}),
    dcc.Upload(id="up-project", multiple=False, children=html.Span(""), accept=".gwz",
               style={"display":"none"}),
    dcc.Upload(id="up-drillhole", multiple=True, children=html.Div(), accept=".csv",
               style={"display":"none"}),
    dcc.Download(id="download"),
    dcc.Download(id="download-project"),
    dcc.Download(id="download-kit"),
    dcc.Store(id="refresh", data=0),
    dcc.Store(id="active-step", data=1),
    dcc.Interval(id="ml-task-poll", interval=500, disabled=True),
    dcc.Interval(id="val-task-poll", interval=500, disabled=True),
    dcc.Interval(id="kit-interval", interval=1000, disabled=True),
    dcc.Store(id="report-well-name", data=None),
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle(id="well-report-title", children="Reporte de pozo")),
        dbc.ModalBody([
            html.Div([
                # (P3-3.5) Antes fijo en DI. Cualquier variable de REPORT_VARS
                # (cruda o calculada) puede graficarse a lo largo del pozo.
                html.Small("Perfil vs. profundidad:", style={"color":"#aaa","marginRight":"8px"}),
                dcc.Dropdown(id="well-report-profile-var",
                             options=[{"label":v,"value":k} for k,v in REPORT_VARS.items()],
                             value="di", clearable=False,
                             style={"fontSize":"11px","width":"260px","display":"inline-block","marginRight":"16px"}),
                html.Small("Variables para histograma (máx. 3):", style={"color":"#aaa","marginRight":"8px"}),
                dcc.Dropdown(id="well-report-vars", options=[{"label":v,"value":k} for k,v in REPORT_VARS.items()],
                             value=["se","pp","vel"], multi=True, style={"fontSize":"11px","width":"420px","display":"inline-block"}),
            ], className="mb-2 d-flex align-items-center"),
            dcc.Graph(id="well-report-graph", config={"displayModeBar":False}),
            html.Div(id="well-report-stats-table"),
        ]),
        dbc.ModalFooter(dbc.Button("Cerrar", id="close-well-report", size="sm", color="secondary")),
    ], id="well-report-modal", size="xl", is_open=False),
    # (P1-T1.8) Panel de vocabulario: atributos, alias, pendientes, traslapes,
    # objetos fuera de sitio y persistencia del registro.
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Registro de vocabulario y partición por sitio")),
        dbc.ModalBody(id="vocab-modal-body", style={"maxHeight":"75vh","overflowY":"auto"}),
        dbc.ModalFooter(dbc.Button("Cerrar", id="close-vocab", size="sm", color="secondary")),
    ], id="vocab-modal", size="xl", is_open=False, scrollable=True),
    # (P2-T2.6) Panel de sondajes: lista con selección, métricas por pozo,
    # reparto espacial y cruce traza↔malla.
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Sondajes — selección de pozos relevantes")),
        dbc.ModalBody(id="drillhole-modal-body", style={"maxHeight":"75vh","overflowY":"auto"}),
        dbc.ModalFooter(dbc.Button("Cerrar", id="close-drillhole", size="sm", color="secondary")),
    ], id="drillhole-modal", size="xl", is_open=False, scrollable=True),
    # (P3-3.3) Confirmación de exportación: qué se exporta y cuántos
    # registros, antes de disparar cualquiera de las seis descargas.
    dcc.Store(id="export-pending", data=None),
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Confirmar exportación")),
        dbc.ModalBody(id="export-confirm-body"),
        dbc.ModalFooter([
            dbc.Button("Cancelar", id="btn-export-cancel", size="sm", color="secondary"),
            dbc.Button("Confirmar y descargar", id="btn-export-confirm", size="sm", color="primary"),
        ]),
    ], id="export-confirm-modal", is_open=False),
    # (P3-3.9) Reporte de justificación de variables: armazón que muestra
    # correlación/multicolinealidad, importancia, comparación de modelos
    # con/sin SE y ablación de cota (LOCO-CV), con resultados en cuanto
    # existan datos suficientes.
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Reporte de justificación de variables")),
        dbc.ModalBody(id="varjust-modal-body", style={"maxHeight": "75vh", "overflowY": "auto"}),
        dbc.ModalFooter(dbc.Button("Cerrar", id="close-varjust", size="sm", color="secondary")),
    ], id="varjust-modal", size="xl", is_open=False, scrollable=True),
])

# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  P1-T1.8 — PANEL DE VOCABULARIO                                          ║
# ║  Tabla de atributos editable · tabla de alias · bandeja de pendientes    ║
# ║  con contador · exportar/importar · confirmaciones de sitio.             ║
# ╚══════════════════════════════════════════════════════════════════════════╝

_VOCAB_NUM_FIELDS = [
    ("ucs_min", "UCS mín (confianza)"), ("ucs_max", "UCS máx (confianza)"),
    ("ucs_media", "UCS media"), ("ucs_central", "UCS central"),
    ("ucs_sd", "UCS SD"), ("ucs_n", "n probetas"), ("ucs_cv", "CV"),
    ("dispersion_min", "Dispersión mín"), ("dispersion_max", "Dispersión máx"),
    ("mi", "mi"), ("modulo_E", "E [GPa]"), ("poisson", "ν"), ("densidad", "γ [t/m³]"),
]


def _vocab_badge_children():
    n = pending_alias_count()
    n_bloq = len(training_blockers())
    n_sitio = len(site_pending_confirms)
    kids = []
    if n_sitio:
        kids.append(dbc.Badge(f"🚫 {n_sitio} fuera de sitio", color="danger",
                              className="me-1", style={"fontSize": "10px"}))
    if n:
        kids.append(dbc.Badge(f"🏷 {n} pendiente{'s' if n != 1 else ''}", color="warning",
                              className="me-1", style={"fontSize": "10px"}))
    if n_bloq:
        kids.append(dbc.Badge(f"⛔ {n_bloq} sin UCS", color="danger",
                              className="me-1", style={"fontSize": "10px"}))
    if not kids:
        kids.append(dbc.Badge("🏷 vocabulario OK", color="success", style={"fontSize": "10px"}))
    return dbc.Button(kids, id="btn-open-vocab", color="link", size="sm",
                      style={"padding": "0", "textDecoration": "none"})


ROLE_BADGE_COLOR = {"litologia": "primary", "alteracion": "info", "estructura": "warning"}


def _attr_row(a: Attribute):
    """
    Fila editable de un atributo.

    (A.1) Los campos de banda de UCS SOLO se ofrecen a rol="litologia": en los
    demás roles no aplican y la interfaz no debe mostrarlos.
    """
    exc = attribute_exclusions.get(a.id)
    ok, motivo = a.entrenable()
    con_banda = a.usa_banda_ucs()
    if exc:
        estado = dbc.Badge("excluido", color="secondary", style={"fontSize": "9px"})
    elif not con_banda:
        estado = dbc.Badge("no requiere banda de UCS", color="dark",
                           style={"fontSize": "9px"})
    elif ok:
        estado = dbc.Badge(f"OK · PI ×{a.pi_factor():.2f}", color="success", style={"fontSize": "9px"})
    else:
        estado = dbc.Badge(motivo, color="danger", style={"fontSize": "9px"})
    jer = (f"subunidad de {a.padre}" if a.nivel == "subunidad"
           else f"unidad" + (f" ({len(attribute_children(a.id))} sub)" if attribute_children(a.id) else ""))
    cuerpo = [
        html.Div([
            html.B(f"{a.id} — {a.nombre_oficial}", style={"fontSize": "11px"}),
            html.Span("  ", style={"marginRight": "4px"}),
            dbc.Badge(a.rol, color=ROLE_BADGE_COLOR.get(a.rol, "secondary"),
                      style={"fontSize": "9px"}),
            html.Span(f"  · {jer}", style={"color": "#888", "fontSize": "10px"}),
            html.Span("  ", style={"marginRight": "6px"}), estado,
            # (P1c-B.5) CV > umbral: la etiqueta es intrínsecamente más ancha,
            # no menos confiable — se declara junto al atributo, no se oculta.
            html.Span([html.Span("  ", style={"marginRight": "4px"}),
                      dbc.Badge(f"⚠ alta variabilidad (CV={a.ucs_cv:.2f})", color="warning",
                                style={"fontSize": "9px"})]) if a.alta_variabilidad() else None,
        ]),
    ]
    if con_banda:
        cuerpo.append(dbc.Row([
            dbc.Col([html.Small("Calidad del ancla", style={"color": "#888", "fontSize": "9px", "display": "block"}),
                     dcc.Dropdown(id={"type": "attr-calidad", "attr": a.id},
                                  options=[{"label": f"{k} · {v}", "value": k}
                                           for k, v in QUALITY_LABELS.items()],
                                  value=a.calidad, clearable=False,
                                  style={"fontSize": "10px"})], width=4),
            dbc.Col([html.Small("Fuente", style={"color": "#888", "fontSize": "9px", "display": "block"}),
                     dbc.Input(id={"type": "attr-txt", "attr": a.id, "field": "fuente"},
                               value=a.fuente, debounce=True, size="sm",
                               style={"fontSize": "10px"})], width=8),
        ], className="g-1 mt-1"))
        cuerpo.append(dbc.Row([
            dbc.Col([html.Small(lbl, style={"color": "#888", "fontSize": "9px", "display": "block"}),
                     dbc.Input(id={"type": "attr-num", "attr": a.id, "field": f},
                               type="number", value=getattr(a, f), debounce=True, size="sm",
                               style={"fontSize": "10px"})], width=2)
            for f, lbl in _VOCAB_NUM_FIELDS
        ], className="g-1 mt-1"))
    else:
        cuerpo.append(html.Small(
            f"El rol «{a.rol}» no lleva banda de UCS: la banda es propiedad de la "
            f"litología. No bloquea el entrenamiento.",
            style={"color": "#888", "fontSize": "9px", "display": "block", "marginTop": "3px"}))
    return dbc.ListGroupItem(cuerpo + [
        html.Div([
            dbc.Input(id={"type": "attr-excl-just", "attr": a.id},
                      placeholder="Justificación para excluir…",
                      value=(exc or {}).get("justificacion", ""), debounce=True, size="sm",
                      style={"fontSize": "10px", "display": "inline-block", "width": "70%"}),
            dbc.Button("Reincluir" if exc else "Excluir",
                       id={"type": "attr-excl-btn", "attr": a.id}, size="sm",
                       color="secondary" if exc else "warning", outline=True,
                       style={"fontSize": "10px", "marginLeft": "6px"}),
        ], className="mt-1"),
        html.Small(a.notas, style={"color": "#666", "fontSize": "9px", "display": "block",
                                   "marginTop": "3px"}) if a.notas else None,
    ], style={"background": "transparent", "borderBottom": "1px solid #222", "padding": "8px 10px"})


def _vocab_panel_body():
    attr_opts = [{"label": f"{a.id} — {a.nombre_oficial}  [{a.rol}]", "value": a.id}
                 for a in sorted(attr_registry.values(), key=lambda x: (x.rol, x.id))]
    unidades = [a for a in attr_registry.values() if a.nivel == "unidad"]
    subunidades = [a for a in attr_registry.values() if a.nivel == "subunidad"]

    # ── Bandeja de pendientes (con propuesta de composición, A.3) ────────────
    pend_rows = []
    for key, e in sorted(pending_aliases.items()):
        prop = e.get("propuesta")
        cabecera = dbc.Row([
            dbc.Col(html.Small([html.B(e["texto_crudo"]),
                                html.Span(f"  · {', '.join(sorted(e['origenes']))}"
                                          f" · visto {e['n_vistas']}×",
                                          style={"color": "#888"})],
                               style={"fontSize": "10px"}), width=5),
            # Multi: un alias puede apuntar a un atributo POR ROL (Bht_Fk →
            # litología + alteración). Dos del mismo rol es error visible.
            dbc.Col(dcc.Dropdown(id={"type": "pend-assign", "index": key}, options=attr_opts,
                                 placeholder="Asignar a atributo(s) — uno por rol…",
                                 multi=True, clearable=True,
                                 style={"fontSize": "10px"}), width=7),
        ], className="g-1 align-items-center")
        hijos = [cabecera]
        if prop:
            det = " + ".join(f"{r}: {a}" for r, a in sorted(prop["atributos"].items()))
            hijos.append(html.Div([
                html.Small([
                    html.Span("💡 Descomposición sugerida: ", style={"color": "#5DCAA5"}),
                    html.B(det),
                    html.Span(f"   (tokens: {', '.join(prop['tokens'])})",
                              style={"color": "#666"}),
                    html.Span("  · se propone, no se aplica sola",
                              style={"color": "#888", "fontStyle": "italic"}),
                ], style={"fontSize": "9px"}),
                dbc.Button("Confirmar composición",
                           id={"type": "pend-confirm-prop", "index": key},
                           size="sm", color="success", outline=True,
                           style={"fontSize": "9px", "marginLeft": "8px", "padding": "0 6px"}),
            ], className="mt-1"))
            if prop["sin_resolver"]:
                hijos.append(html.Small(
                    f"⚠ tokens sin correspondencia: {', '.join(prop['sin_resolver'])}",
                    style={"color": "#F39C12", "fontSize": "9px", "display": "block"}))
        pend_rows.append(dbc.ListGroupItem(hijos,
            style={"background": "transparent", "borderBottom": "1px solid #222", "padding": "5px 8px"}))
    pend_body = pend_rows or [html.Small("Sin textos pendientes. ✅",
                                         style={"color": "#666", "fontSize": "10px"})]

    # ── Confirmaciones de sitio (T1.1) ───────────────────────────────────────
    s = active_site()
    sitio_rows = []
    for e in site_pending_confirms:
        sitio_rows.append(dbc.ListGroupItem([
            html.Small([html.B(f"{e['etiqueta']} "),
                        html.Span(f"({e['tipo']}) a "),
                        html.B(f"{_num_cl(e['dist_m'])} m"),
                        html.Span(f" del centroide de {s['display']}; margen "
                                  f"{_num_cl(e['umbral_m'])} m."),
                        html.Br(),
                        html.Span(f"Centroide: E {_num_cl(e['este'],1)} · N {_num_cl(e['norte'],1)}",
                                  style={"color": "#888", "fontFamily": "monospace"})],
                       style={"fontSize": "10px"}),
            html.Div([
                dbc.Button("Cargar igual (confirmo)", id={"type": "site-confirm", "index": e["token"]},
                           size="sm", color="danger", outline=True, style={"fontSize": "10px"}),
                dbc.Button("Descartar", id={"type": "site-discard", "index": e["token"]},
                           size="sm", color="secondary", outline=True,
                           style={"fontSize": "10px", "marginLeft": "6px"}),
            ], className="mt-1"),
        ], style={"background": "transparent", "borderBottom": "1px solid #222", "padding": "6px 8px"}))
    sitio_body = sitio_rows or [html.Small(
        f"Nada fuera de la envolvente de {s['display']}. ✅",
        style={"color": "#666", "fontSize": "10px"})]

    # ── Bloqueadores de entrenamiento (T1.5) ─────────────────────────────────
    bl = training_blockers()
    if bl:
        bloq_body = [dbc.Alert(training_block_message(bl), color="danger",
                               style={"fontSize": "10px", "padding": "6px 10px"})]
    else:
        bloq_body = [html.Small("Ningún atributo bloquea el entrenamiento. ✅",
                                style={"color": "#666", "fontSize": "10px"})]

    # ── Traslapes (T1.4) ─────────────────────────────────────────────────────
    ov = overlap_stats
    if ov.get("n_puntos"):
        filas = [html.Small(f"· {m}: {n} pts", style={"fontSize": "10px", "display": "block",
                                                       "color": "#E74C3C"})
                 for m, n in sorted(ov["motivos"].items(), key=lambda kv: -kv[1])]
        casos = [html.Small(f"  {c} → {n} pts", style={"fontSize": "9px", "display": "block",
                                                        "color": "#888", "fontFamily": "monospace"})
                 for c, n in sorted(ov["casos"].items(), key=lambda kv: -kv[1])[:8]]
        ov_body = [html.Small([
            f"{ov['n_puntos']} puntos clasificados · ",
            html.B(f"{ov['n_ambiguos']} excluidos por Conflicto",
                   style={"color": "#E74C3C" if ov["n_ambiguos"] else "#aaa"}),
            f" · {ov.get('n_compuestos', 0)} compuestos (litología+alteración)"
            f" · {ov['n_subunidad_gana']} por Anidamiento"
            f" · {ov['n_sin_lito']} sin litología"
            f" · {ov.get('n_sin_clasificar', 0)} sin clasificar.",
        ], style={"fontSize": "10px", "display": "block", "marginBottom": "4px"})] + filas + casos
    else:
        ov_body = [html.Small("Sin clasificación ejecutada todavía.",
                              style={"color": "#666", "fontSize": "10px"})]

    # ── Matriz de traslape de bandas UCS, ambos criterios (P1c-B.7) ─────────
    # NO es la resolución geométrica de arriba (esa es sobre puntos MWD contra
    # mallas DXF, A.5). Esta es entre las BANDAS de UCS de las litologías: qué
    # tan bien separadas están las etiquetas que el modelo tiene que aprender
    # a distinguir. Se reportan los DOS criterios lado a lado, nunca uno solo:
    # dan panoramas distintos y la diferencia es el hallazgo.
    ucs_ov = ucs_band_overlap_report()

    def _fmt_par(p):
        ra, rb = p["rango_a"], p["rango_b"]
        return html.Small(
            f"{p['a']} [{ra[0]:g}–{ra[1]:g}]  ↔  {p['b']} [{rb[0]:g}–{rb[1]:g}]",
            style={"fontSize": "9px", "display": "block", "color": "#E74C3C",
                   "fontFamily": "monospace"})

    ucs_ov_body = [
        html.Small(
            "Bandas de UCS entre litologías con etiqueta utilizable. La banda de "
            "confianza es sobre el valor central; la dispersión es la variabilidad "
            "OBSERVADA del material — pueden dar panoramas distintos (B.7).",
            style={"color": "#888", "fontSize": "9px", "display": "block", "marginBottom": "6px"}),
        dbc.Row([
            dbc.Col([
                html.Small(f"Banda de confianza — {len(ucs_ov['confianza'])} par(es)",
                          style={"color": "#aaa", "fontSize": "10px", "fontWeight": "bold",
                                 "display": "block", "marginBottom": "2px"}),
            ] + ([_fmt_par(p) for p in ucs_ov["confianza"]] or
                 [html.Small("Sin traslapes.", style={"color": "#5DCAA5", "fontSize": "9px"})]),
                   width=6),
            dbc.Col([
                html.Small(f"Dispersión observada — {len(ucs_ov['dispersion'])} par(es)",
                          style={"color": "#aaa", "fontSize": "10px", "fontWeight": "bold",
                                 "display": "block", "marginBottom": "2px"}),
            ] + ([_fmt_par(p) for p in ucs_ov["dispersion"]] or
                 [html.Small("Sin traslapes.", style={"color": "#5DCAA5", "fontSize": "9px"})]),
                   width=6),
        ], className="g-2"),
    ]

    return [
        dbc.Alert([
            html.B(f"Sitio activo: {s['display']} ({s['id']})"), html.Br(),
            html.Small(f"Envolvente UTM · Este {_num_cl(s['este_min'])}–{_num_cl(s['este_max'])} · "
                       f"Norte {_num_cl(s['norte_min'])}–{_num_cl(s['norte_max'])} · "
                       f"margen {_num_cl(s['margen_m'])} m. "
                       "Las coordenadas son la autoridad de pertenencia al sitio: "
                       "ni el nombre del archivo ni este desplegable.",
                       style={"fontSize": "10px"}),
        ], color="dark", style={"fontSize": "11px", "padding": "8px 12px"}),

        card(f"🚫 Objetos fuera de sitio ({len(site_pending_confirms)})",
             [dbc.ListGroup(sitio_body, flush=True)]),
        card(f"⛔ Bloqueadores de entrenamiento ({len(bl)})", bloq_body),
        card(f"🏷 Pendientes de asignar ({pending_alias_count()})",
             [html.Small("Todo texto de capa DXF o sondaje que no resuelve a un atributo "
                         "canónico aparece aquí. Un alias apunta a exactamente un atributo.",
                         style={"color": "#888", "fontSize": "10px", "display": "block",
                                "marginBottom": "6px"}),
              dbc.ListGroup(pend_body, flush=True)]),
        card("🔀 Resolución de traslapes (último cruce)", ov_body),
        card("📊 Matriz de traslape de bandas UCS", ucs_ov_body),

        card(f"📖 Atributos — unidades ({len(unidades)})",
             [dbc.ListGroup([_attr_row(a) for a in sorted(unidades, key=lambda x: x.id)], flush=True)]),
        card(f"📖 Atributos — subunidades ({len(subunidades)})",
             [dbc.ListGroup([_attr_row(a) for a in sorted(subunidades, key=lambda x: x.id)], flush=True)]),

        card(f"🔗 Alias registrados ({len(alias_registry)})", [
            dbc.ListGroup([
                dbc.ListGroupItem(dbc.Row([
                    dbc.Col(html.Small(
                        [html.B(al.texto_crudo), " → ",
                         " + ".join(f"{r}:{a}" for r, a in sorted(al.atributos.items())),
                         dbc.Badge("compuesto", color="info", className="ms-1",
                                   style={"fontSize": "8px"}) if al.es_compuesto() else None,
                         html.Span(f"  ({al.origen})", style={"color": "#888"})],
                        style={"fontSize": "10px"}), width=10),
                    dbc.Col(dbc.Button("✕", id={"type": "alias-del", "index": key}, size="sm",
                                       color="link", style={"fontSize": "10px", "padding": 0}), width=2),
                ], className="g-1 align-items-center"),
                    style={"background": "transparent", "borderBottom": "1px solid #1a1a1a",
                           "padding": "3px 8px"})
                for key, al in sorted(alias_registry.items())
            ], flush=True, style={"maxHeight": "220px", "overflowY": "auto"}),
            html.Hr(style={"margin": "8px 0"}),
            dbc.Row([
                dbc.Col(dbc.Input(id="alias-new-text", placeholder="Texto crudo…", size="sm",
                                  style={"fontSize": "10px"}), width=5),
                dbc.Col(dcc.Dropdown(id="alias-new-attr", options=attr_opts,
                                     placeholder="Atributo…", style={"fontSize": "10px"}), width=5),
                dbc.Col(dbc.Button("+", id="btn-alias-add", size="sm", color="info",
                                   outline=True, style={"fontSize": "11px"}), width=2),
            ], className="g-1"),
        ]),

        card("💾 Persistencia del registro", [
            html.Small("Exporta atributos + alias + exclusiones justificadas. "
                       "Legible por humanos, versionable y publicable como anexo de la memoria.",
                       style={"color": "#888", "fontSize": "10px", "display": "block",
                              "marginBottom": "6px"}),
            dbc.Row([
                dbc.Col(dbc.Button("⬇ JSON", id="btn-vocab-json", size="sm", color="info",
                                   outline=True, style={"fontSize": "10px"}), width="auto"),
                dbc.Col(dbc.Button("⬇ CSV", id="btn-vocab-csv", size="sm", color="info",
                                   outline=True, style={"fontSize": "10px"}), width="auto"),
            ], className="g-2"),
            # El uploader vive DENTRO del panel: revelarlo desde la raíz lo
            # dejaría detrás del modal, invisible para el usuario.
            dcc.Upload(id="up-vocab", multiple=False, accept=".json",
                       children=html.Span("⬆ Importar: suelta aquí el .json (o haz clic)"),
                       style={"border": "1px dashed #3B8BD4", "borderRadius": "5px",
                              "padding": "10px", "textAlign": "center", "cursor": "pointer",
                              "marginTop": "8px", "fontSize": "10px", "color": "#3B8BD4"}),
            html.Small("Importar REEMPLAZA el registro actual (atributos, alias y "
                       "exclusiones). Exporta antes si quieres conservarlo.",
                       style={"color": "#888", "fontSize": "9px", "display": "block",
                              "marginTop": "4px"}),
        ]),
    ]


@app.callback(Output("vocab-badge", "children"), Input("refresh", "data"))
def render_vocab_badge(_):
    return _vocab_badge_children()


@app.callback(Output("varjust-modal", "is_open"), Output("varjust-modal-body", "children"),
              Input("btn-open-varjust", "n_clicks"), Input("close-varjust", "n_clicks"),
              State("varjust-modal", "is_open"), prevent_initial_call=True)
def toggle_varjust_modal(open_c, close_c, is_open):
    trig = callback_context.triggered_id
    if trig == "btn-open-varjust":
        return True, _varjust_panel_body()
    if trig == "close-varjust":
        return False, no_update
    return no_update, no_update


@app.callback(Output("vocab-modal", "is_open"), Output("vocab-modal-body", "children"),
              Input("btn-open-vocab", "n_clicks"), Input("close-vocab", "n_clicks"),
              Input("btn-open-vocab-step1", "n_clicks"), Input("refresh", "data"),
              State("vocab-modal", "is_open"), prevent_initial_call=True)
def toggle_vocab_modal(open_c, close_c, open_c1, _ref, is_open):
    trig = callback_context.triggered_id
    if trig in ("btn-open-vocab", "btn-open-vocab-step1"): return True, _vocab_panel_body()
    if trig == "close-vocab": return False, no_update
    # refresh mientras está abierto → recomponer el cuerpo sin cerrarlo
    return (no_update, _vocab_panel_body()) if is_open else (no_update, no_update)


@app.callback(Output("refresh", "data", allow_duplicate=True),
              Output("toast", "children", allow_duplicate=True),
              Output("toast", "is_open", allow_duplicate=True),
              Input({"type": "attr-num", "attr": ALL, "field": ALL}, "value"),
              State({"type": "attr-num", "attr": ALL, "field": ALL}, "id"),
              State("refresh", "data"), prevent_initial_call=True)
def on_attr_num(values, ids, ref):
    """
    Campos numéricos del registro. Todo valor fuera de los límites físicos de
    UCS se RECHAZA con mensaje visible (T1.6): nunca se sustituye ni se ignora
    en silencio.
    """
    lo_f, hi_f = UCS_CONFIG["physical_min"], UCS_CONFIG["physical_max"]
    changed, rechazados = False, []
    for val, id_d in zip(values, ids):
        a = attr_registry.get(id_d["attr"])
        if a is None: continue
        f = id_d["field"]
        if val is None or val == "":
            if getattr(a, f) is not None:
                setattr(a, f, None); changed = True
            continue
        try: x = float(val)
        except (TypeError, ValueError):
            rechazados.append(f"{a.id}.{f}: «{val}» no es número."); continue
        if not np.isfinite(x):
            rechazados.append(f"{a.id}.{f}: valor no finito."); continue
        if f in ("ucs_min", "ucs_max", "ucs_media", "ucs_central",
                 "dispersion_min", "dispersion_max") and not (lo_f <= x <= hi_f):
            rechazados.append(f"{a.id}.{f}: {x:g} MPa fuera del rango físico "
                              f"[{lo_f:g}, {hi_f:g}]."); continue
        if f == "ucs_n": x = int(x)
        if getattr(a, f) != x:
            setattr(a, f, x); changed = True
    if rechazados:
        return ref + 1, "🚫 Valor NO aplicado: " + " · ".join(rechazados), True
    if changed:
        build_domain_index()
        return ref + 1, no_update, no_update
    return no_update, no_update, no_update


@app.callback(Output("refresh", "data", allow_duplicate=True),
              Input({"type": "attr-calidad", "attr": ALL}, "value"),
              Input({"type": "attr-txt", "attr": ALL, "field": ALL}, "value"),
              State({"type": "attr-calidad", "attr": ALL}, "id"),
              State({"type": "attr-txt", "attr": ALL, "field": ALL}, "id"),
              State("refresh", "data"), prevent_initial_call=True)
def on_attr_meta(cal_vals, txt_vals, cal_ids, txt_ids, ref):
    changed = False
    for v, i in zip(cal_vals, cal_ids):
        a = attr_registry.get(i["attr"])
        if a is not None and v is not None and a.calidad != int(v):
            a.calidad = int(v); changed = True
    for v, i in zip(txt_vals, txt_ids):
        a = attr_registry.get(i["attr"])
        if a is not None and getattr(a, i["field"]) != (v or ""):
            setattr(a, i["field"], v or ""); changed = True
    if not changed: return no_update
    build_domain_index()
    return ref + 1


@app.callback(Output("refresh", "data", allow_duplicate=True),
              Output("toast", "children", allow_duplicate=True),
              Output("toast", "is_open", allow_duplicate=True),
              Input({"type": "attr-excl-btn", "attr": ALL}, "n_clicks"),
              State({"type": "attr-excl-just", "attr": ALL}, "value"),
              State({"type": "attr-excl-just", "attr": ALL}, "id"),
              State("refresh", "data"), prevent_initial_call=True)
def on_attr_exclude(clicks, justs, just_ids, ref):
    """Excluir / reincluir un atributo. La exclusión EXIGE justificación."""
    trig = callback_context.triggered_id
    if not isinstance(trig, dict) or not any(c for c in clicks if c):
        return no_update, no_update, no_update
    aid = trig["attr"]
    if aid in attribute_exclusions:
        unexclude_attribute(aid)
        build_domain_index()
        return ref + 1, f"↩ «{aid}» reincluido en el entrenamiento.", True
    just = next((v for v, i in zip(justs, just_ids) if i["attr"] == aid), None)
    try:
        exclude_attribute(aid, just)
    except ValueError:
        return no_update, (f"🚫 No se excluyó «{aid}»: la exclusión requiere una "
                           f"justificación explícita escrita en el campo."), True
    except KeyError as e:
        return no_update, f"🚫 {e}", True
    build_domain_index()
    return ref + 1, f"✅ «{aid}» excluido del entrenamiento. Justificación registrada.", True


@app.callback(Output("refresh", "data", allow_duplicate=True),
              Output("toast", "children", allow_duplicate=True),
              Output("toast", "is_open", allow_duplicate=True),
              Input({"type": "pend-assign", "index": ALL}, "value"),
              State({"type": "pend-assign", "index": ALL}, "id"),
              State("refresh", "data"), prevent_initial_call=True)
def on_pending_assign(values, ids, ref):
    """
    Asigna un texto pendiente a uno o varios atributos canónicos de ROLES
    DISTINTOS (el dropdown es multi). Dos del mismo rol → error visible.
    """
    trig = callback_context.triggered_id
    if not isinstance(trig, dict): return no_update, no_update, no_update
    val = callback_context.triggered[0]["value"]
    if not val: return no_update, no_update, no_update
    if isinstance(val, str): val = [val]
    key = trig["index"]
    e = pending_aliases.get(key)
    if not e: return no_update, no_update, no_update
    try:
        al = register_alias(e["texto_crudo"], val, sorted(e["origenes"])[0])
    except AliasConflict as exc:
        return no_update, f"🚫 {exc}", True
    except (KeyError, ValueError) as exc:
        return no_update, f"🚫 {exc}", True
    _propagate_alias_to_layers(key, al.atributos)
    build_domain_index()
    det = " + ".join(f"{r}:{a}" for r, a in sorted(al.atributos.items()))
    return ref + 1, f"✅ «{e['texto_crudo']}» → {det}.", True


def _propagate_alias_to_layers(key_norm: str, atributos: Dict[str, str]):
    """Aplica un alias recién registrado a las capas que llevaban ese texto."""
    for lay in layers.values():
        if not lay.atributos and _norm_txt(lay.name) == key_norm:
            set_layer_attributes(lay, atributos)


@app.callback(Output("refresh", "data", allow_duplicate=True),
              Output("toast", "children", allow_duplicate=True),
              Output("toast", "is_open", allow_duplicate=True),
              Input({"type": "pend-confirm-prop", "index": ALL}, "n_clicks"),
              State("refresh", "data"), prevent_initial_call=True)
def on_confirm_proposal(clicks, ref):
    """
    (A.3) Confirma la descomposición PROPUESTA para un nombre compuesto. Solo
    aquí se acepta: la propuesta nunca se aplica sola. Una vez confirmada, el
    string crudo completo queda como alias propio y la próxima vez resuelve
    directo, sin volver a descomponer.
    """
    trig = callback_context.triggered_id
    if not isinstance(trig, dict) or not any(c for c in clicks if c):
        return no_update, no_update, no_update
    key = trig["index"]
    e = pending_aliases.get(key)
    if not e: return no_update, no_update, no_update
    try:
        al = confirm_composite_alias(e["texto_crudo"], sorted(e["origenes"])[0])
    except (AliasConflict, KeyError, ValueError) as exc:
        return no_update, f"🚫 {exc}", True
    _propagate_alias_to_layers(key, al.atributos)
    build_domain_index()
    det = " + ".join(f"{r}:{a}" for r, a in sorted(al.atributos.items()))
    return ref + 1, (f"✅ Composición confirmada: «{al.texto_crudo}» → {det}. "
                     f"Queda almacenada como alias propio."), True


@app.callback(Output("refresh", "data", allow_duplicate=True),
              Output("toast", "children", allow_duplicate=True),
              Output("toast", "is_open", allow_duplicate=True),
              Input("btn-alias-add", "n_clicks"),
              State("alias-new-text", "value"), State("alias-new-attr", "value"),
              State("refresh", "data"), prevent_initial_call=True)
def on_alias_add(n, texto, aid, ref):
    if not n: return no_update, no_update, no_update
    if not texto or not aid:
        return no_update, "🚫 Alias: falta el texto crudo o el atributo destino.", True
    if isinstance(aid, str): aid = [aid]
    try:
        al = register_alias(texto, aid, "manual")
    except AliasConflict as e:
        return no_update, f"🚫 {e}", True
    except (KeyError, ValueError) as e:
        return no_update, f"🚫 {e}", True
    det = " + ".join(f"{r}:{a}" for r, a in sorted(al.atributos.items()))
    return ref + 1, f"✅ Alias «{texto}» → {det}.", True


@app.callback(Output("refresh", "data", allow_duplicate=True),
              Input({"type": "alias-del", "index": ALL}, "n_clicks"),
              State("refresh", "data"), prevent_initial_call=True)
def on_alias_del(clicks, ref):
    trig = callback_context.triggered_id
    if not isinstance(trig, dict) or not any(c for c in clicks if c): return no_update
    alias_registry.pop(trig["index"], None)
    return ref + 1


@app.callback(Output("refresh", "data", allow_duplicate=True),
              Output("toast", "children", allow_duplicate=True),
              Output("toast", "is_open", allow_duplicate=True),
              Input({"type": "site-confirm", "index": ALL}, "n_clicks"),
              Input({"type": "site-discard", "index": ALL}, "n_clicks"),
              State("refresh", "data"), prevent_initial_call=True)
def on_site_decision(conf_clicks, disc_clicks, ref):
    trig = callback_context.triggered_id
    if not isinstance(trig, dict): return no_update, no_update, no_update
    if not callback_context.triggered[0]["value"]:
        return no_update, no_update, no_update
    tok = trig["index"]
    if trig["type"] == "site-confirm":
        confirm_site_token(tok)
        return ref + 1, (f"⚠ «{tok}» aceptado fuera de la envolvente del sitio. "
                         f"Vuelve a cargar el archivo para que entre."), True
    discard_site_token(tok)
    return ref + 1, f"🗑 «{tok}» descartado.", True


@app.callback(Output("download", "data", allow_duplicate=True),
              Input("btn-vocab-json", "n_clicks"), Input("btn-vocab-csv", "n_clicks"),
              prevent_initial_call=True)
def on_vocab_export(n_json, n_csv):
    trig = callback_context.triggered_id
    stamp = time.strftime("%Y%m%d_%H%M")
    if trig == "btn-vocab-json" and n_json:
        return dict(content=export_vocabulary_json(),
                    filename=f"vocabulario_{ACTIVE_SITE}_{stamp}.json")
    if trig == "btn-vocab-csv" and n_csv:
        return dict(content=export_vocabulary_csv(),
                    filename=f"vocabulario_{ACTIVE_SITE}_{stamp}.csv")
    return no_update


@app.callback(Output("refresh", "data", allow_duplicate=True),
              Output("toast", "children", allow_duplicate=True),
              Output("toast", "is_open", allow_duplicate=True),
              Input("up-vocab", "contents"), State("up-vocab", "filename"),
              State("refresh", "data"), prevent_initial_call=True)
def on_vocab_import(content, fname, ref):
    if not content: return no_update, no_update, no_update
    try:
        _, b64 = content.split(",", 1)
        res = import_vocabulary(base64.b64decode(b64).decode("utf-8"), replace=True)
    except Exception as e:
        return no_update, f"🚫 Importación fallida: {e}", True
    build_domain_index()
    msg = (f"✅ Vocabulario importado: {res['atributos']} atributos · "
           f"{res['alias']} alias · {res['exclusiones']} exclusiones.")
    if res["errores"]:
        msg += f" ⚠ {len(res['errores'])} problema(s): " + " · ".join(res["errores"][:4])
    return ref + 1, msg, True


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  P2-T2.6 — PANEL DE SONDAJES                                            ║
# ║  Lista con casillas, ordenable, estado del cruce, métricas por pozo,    ║
# ║  reparto espacial y anulación manual en ambos sentidos.                 ║
# ╚══════════════════════════════════════════════════════════════════════════╝

_DH_SORT_FIELDS = [
    ("holeid", "Hole ID"), ("banda", "Banda"), ("estado", "Estado"),
    ("metros_dentro", "Metros dentro"), ("n_estructuras", "N° estructuras"),
    ("rqd_mediana", "RQD mediana"), ("rmr_mediana", "RMR mediana"),
    ("dist_min_m", "Distancia mín."),
]
_DH_ESTADO_COLOR = {"intersecta": "success", "cercano": "warning", "lejano": "secondary"}
_DH_ESTADO_LABEL = {"intersecta": "Intersecta", "cercano": "Cercano", "lejano": "Lejano"}


def _dh_sort_key(dh, field):
    """Los None quedan siempre al final, sea cual sea el orden (asc/desc)."""
    v = getattr(dh, field, None)
    return (v is None, v if v is not None else "")


def _dh_badge_children():
    if not drillholes:
        return dbc.Button("🗿 Sondajes", id="btn-open-drillhole", color="link", size="sm",
                          disabled=True, style={"padding": "0", "fontSize": "10px",
                                                "textDecoration": "none", "color": "#555"})
    n_sel = sum(1 for dh in drillholes.values() if dh.seleccionado())
    return dbc.Button(
        dbc.Badge(f"🗿 {n_sel}/{len(drillholes)} sondajes", color="secondary",
                 style={"fontSize": "10px"}),
        id="btn-open-drillhole", color="link", size="sm",
        style={"padding": "0", "textDecoration": "none"})


@app.callback(Output("drillhole-badge", "children"), Input("refresh", "data"))
def render_drillhole_badge(_):
    return _dh_badge_children()


def _dh_row(dh: DrillHole):
    sel = dh.seleccionado()
    manual = dh.seleccion_manual is not None
    mpu = " · ".join(f"{u} {m:.1f}m"
                     for u, m in sorted(dh.metros_por_unidad.items(), key=lambda kv: -kv[1])[:4])
    if dh.estado == "intersecta":
        detalle = f"{dh.metros_dentro:.1f} m dentro"
    elif dh.dist_min_m is not None:
        detalle = f"{_num_cl(dh.dist_min_m, 1)} m a «{dh.malla_cercana}»"
    else:
        detalle = "sin mallas de referencia cargadas"
    return dbc.ListGroupItem([
        dbc.Row([
            dbc.Col(dbc.Checkbox(id={"type": "dh-sel", "index": dh.holeid}, value=sel),
                    width="auto"),
            dbc.Col(html.Div([
                html.B(dh.holeid, style={"fontSize": "11px"}),
                html.Span(f"  {dh.banda or '—'}", style={"color": "#888", "fontSize": "10px"}),
                dbc.Badge(_DH_ESTADO_LABEL.get(dh.estado, "sin mallas"),
                         color=_DH_ESTADO_COLOR.get(dh.estado, "dark"),
                         className="ms-1", style={"fontSize": "9px"}),
                dbc.Badge("✎ manual", color="info", className="ms-1",
                         style={"fontSize": "9px"}) if manual else None,
                dbc.Button("↺", id={"type": "dh-clear-override", "index": dh.holeid}, size="sm",
                          color="link", style={"fontSize": "10px", "padding": "0 0 0 4px"}
                          ) if manual else None,
            ]), width=True),
        ], className="g-1 align-items-center"),
        html.Small(f"{detalle} · {dh.n_estructuras} estruct."
                  + (f" · RQD {dh.rqd_mediana:.0f}" if dh.rqd_mediana is not None else "")
                  + (f" · RMR {dh.rmr_mediana:.0f}" if dh.rmr_mediana is not None else ""),
                  style={"color": "#888", "fontSize": "9px", "display": "block", "marginLeft": "26px"}),
        html.Small(mpu, style={"color": "#666", "fontSize": "9px", "display": "block",
                              "marginLeft": "26px"}) if mpu else None,
    ], style={"background": "transparent", "borderBottom": "1px solid #222", "padding": "6px 8px"})


def _drillhole_panel_body(sort_field="holeid", desc=False):
    if not drillholes:
        return [dbc.Alert(
            "Sin sondajes cargados. Sube los seis CSV (header, survey, lithology, "
            "structure, geomec y density; nombres tolerantes, p.ej. 'MPC_header.csv').",
            color="dark", style={"fontSize": "11px"})]

    holes = sorted(drillholes.values(), key=lambda dh: _dh_sort_key(dh, sort_field), reverse=desc)
    n_sel = sum(1 for dh in drillholes.values() if dh.seleccionado())
    n_int = sum(1 for dh in drillholes.values() if dh.estado == "intersecta")
    n_cer = sum(1 for dh in drillholes.values() if dh.estado == "cercano")
    n_lej = sum(1 for dh in drillholes.values() if dh.estado == "lejano")
    n_none = sum(1 for dh in drillholes.values() if dh.estado is None)

    band_rows = []
    for lbl in ("Sur", "Centro", "Norte"):
        b = spatial_bands.get(lbl)
        if not b: continue
        cota = (f"{b['cota_min']:.0f}–{b['cota_max']:.0f}" if b["cota_min"] is not None else "—")
        band_rows.append(html.Small(
            f"{lbl}: {b['n_pozos']} pozos · {b['m_litologia']:.1f} m litología · "
            f"{b['n_estructuras']} estructuras · cota {cota}",
            style={"display": "block", "fontSize": "10px", "color": "#aaa"}))

    return [
        dbc.Alert([
            html.B(f"{len(drillholes)} sondajes cargados · {n_sel} seleccionados"), html.Br(),
            html.Small(
                f"Intersecta {n_int} · Cercano {n_cer} · Lejano {n_lej}"
                + (f" · sin mallas de referencia {n_none}" if n_none else ""),
                style={"fontSize": "10px", "color": "#aaa"}),
        ], color="dark", style={"fontSize": "11px", "padding": "8px 12px"}),
        card("Reparto espacial (tercios geométricos norte-sur)", band_rows or [
            html.Small("Sin traza calculada todavía.", style={"color": "#666", "fontSize": "10px"})]),
        card("Cruce traza↔malla", [
            html.Small("Contra las mallas de litología cargadas (representan caserones/"
                      "dominios). Los pozos cercanos no seleccionan por defecto, pero "
                      "siguen siendo útiles para la interpolación al modelo de bloques.",
                      style={"color": "#888", "fontSize": "10px", "display": "block",
                             "marginBottom": "6px"}),
            dbc.Row([
                dbc.Col([html.Small("Umbral 'cercano' [m]", style={"color": "#888", "display": "block"}),
                        dbc.Input(id="dh-near-input", type="number", value=DRILLHOLE_NEAR_DISTANCE_M,
                                  step=1, size="sm", style={"fontSize": "11px"})], width=4),
                dbc.Col(dbc.Button("🔄 Recalcular selección", id="btn-dh-recalc", color="info",
                                   outline=True, size="sm", className="mt-4"), width="auto"),
            ], className="g-2"),
        ]),
        card("Pozos", [
            dbc.Row([
                dbc.Col([html.Small("Ordenar por", style={"color": "#888", "display": "block"}),
                        dcc.Dropdown(id="dh-sort-field",
                                    options=[{"label": l, "value": k} for k, l in _DH_SORT_FIELDS],
                                    value=sort_field, clearable=False,
                                    style={"fontSize": "10px"})], width=8),
                dbc.Col([html.Small("Orden", style={"color": "#888", "display": "block"}),
                        dbc.Checklist(id="dh-sort-desc", options=[{"label": " desc", "value": 1}],
                                     value=[1] if desc else [], switch=True,
                                     style={"fontSize": "10px"})], width=4),
            ], className="g-2 mb-2"),
            dbc.ListGroup([_dh_row(dh) for dh in holes], flush=True,
                         style={"maxHeight": "340px", "overflowY": "auto"}),
        ]),
    ]


@app.callback(Output("drillhole-modal", "is_open"), Output("drillhole-modal-body", "children"),
              Input("btn-open-drillhole", "n_clicks"), Input("btn-open-drillhole-step1", "n_clicks"),
              Input("close-drillhole", "n_clicks"), Input("refresh", "data"),
              Input("dh-sort-field", "value"), Input("dh-sort-desc", "value"),
              State("drillhole-modal", "is_open"), prevent_initial_call=True)
def toggle_drillhole_modal(open_c, open_c1, close_c, _ref, sort_field, sort_desc, is_open):
    trig = callback_context.triggered_id
    if trig in ("btn-open-drillhole", "btn-open-drillhole-step1"):
        return True, _drillhole_panel_body(sort_field or "holeid", bool(sort_desc))
    if trig == "close-drillhole":
        return False, no_update
    if is_open:
        return no_update, _drillhole_panel_body(sort_field or "holeid", bool(sort_desc))
    return no_update, no_update


@app.callback(
    Output("refresh", "data", allow_duplicate=True),
    Output("toast", "children", allow_duplicate=True),
    Output("toast", "is_open", allow_duplicate=True),
    Input("up-drillhole", "contents"), State("up-drillhole", "filename"),
    State("refresh", "data"), prevent_initial_call=True,
)
def on_drillhole_upload(contents_list, filenames, ref):
    """
    (T2.1) Sube hasta seis CSV a la vez; el kind de cada uno se adivina por
    el nombre de archivo (guess_drillhole_kind). Un archivo no reconocible se
    reporta, no se descarta en silencio. Al terminar de cargar, corre el
    pipeline completo (T2.2-T2.5) automáticamente.
    """
    if not contents_list: return no_update, no_update, no_update
    files, no_reconocidos, errs = {}, [], []
    for content, fname in zip(contents_list, filenames):
        kind = guess_drillhole_kind(fname)
        if kind is None:
            no_reconocidos.append(fname); continue
        try:
            _, b64 = content.split(",", 1)
            files[kind] = base64.b64decode(b64)
        except Exception as e:
            errs.append(f"{fname}: {e}")
    try:
        res = load_drillhole_csvs(files)
    except Exception as e:
        return no_update, f"🚫 No se pudieron cargar los sondajes: {e}", True
    refresh_drillhole_selection()
    parts = [f"✅ {res['holes']} sondajes cargados"]
    if res["faltantes"]: parts.append(f"sin {', '.join(res['faltantes'])}")
    if no_reconocidos: parts.append(f"sin reconocer: {', '.join(no_reconocidos)}")
    n_warn = len(res["warnings"])
    if n_warn: parts.append(f"{n_warn} advertencia(s) — ver panel de sondajes")
    if errs: parts.append(f"Err: {'; '.join(errs)}")
    return ref + 1, " · ".join(parts), True


@app.callback(
    Output("refresh", "data", allow_duplicate=True),
    Output("toast", "children", allow_duplicate=True),
    Output("toast", "is_open", allow_duplicate=True),
    Input("btn-dh-recalc", "n_clicks"), State("dh-near-input", "value"),
    State("refresh", "data"), prevent_initial_call=True,
)
def on_drillhole_recalc(n, near_v, ref):
    if not n: return no_update, no_update, no_update
    if not drillholes:
        return no_update, "🚫 No hay sondajes cargados.", True
    try:
        near_m = float(near_v) if near_v not in (None, "") else DRILLHOLE_NEAR_DISTANCE_M
    except (TypeError, ValueError):
        return no_update, f"🚫 Umbral 'cercano' inválido: «{near_v}».", True
    refresh_drillhole_selection(near_m=near_m)
    n_int = sum(1 for dh in drillholes.values() if dh.estado == "intersecta")
    n_cer = sum(1 for dh in drillholes.values() if dh.estado == "cercano")
    n_lej = sum(1 for dh in drillholes.values() if dh.estado == "lejano")
    return (ref + 1,
           f"✅ Cruce recalculado (umbral {near_m:g} m): {n_int} intersecta · "
           f"{n_cer} cercano · {n_lej} lejano.", True)


@app.callback(Output("refresh", "data", allow_duplicate=True),
              Input({"type": "dh-sel", "index": ALL}, "value"),
              State({"type": "dh-sel", "index": ALL}, "id"),
              State("refresh", "data"), prevent_initial_call=True)
def on_drillhole_select(values, ids, ref):
    """
    (T2.6) Anulación manual en ambos sentidos: marcar o desmarcar una casilla
    fija `seleccion_manual` explícitamente, y esa marca sobrevive a un
    recálculo del cruce (refresh_drillhole_selection no la toca).
    """
    trig = callback_context.triggered_id
    if not isinstance(trig, dict): return no_update
    hid = trig["index"]
    dh = drillholes.get(hid)
    if dh is None: return no_update
    val = callback_context.triggered[0]["value"]
    dh.seleccion_manual = bool(val)
    return ref + 1


@app.callback(Output("refresh", "data", allow_duplicate=True),
              Input({"type": "dh-clear-override", "index": ALL}, "n_clicks"),
              State("refresh", "data"), prevent_initial_call=True)
def on_drillhole_clear_override(clicks, ref):
    """Revierte una anulación manual a la selección automática (por estado)."""
    trig = callback_context.triggered_id
    if not isinstance(trig, dict) or not any(c for c in clicks if c): return no_update
    dh = drillholes.get(trig["index"])
    if dh is None: return no_update
    dh.seleccion_manual = None
    return ref + 1


@app.callback(
    Output("wz-content","children"), Output("pills-bar","children"),
    Input("active-step","data"), Input("refresh","data"),
)
def render_wizard(step, _):
    """
    Contenido del wizard y barra de pasos. Deliberadamente SEPARADO del
    callback de la figura 3D: cambiar de paso (o cargar datos) NO debe
    reconstruir el viewport, así la cámara y el estado de visibilidad de
    capas/pozos permanecen intactos.
    """
    renderers = {1:_step1,2:_step2,3:_step3,4:_step4,5:_step5}
    content = renderers.get(step, _step1)()
    pills = step_pills(step)
    return content, pills

@app.callback(
    Output("layer-tree","children"),
    Output("center-info","children"),
    Input("refresh","data"),
)
def render_layer_tree(_):
    """
    Árbol de capas/pozos con sus checkboxes de visibilidad. Se regenera solo
    cuando cambian los datos (nueva capa, nuevo pozo, UCS asignado) — NO cada
    vez que se togglea un checkbox, para no perder el estado del propio
    checkbox que el usuario acaba de clickear.
    """
    tree = _layer_tree()
    ct = f"Centro: N={global_center['norte']:.0f} E={global_center['este']:.0f} Z={global_center['cota']:.0f}" if global_center else ""
    return tree, ct

@app.callback(
    Output("viewport-3d","figure"),
    Input("refresh","data"), Input("color-by","value"),
    Input({"type":"vis-layer","index":ALL},"value"),
    Input({"type":"vis-well","index":ALL},"value"),
    State({"type":"vis-layer","index":ALL},"id"),
    State({"type":"vis-well","index":ALL},"id"),
)
def render_viewport(_, color_by, layer_vis_vals, well_vis_vals, layer_ids, well_ids):
    """
    Único callback que toca la figura 3D. Se dispara solo cuando cambian datos
    (refresh), el color, o los checkboxes de visibilidad — nunca al navegar
    entre pasos del wizard. uirevision="viewport" (fijo) preserva cámara.
    """
    hidden_layers = {lid["index"] for lid, v in zip(layer_ids, layer_vis_vals) if not v}
    hidden_wells  = {wid["index"] for wid, v in zip(well_ids,  well_vis_vals)  if not v}
    fig = build_3d_figure(color_by, hidden_layers, hidden_wells)
    return fig

def _layer_tree():
    items = []
    caseron_opts = [{"label": c, "value": c} for c in excel_caserones()]
    lito_opts = [{"label": l, "value": l} for l in excel_litologias()]
    for i, (name, layer) in enumerate(layers.items()):
        ucs_badge = dbc.Badge(f"{layer.ucs_lab} MPa", color="success", className="ms-1") \
                    if layer.ucs_lab else dbc.Badge("sin UCS", color="secondary", className="ms-1")
        band_badge = dbc.Badge(f"banda {layer.ucs_lo:.0f}–{layer.ucs_hi:.0f}", color="info",
                               className="ms-1") if layer.ucs_lo is not None and layer.ucs_hi is not None else None
        layer_children = [
            html.Div([
                dbc.Checkbox(id={"type":"vis-layer","index":name}, value=True,
                             style={"display":"inline-block","marginRight":"6px"}),
                html.Small([html.Span("●",style={"color":PALETTE[i%len(PALETTE)],"marginRight":"4px"}),
                            f"{layer.kind[:4]}: ", name, ucs_badge, band_badge], style={"fontSize":"11px"}),
            ], style={"display":"flex","alignItems":"center"}),
            # (P1-T1.6) SIN min/max en el componente: con ellos, un valor fuera
            # de rango llega como None al callback y la validación no puede
            # distinguirlo de "campo vacío" → se perdía en silencio. La
            # validación vive en update_ucs, que rechaza con mensaje visible.
            dbc.Input(id={"type":"ucs-in","index":name}, type="number", placeholder="UCS [MPa]",
                      value=layer.ucs_lab,
                      step=1, size="sm", debounce=True, style={"fontSize":"10px","marginTop":"3px"}),
        ]
        # Etiquetado caserón×litología (T2). Los dropdowns solo se muestran si
        # hay Excel geomecánico cargado. Ids pattern-matching (contenido
        # regenerado) → nunca ids fijos.
        if caseron_opts:
            layer_children.append(dbc.Row([
                dbc.Col(dcc.Dropdown(id={"type":"caseron-sel","index":name}, options=caseron_opts,
                        value=layer.caseron, placeholder="Caserón…", clearable=True,
                        style={"fontSize":"10px"}), width=6),
                dbc.Col(dcc.Dropdown(id={"type":"lito-alias","index":name}, options=lito_opts,
                        value=layer.lito_alias, placeholder="Litología (alias)…", clearable=True,
                        style={"fontSize":"10px"}), width=6),
            ], className="g-1", style={"marginTop":"3px"}))
        items.append(dbc.ListGroupItem(layer_children,
            style={"padding":"5px 8px","background":"transparent","border":"none","borderBottom":"1px solid #222"}))
    for wn, well in wells.items():
        badge = ""
        if well.origin == "fallback_hole": badge = " ⚠ collar por fallback"
        elif well.origin == "no_dq": badge = " ⚠ sin DQ (ficticio)"
        elif well.origin == "ambiguous": badge = " ⚠ ambiguo (asignar DQ)"
        elif well.origin == "manual": badge = " ✎ DQ asignado manualmente"
        row = html.Div([
            dbc.Checkbox(id={"type":"vis-well","index":wn}, value=True,
                         style={"display":"inline-block","marginRight":"6px"}),
            html.Small([html.Span("○",style={"color":"#5DCAA5","marginRight":"4px"}), wn,
                        html.Span(badge, style={"color":"#F39C12","fontSize":"10px","marginLeft":"4px"})],
                       style={"fontSize":"11px"}),
            dbc.Button("📊", id={"type":"open-well-report","index":wn}, size="sm",
                       color="link", style={"fontSize":"12px","padding":"0 0 0 8px","marginLeft":"auto"}),
        ], style={"display":"flex","alignItems":"center"})
        item_children = [row]
        # Pozos ambiguos: dropdown de reasignación manual del DQ×hole (id
        # pattern-matching, sin ids fijos, para sobrevivir a la regeneración
        # del árbol). Al elegir se reinterpola y el origin pasa a "manual".
        if well.origin == "ambiguous" and well.dq_candidates:
            opts = [{"label": f"{_plan_short(c['plan_id'])} / hole {c['hole_id']} (err {c['err_pct']}%)",
                     "value": i} for i, c in enumerate(well.dq_candidates)]
            item_children.append(dcc.Dropdown(
                id={"type":"assign-dq","index":wn}, options=opts,
                placeholder="Asignar DQ×hole…", clearable=False,
                style={"fontSize":"10px","marginTop":"4px"}))
        items.append(dbc.ListGroupItem(
            item_children,
            style={"padding":"3px 8px","background":"transparent","border":"none","borderBottom":"1px solid #1a1a1a"}))
    return dbc.ListGroup(items, flush=True) if items else \
           html.Small("Sin datos.", style={"color":"#444","fontSize":"10px"})

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input({"type":"ucs-in","index":ALL},"value"),
    State({"type":"ucs-in","index":ALL},"id"),
    State("refresh","data"), prevent_initial_call=True,
)
def update_ucs(values, ids, ref):
    """
    (P1-T1.6) Un valor fuera de los límites físicos produce ERROR VISIBLE, nunca
    sustitución silenciosa. Antes se ignoraba el valor sin avisar y la capa se
    quedaba con su UCS anterior (o sin UCS), excluyéndola del entrenamiento sin
    que nada lo dijera.
    """
    changed, rechazados = False, []
    lo, hi = UCS_CONFIG["physical_min"], UCS_CONFIG["physical_max"]
    for val, id_d in zip(values, ids):
        name = id_d["index"]
        if name not in layers or val is None: continue
        try:
            ucs = float(val)
        except (TypeError, ValueError):
            rechazados.append(f"{name}: «{val}» no es un número."); continue
        if not np.isfinite(ucs):
            rechazados.append(f"{name}: valor no finito."); continue
        if not (lo <= ucs <= hi):
            rechazados.append(f"{name}: {ucs:g} MPa fuera del rango físico [{lo:g}, {hi:g}]."); continue
        if layers[name].ucs_lab != ucs:
            layers[name].ucs_lab = ucs; changed = True
    if rechazados:
        build_domain_index()
        return ref+1, "🚫 UCS rechazado (valor NO aplicado): " + " · ".join(rechazados), True
    if changed:
        build_domain_index()
        return ref+1, no_update, no_update
    return no_update, no_update, no_update

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input({"type":"caseron-sel","index":ALL},"value"),
    Input({"type":"lito-alias","index":ALL},"value"),
    State({"type":"caseron-sel","index":ALL},"id"),
    State({"type":"lito-alias","index":ALL},"id"),
    State("refresh","data"), prevent_initial_call=True,
)
def on_layer_meta(caseron_vals, alias_vals, caseron_ids, alias_ids, ref):
    """
    Asigna caserón / alias de litología a las capas DXF y autocompleta su banda
    UCS desde el Excel geomecánico. Ids pattern-matching → sobrevive a la
    regeneración del árbol; no toca la figura 3D (eso es de render_viewport).
    """
    ctx = callback_context
    if not ctx.triggered: return no_update, no_update, no_update
    # Solo actuar ante un cambio REAL de valor. Al regenerarse el árbol los
    # dropdowns se remontan y este callback se dispara con los mismos valores;
    # si no filtramos, cada disparo devolvería ref+1 y entraría en bucle.
    changed = False
    for val, id_d in zip(caseron_vals, caseron_ids):
        name = id_d["index"]
        if name in layers and layers[name].caseron != (val or None):
            layers[name].caseron = val or None; changed = True
    for val, id_d in zip(alias_vals, alias_ids):
        name = id_d["index"]
        if name in layers and layers[name].lito_alias != (val or None):
            layers[name].lito_alias = val or None; changed = True
    if not changed:
        return no_update, no_update, no_update
    filled = []
    for name, layer in layers.items():
        if layer.caseron and apply_layer_band(layer):
            filled.append(f"{name}→{layer.ucs_lo:.0f}–{layer.ucs_hi:.0f}")
    build_domain_index()
    if filled:
        return ref+1, "✅ Banda autocompletada: " + ", ".join(filled), True
    return ref+1, "Caserón/litología actualizado (sin banda coincidente).", True

@app.callback(
    Output("active-step","data"),
    Input({"type":"pill","index":ALL},"n_clicks"),
    State("active-step","data"),
    prevent_initial_call=True,
)
def nav(pill_clicks, current):
    """
    Navegación robusta con pattern-matching (ALL). Tanto los pills de la barra
    superior como los botones "Siguiente →" / "← Atrás" de cada paso usan el
    mismo id={"type":"pill","index":N}. Esto es inmune a que wz-content se
    regenere en cada refresh: Dash resuelve el callback por el patrón, no por
    un id fijo que podría no existir todavía en el layout.
    """
    ctx = callback_context
    if not ctx.triggered: return no_update
    # Ignorar disparos donde n_clicks es None (componente recién montado)
    triggered_id = ctx.triggered_id
    if triggered_id is None or not isinstance(triggered_id, dict):
        return no_update
    triggered_value = ctx.triggered[0]["value"]
    if not triggered_value:
        return no_update
    target = triggered_id["index"]
    if not wz_prereq(target): return no_update
    return target

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("up-dxf","contents"), State("up-dxf","filename"),
    State("refresh","data"), prevent_initial_call=True,
)
def on_dxf(contents_list, filenames, ref):
    if not contents_list: return no_update, no_update, no_update
    loaded, errs, bloqueadas = [], [], []
    for content, fname in zip(contents_list, filenames):
        try:
            _, b64 = content.split(",", 1)
            raw = base64.b64decode(b64)
            # (Sesión E) parseo cacheado en disco por hash del contenido: el
            # perfilado real mostró que parsear el DXF (no el ray casting)
            # es el costo dominante — 12,5 s / +210 MB para una malla de
            # ~93k triángulos, contra 1,6 s para clasificar 262.500 puntos.
            tris, _ = parse_dxf_cached(raw, fname)
            name = Path(fname).stem
            bmin = tris.reshape(-1,3).min(0)
            bmax = tris.reshape(-1,3).max(0)
            # (T1.1) Guardián por coordenadas: DXF es X=Este, Y=Norte, Z=Cota.
            # Las coordenadas son la autoridad de pertenencia al sitio, no el
            # nombre del archivo. Si excede el margen NO se carga en silencio.
            verdict = site_guard(este=(bmin[0]+bmax[0])/2, norte=(bmin[1]+bmax[1])/2,
                                 etiqueta=name, tipo="malla DXF", token=f"dxf:{name}")
            if not verdict["ok"]:
                bloqueadas.append(verdict["mensaje"]); log_warn(verdict["mensaje"]); continue
            lay = Layer(name=name, kind=guess_kind(fname), triangles=tris,
                        bbox_min=bmin, bbox_max=bmax)
            # (T1.3 / A.3) Sugerencia automática de atributos canónicos. Un
            # nombre puede resolver a VARIOS roles (Bht_Fk → litología +
            # alteración). Si el texto no se reconoce cae a la bandeja de
            # pendientes, donde A.3 puede haber dejado una descomposición
            # PROPUESTA — que nunca se aplica sola: exige confirmación.
            m = resolve_or_note(name, "dxf_layer")
            if m: set_layer_attributes(lay, m)
            layers[name] = lay
            if global_center is None:
                cx = (bmin[0]+bmax[0])/2; cy = (bmin[1]+bmax[1])/2; cz = (bmin[2]+bmax[2])/2
                set_center(norte=cy, este=cx, cota=cz)
            if m:
                det = " → " + " + ".join(f"{r}:{a}" for r, a in sorted(m.items()))
            else:
                prop = (pending_aliases.get(_norm_txt(name)) or {}).get("propuesta")
                det = (" · descomposición PROPUESTA (confirmar en el panel): "
                       + " + ".join(f"{r}:{a}" for r, a in sorted(prop["atributos"].items()))
                       ) if prop else ", sin atributo"
            loaded.append(f"{name} ({len(tris)} tri{det})")
        except Exception as e:
            errs.append(f"{fname}: {e}")
    wz_state['step1']['dxf_loaded'] = bool(layers)
    parts = []
    if loaded: parts.append(f"✅ DXF: {', '.join(loaded)}")
    if bloqueadas: parts.append("🚫 FUERA DE SITIO (no cargadas): " + " ".join(bloqueadas))
    if errs: parts.append(f"Err: {'; '.join(errs)}")
    n_pend = pending_alias_count()
    if n_pend: parts.append(f"🏷 {n_pend} texto(s) pendiente(s) de asignar.")
    return ref+1, " | ".join(parts) if parts else "Sin cambios.", True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("up-xml","contents"), State("up-xml","filename"),
    State("refresh","data"), prevent_initial_call=True,
)
def on_xml(contents_list, filenames, ref):
    if not contents_list: return no_update, no_update, no_update
    dq_list, mw_by_hole, errs = [], {}, []
    for content, fname in zip(contents_list, filenames):
        try:
            _, b64 = content.split(",", 1)
            raw = base64.b64decode(b64)
            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
                f.write(raw); tmp = f.name
            try:
                root = ET.parse(tmp).getroot()
                root_tag = root.tag
            except: root_tag = ""
            if is_dq(fname, root_tag):
                # Se ACUMULAN los DQ, no se indexan por plan_id: varios
                # archivos pueden ser revisiones del mismo abanico y cada
                # una traer tiros distintos. La fusión (y el reporte de sus
                # desacuerdos) ocurre después, en merge_dq_siblings.
                dq_list.append(parse_dq(tmp, fname))
            else:
                mw = parse_mw(tmp, fname)
                key = f"{mw['plan_id']}_H{mw['hole_id'] or 'X'}"
                mw_by_hole.setdefault(key, []).append(mw)
            os.unlink(tmp)
        except Exception as e:
            errs.append(f"{fname}: {e}")
    dq_results, dq_rep = merge_dq_siblings(dq_list)
    counts = match_and_place_wells(dq_results, mw_by_hole)
    if wells:
        wz_state['step1']['xml_loaded'] = True
    parts = [f"✅ {len(mw_by_hole)} pozos MWD"]
    if counts["matched"]:   parts.append(f"{counts['matched']} matcheados")
    if counts["fallback"]:  parts.append(f"{counts['fallback']} por hermano ⚠")
    if counts["ambiguous"]: parts.append(f"{counts['ambiguous']} ambiguos ⚠ (reasignar)")
    if counts["no_dq"]:     parts.append(f"{counts['no_dq']} sin DQ ⚠")
    if counts.get("fuera_sitio"):
        parts.append(f"🚫 {counts['fuera_sitio']} FUERA DEL SITIO {active_site()['id']} "
                     f"(no cargados — ver advertencias)")
    if dq_rep["n_archivos"] > dq_rep["n_planes"]:
        parts.append(f"{dq_rep['n_archivos']} DQ → {dq_rep['n_planes']} planes "
                     f"({dq_rep['n_tiros']} tiros)")
    if dq_rep["conflictos"]:
        parts.append(f"{len(dq_rep['conflictos'])} tiro(s) con coordenadas distintas "
                     f"entre revisiones ⚠")
    if errs: parts.append(f"Err: {'; '.join(errs)}")
    return ref+1, " · ".join(parts), True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("up-excel","contents"), State("up-excel","filename"),
    State("refresh","data"), prevent_initial_call=True,
)
def on_excel(content, fname, ref):
    if not content: return no_update, no_update, no_update
    try:
        _, b64 = content.split(",", 1)
        raw = base64.b64decode(b64)
        with tempfile.NamedTemporaryFile(suffix=Path(fname).suffix, delete=False) as f:
            f.write(raw); tmp = f.name
        rows = parse_excel(tmp); os.unlink(tmp)
        excel_data.clear(); excel_data.extend(rows)
        apply_seteo_from_excel()
        return ref+1, f"✅ Excel: {len(rows)} tiros.", True
    except Exception as e:
        return no_update, f"❌ Excel: {e}", True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("up-geomech","contents"), State("up-geomech","filename"),
    State("refresh","data"), prevent_initial_call=True,
)
def on_geomech(content, fname, ref):
    """Carga el Excel geomecánico caserón×litología y reconstruye geomech_bands."""
    if not content: return no_update, no_update, no_update
    try:
        _, b64 = content.split(",", 1)
        raw = base64.b64decode(b64)
        with tempfile.NamedTemporaryFile(suffix=Path(fname).suffix, delete=False) as f:
            f.write(raw); tmp = f.name
        records = parse_geomech_excel(tmp); os.unlink(tmp)
        index_geomech_bands(records)
        # Reaplicar bandas a las capas que ya tengan caserón asignado.
        for layer in layers.values():
            if layer.caseron: apply_layer_band(layer)
        build_domain_index()
        n_cas, n_lit = len(excel_caserones()), len(excel_litologias())
        return ref+1, (f"✅ Excel geomecánico: {len(records)} bandas "
                       f"({n_cas} caserones, {n_lit} litologías)."), True
    except Exception as e:
        return no_update, f"❌ Excel geomecánico: {e}", True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-preview-cross","n_clicks"),
    State("refresh","data"), prevent_initial_call=True,
)
def do_preview_cross(n, ref):
    """
    Ejecuta el cruce geométrico DXF↔MWD sin entrenar el modelo, para que el
    usuario vea de inmediato cuántos puntos MWD caen dentro de cada sólido y
    reciben UCS, antes de avanzar a los pasos de calibración/DI/ML.
    """
    if not n: return no_update, no_update, no_update
    if not layers:
        return no_update, "⚠ Carga al menos una malla DXF con UCS asignado primero.", True
    if not wells:
        return no_update, "⚠ Carga al menos un XML MWD primero.", True
    classify_all_wells_cached()
    build_domain_index()
    all_pts = list(all_points())
    n_ucs = sum(1 for p in all_pts if p.dominio and domains.get(p.dominio, {}).get("ucs_lab"))
    n_dom = sum(1 for p in all_pts if p.dominio)
    return ref+1, f"✅ Cruce ejecutado: {n_dom}/{len(all_pts)} pts dentro de alguna malla, {n_ucs} con UCS asignado.", True

for btn_id, upload_id in [("btn-dxf","up-dxf"),("btn-xml","up-xml"),("btn-excel","up-excel"),
                          ("btn-geomech","up-geomech"),("btn-drillhole","up-drillhole")]:
    app.clientside_callback(
        f"""function(n){{if(n){{var e=document.querySelector('#{upload_id} input[type=file]');if(e)e.click();}}return window.dash_clientside.no_update;}}""",
        Output(btn_id,"n_clicks"), Input(btn_id,"n_clicks"), prevent_initial_call=True,
    )

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-cal-apply","n_clicks"),
    [State(f"cal-{k}","value") for k in ("vel","pp","pa","pd","pr","pf")],
    State("refresh","data"), prevent_initial_call=True,
)
def do_cal(n, *args):
    if not n: return no_update, no_update, no_update
    vals = args[:6]; ref = args[6]
    for k, v in zip(("vel","pp","pa","pd","pr","pf"), vals):
        cal_factors[k] = float(v or 1.0)
    apply_calibration()
    wz_state['step2']['calibrated'] = True
    return ref+1, "✅ Calibración aplicada.", True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-cal-derive","n_clicks"),
    State("refresh","data"), prevent_initial_call=True,
)
def do_derive(n, ref):
    if not n: return no_update, no_update, no_update
    derived = derive_cal_factors_from_excel()
    if not derived:
        return no_update, "⚠ Sin tiros comunes.", True
    cal_factors.update(derived); apply_calibration()
    return ref+1, f"✅ Factores: {derived}", True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-prelim","n_clicks"),
    State("refresh","data"), prevent_initial_call=True,
)
def do_prelim(n, ref):
    if not n: return no_update, no_update, no_update
    s = train_prelim_from_excel()
    if "error" in s: return no_update, f"⚠ {s['error']}", True
    return ref+1, f"✅ Prelim: R²={s['r2']}, RMSE={s['rmse']} MPa", True

@app.callback(Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-cut","n_clicks"), State("val-cut","value"),
    State("refresh","data"), prevent_initial_call=True)
def do_cut(n, cut, ref):
    if not n: return no_update, no_update, no_update
    # (P3-3.8) `float(cut or 2.0)` habría sustituido en silencio un 0.0
    # explícito (corte desactivado) por el default. Un valor no numérico o
    # negativo se rechaza con mensaje, nunca se sustituye.
    try:
        cut_v = float(cut)
    except (TypeError, ValueError):
        return no_update, f"🚫 Corte de emboquillado inválido: «{cut}».", True
    if cut_v < 0:
        return no_update, f"🚫 El corte de emboquillado no puede ser negativo ({cut_v:g} m).", True
    apply_inicio_filter(cut_v)
    wz_state['step2']['cleaned'] = True
    return ref+1, no_update, no_update

@app.callback(Output("refresh","data",allow_duplicate=True),
    Input("btn-add-filt","n_clicks"),
    State("sel-norm-var","value"), State("sel-norm-method","value"),
    State("refresh","data"), prevent_initial_call=True)
def do_add_filt(n, var, method, ref):
    if not n: return no_update
    add_norm_filter(var, method)
    wz_state['step2']['cleaned'] = True
    return ref+1

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input({"type":"rm-filt","index":ALL},"n_clicks"),
    State("refresh","data"), prevent_initial_call=True,
)
def do_remove_filt(n_clicks_list, ref):
    ctx = callback_context
    if not ctx.triggered: return no_update, no_update, no_update
    triggered_id = ctx.triggered_id
    if not isinstance(triggered_id, dict): return no_update, no_update, no_update
    triggered_value = ctx.triggered[0]["value"]
    if not triggered_value: return no_update, no_update, no_update
    idx = triggered_id["index"]
    ok = remove_filter(idx)
    if ok:
        return ref+1, "✅ Filtro eliminado, puntos recalculados.", True
    return no_update, "⚠ No se pudo eliminar el filtro.", True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input({"type":"assign-dq","index":ALL},"value"),
    State({"type":"assign-dq","index":ALL},"id"),
    State("refresh","data"), prevent_initial_call=True,
)
def on_assign_dq(values, ids, ref):
    """
    Reasigna manualmente el DQ×hole de un pozo ambiguo. El dropdown vive dentro
    del árbol de capas regenerado, por eso usa id pattern-matching
    {"type":"assign-dq","index":well_name} (no un id fijo). Al elegir un
    candidato se reinterpolan las coordenadas de los puntos con la MISMA
    interpolación lineal por p.t que usa on_xml, el origin pasa a "manual" y
    se dispara refresh.
    """
    ctx = callback_context
    if not ctx.triggered: return no_update, no_update, no_update
    triggered_id = ctx.triggered_id
    if not isinstance(triggered_id, dict): return no_update, no_update, no_update
    triggered_value = ctx.triggered[0]["value"]
    if triggered_value is None: return no_update, no_update, no_update
    well_name = triggered_id["index"]
    well = wells.get(well_name)
    if not well: return no_update, no_update, no_update
    try:
        cand = well.dq_candidates[int(triggered_value)]
    except (IndexError, ValueError, TypeError):
        return no_update, "⚠ Candidato DQ inválido.", True
    collar, final_pt = cand["collar"], cand["final_pt"]
    well.collar, well.final_pt = collar, final_pt
    for p in well.points:
        p.este  = collar["este"]  + p.t*(final_pt["este"]  - collar["este"])
        p.norte = collar["norte"] + p.t*(final_pt["norte"] - collar["norte"])
        p.cota  = collar["cota"]  + p.t*(final_pt["cota"]  - collar["cota"])
    well.origin = "manual"
    log_warn(f'Pozo "{well_name}" reasignado manualmente a DQ '
             f'"{cand["plan_id"]}" hole={cand["hole_id"]} (err {cand["err_pct"]}%).')
    return ref+1, (f"✅ {well_name}: reasignado a {_plan_short(cand['plan_id'])} / "
                   f"hole {cand['hole_id']} (err {cand['err_pct']}%)."), True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-di","n_clicks"),
    State("di-window","value"), State("di-thresh","value"),
    State("di-w-pp","value"), State("di-w-pd","value"),
    State("di-w-pf","value"), State("di-w-pr","value"),
    State("refresh","data"), prevent_initial_call=True,
)
def do_di(n, window, thresh, w_pp, w_pd, w_pf, w_pr, ref):
    """
    (P3-3.7) Pesos y umbral del DI, configurables desde la interfaz. `or
    default` habría sustituido en silencio un 0 explícito (peso desactivado)
    o un umbral 0.0; cada campo se valida por separado y un valor inválido
    aborta con mensaje, sin tocar la configuración vigente.
    """
    if not n: return no_update, no_update, no_update
    def _num(v, etiqueta, lo=None):
        if v is None or v == "":
            return None, f"{etiqueta} vacío."
        try: x = float(v)
        except (TypeError, ValueError):
            return None, f"{etiqueta}: «{v}» no es un número."
        if not np.isfinite(x):
            return None, f"{etiqueta}: valor no finito."
        if lo is not None and x < lo:
            return None, f"{etiqueta}: {x:g} < {lo:g}."
        return x, None
    campos = [(window, "Ventana", 3), (thresh, "Umbral", 0.0),
             (w_pp, "Peso PP", 0.0), (w_pd, "Peso DP", 0.0),
             (w_pf, "Peso FP", 0.0), (w_pr, "Peso RP", 0.0)]
    valores, errores = [], []
    for v, etq, lo in campos:
        x, e = _num(v, etq, lo)
        valores.append(x)
        if e: errores.append(e)
    if errores:
        return no_update, "🚫 " + " · ".join(errores), True
    window_v, thresh_v, wpp, wpd, wpf, wpr = valores
    global di_threshold
    di_config["window"] = int(window_v)
    di_threshold = float(thresh_v)
    di_config["weights"] = {"pp": wpp, "pd": wpd, "pf": wpf, "pr": wpr}
    suma = wpp + wpd + wpf + wpr
    aviso_suma = ""
    if abs(suma - 1.0) > 0.02:
        aviso_suma = f" ⚠ los pesos suman {suma:.3f} (no 1,0)."
    compute_di()
    wz_state['step3']['di_computed'] = True
    all_pts = list(all_points())
    n_di = sum(1 for p in all_pts if p.di is not None)
    n_disc = sum(1 for p in all_pts if p.di is not None and p.di > di_threshold)
    modif = "" if di_config_is_default() else " · configuración MODIFICADA respecto a Fernández et al. 2023"
    return ref+1, f"✅ DI: {n_di} pts · {n_disc} discontinuidades{modif}.{aviso_suma}", True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("di-window","value"), Output("di-thresh","value"),
    Output("di-w-pp","value"), Output("di-w-pd","value"),
    Output("di-w-pf","value"), Output("di-w-pr","value"),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-di-reset","n_clicks"),
    State("refresh","data"), prevent_initial_call=True,
)
def do_di_reset(n, ref):
    """(P3-3.7) Restaura ventana, umbral y pesos a Fernández et al. 2023. Solo
    cambia la configuración; no recalcula el DI hasta que se pulse Calcular."""
    if not n: return (no_update,)*8
    global di_threshold
    di_config["window"] = DI_DEFAULTS["window"]
    di_threshold = DI_DEFAULTS["threshold"]
    di_config["weights"] = dict(DI_DEFAULTS["weights"])
    w = di_config["weights"]
    return (ref+1, di_config["window"], di_threshold, w["pp"], w["pd"], w["pf"], w["pr"],
           "↺ Configuración DI restaurada a Fernández et al. 2023. Pulsa «Calcular DI» "
           "para recalcular con estos valores.", True)

@app.callback(
    Output({"type":"sens-output","index":ALL},"children"),
    Input({"type":"sens-btn","index":ALL},"n_clicks"),
    State({"type":"sens-well-sel","index":ALL},"value"),
    State({"type":"sens-output","index":ALL},"id"),
    prevent_initial_call=True,
)
def do_di_sensitivity(n_clicks_list, well_sel_list, out_ids):
    """
    (T7b/c) Análisis de sensibilidad del DI (ventanas 10/14/20) para el pozo
    seleccionado. Callback normal (no hilo): un solo pozo, cálculo rápido con
    la función pura di_profile — no toca p.di ni bloquea la UI. El dropdown,
    botón y contenedor de salida viven en wz-content (contenido regenerado al
    navegar de paso) → todos con ids pattern-matching.
    """
    n_out = len(out_ids)
    ctx = callback_context
    tid = ctx.triggered_id
    if not isinstance(tid, dict) or not ctx.triggered[0]["value"]:
        return [no_update] * n_out
    wn = well_sel_list[0] if well_sel_list else None
    well = wells.get(wn)
    if not well or not well.points:
        return [dbc.Alert("Selecciona un pozo válido.", color="warning",
                          style={"fontSize":"11px","padding":"6px 10px"})] * n_out
    content = build_di_sensitivity_content(well)
    return [content] * n_out

@app.callback(
    Output("ml-task-poll","disabled"),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-ml","n_clicks"),
    State("ucs-min","value"), State("ucs-max","value"),
    prevent_initial_call=True,
)
def do_ml(n, ucs_min_v, ucs_max_v):
    """
    Lanza el pipeline (cruce + índice + RF) en un hilo de fondo y activa el
    polling (dcc.Interval) que consulta task_state cada 500ms para actualizar
    la barra de progreso y el log en vivo, sin bloquear la UI de Dash.

    (P1-T1.6) El rango de UCS ya NO cae a un default cuando el campo llega
    vacío o fuera de límites: eso fue el bug que excluía en silencio una
    litología completa. Un rango inválido aborta el lanzamiento con mensaje.
    """
    if not n or task_state["running"]:
        return no_update, no_update, no_update
    lo_f, hi_f = UCS_CONFIG["physical_min"], UCS_CONFIG["physical_max"]
    def _chk(v, etiqueta):
        if v is None or v == "":
            return None, f"{etiqueta} vacío (o fuera de rango en el campo)."
        try: x = float(v)
        except (TypeError, ValueError): return None, f"{etiqueta}: «{v}» no es un número."
        if not np.isfinite(x): return None, f"{etiqueta}: valor no finito."
        if not (lo_f <= x <= hi_f):
            return None, f"{etiqueta}: {x:g} MPa fuera del rango físico [{lo_f:g}, {hi_f:g}]."
        return x, None
    lo, e1 = _chk(ucs_min_v, "UCS mín")
    hi, e2 = _chk(ucs_max_v, "UCS máx")
    errs = [e for e in (e1, e2) if e]
    if not errs and lo > hi:
        errs.append(f"UCS mín ({lo:g}) es mayor que UCS máx ({hi:g}).")
    if errs:
        return no_update, "🚫 No se ejecutó: " + " · ".join(errs), True
    ucs_range["ucs_min"], ucs_range["ucs_max"] = lo, hi
    # (P1-T1.5) Bloqueo ruidoso: atributos presentes sin banda de UCS y sin
    # exclusión explícita impiden entrenar. Se nombra qué falta y cuánto pesa.
    bloqueo = training_block_message()
    if bloqueo:
        return no_update, "🚫 " + bloqueo, True
    th = threading.Thread(target=run_ml_task, args=(ucs_range["ucs_min"], ucs_range["ucs_max"]), daemon=True)
    th.start()
    return False, no_update, no_update  # habilita el Interval de polling

@app.callback(
    Output("ml-progress-bar","value"), Output("ml-progress-bar","label"),
    Output("ml-stage-label","children"), Output("ml-log-box","children"),
    Output("ml-task-poll","disabled",allow_duplicate=True),
    Output("refresh","data",allow_duplicate=True),
    Output("ml-result","children"),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("ml-task-poll","n_intervals"),
    State("refresh","data"), prevent_initial_call=True,
)
def poll_ml_task(_, ref):
    with task_lock:
        running = task_state["running"]
        progress = task_state["progress"]
        stage = task_state["stage"]
        log_lines = list(task_state["log"])
        done = task_state["done"]
        error = task_state["error"]
        result = task_state["result"]

    log_box = html.Div([
        html.Div(line, style={"fontFamily":"monospace","fontSize":"10px","color":"#8f8" if "✅" in line else ("#f88" if "❌" in line or "⚠" in line else "#aaa")})
        for line in log_lines[-40:]
    ], style={"maxHeight":"140px","overflowY":"auto","background":"#050508",
              "padding":"6px 8px","borderRadius":"4px","border":"1px solid #222"})

    if not done:
        return progress, f"{progress}%", stage, log_box, False, no_update, no_update, no_update, no_update

    # Tarea terminada (con o sin error): detener polling y refrescar la UI
    if error:
        return progress, f"{progress}%", stage, log_box, True, no_update, \
               dbc.Alert(error, color="warning"), f"⚠ {error}", True

    # (T6c) CV agrupada por pozo: si se omitió (< 3 pozos), mostrar el motivo
    # en vez de un "—" mudo, para que quede claro por qué falta la métrica.
    if result.get('cv_r2_mean') is not None:
        cv_display = f"{result['cv_r2_mean']}±{result['cv_r2_std']}"
    elif result.get('cv_warning'):
        cv_display = "sin CV"
    else:
        cv_display = "—"
    badges = html.Div([
        dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody([html.Div(str(v),style={"fontSize":"17px","fontWeight":700}),
                html.Small(k,style={"color":"#aaa","fontSize":"10px"})], style={"padding":"6px 10px"}),
                color="dark"), width="auto")
            for k,v in [("R² in-sample",result["r2_train"]),("RMSE in-sample",f"{result['rmse_train']} MPa"),
                        ("RMSEA",result["rmsea"]),
                        ("R² CV agrupada (por pozo)",cv_display),
                        ("N",result["n_train"]),("Excl. caídas",result["n_excl_disc"])]
        ], className="g-1 mt-2"),
        dbc.Alert([
            html.Small([
                html.B("R² in-sample"), " mide el ajuste sobre los mismos datos usados para entrenar ",
                "(equivalente a evaluar con predict(X) sobre el 100% de los datos, sin holdout separado). ",
                html.B("R² CV agrupada (por pozo)"), " es la métrica honesta de generalización: usa "
                "GroupKFold, que mantiene TODO un pozo del mismo lado del split train/test. Evita la fuga "
                "espacial entre muestras vecinas de un mismo tiro (a 2 cm entre sí y fuertemente "
                "autocorrelacionadas), que un KFold aleatorio mezclaría e infla artificialmente el R². "
                "Para reportar en la memoria, usar esta métrica.",
            ] + ([html.Br(), html.Br(), f"⚠ {result['cv_warning']}"] if result.get('cv_warning') else []),
            style={"color":"#aaa","lineHeight":"1.5"})
        ], color="dark", style={"fontSize":"10px","padding":"6px 10px","marginTop":"6px"}),
    ])
    msg = f"✅ R² in-sample={result['r2_train']} | R² CV agrupada={cv_display} | RMSE={result['rmse_train']} MPa | N={result['n_train']}"
    return progress, f"{progress}%", stage, log_box, True, ref+1, badges, msg, True

# ─── Callbacks de la validación multipozo (T4e) ───────────────────────────────
@app.callback(
    Output("val-task-poll","disabled"),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input({"type":"val-mesh-btn","index":ALL},"n_clicks"),
    prevent_initial_call=True,
)
def start_mesh_validation(n_clicks_list):
    """
    Lanza la validación multipozo en hilo de fondo y habilita su polling. El
    botón vive en contenido regenerado → id pattern-matching, nunca fijo. No
    interfiere con el flujo del ML: usa val_task_state y val-task-poll propios.
    """
    ctx = callback_context
    tid = ctx.triggered_id
    if not isinstance(tid, dict) or not ctx.triggered[0]["value"]:
        return no_update, no_update, no_update
    if val_task_state["running"]:
        return no_update, "⚠ La validación ya está corriendo.", True
    if not any(l.kind == "estructura" for l in layers.values()):
        return no_update, "⚠ No hay mallas de estructura cargadas.", True
    if not any(p.di is not None for p in all_points()):
        return no_update, "⚠ Calcula el DI primero (Paso 3).", True
    threading.Thread(target=run_validation_task, daemon=True).start()
    return False, "🧭 Validación multipozo iniciada…", True

@app.callback(
    Output("val-task-poll","disabled",allow_duplicate=True),
    Output({"type":"val-progress","index":ALL},"value"),
    Output({"type":"val-progress","index":ALL},"label"),
    Output({"type":"val-progress-txt","index":ALL},"children"),
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("val-task-poll","n_intervals"),
    State({"type":"val-progress","index":ALL},"id"),
    State("refresh","data"), prevent_initial_call=True,
)
def poll_mesh_validation(_, prog_ids, ref):
    """
    Polling de la validación de mallas. Los componentes de progreso viven en
    contenido regenerado → outputs pattern-matching (ALL); si el usuario
    navegó a otro paso, las listas quedan vacías y no pasa nada. Al terminar:
    detiene el polling, refresca (re-renderiza el Paso 5 con la tabla) y
    muestra el resumen en el toast.
    """
    n = len(prog_ids)
    with task_lock:
        prog = val_task_state["progress"]; stage = val_task_state["stage"]
        done = val_task_state["done"]; err = val_task_state["error"]
        result = val_task_state["result"]
    if done:
        with task_lock:
            val_task_state["done"] = False   # consumir para no repetir el toast
        if err:
            return True, [100]*n, [""]*n, [""]*n, no_update, f"❌ Validación: {err}", True
        msg = (f"✅ Validación: {result['n_mallas']} mallas · "
               f"{result['n_desplazadas']} con posible desplazamiento · {result['t']}s")
        return True, [100]*n, [""]*n, [""]*n, ref+1, msg, True
    return no_update, [prog]*n, [f"{prog}%"]*n, [stage]*n, no_update, no_update, no_update

@app.callback(
    Output("export-pending","data"),
    Output("export-confirm-modal","is_open"),
    Output("export-confirm-body","children"),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-exp-dom","n_clicks"), Input("btn-exp-pred","n_clicks"),
    Input({"type":"val-export-btn","index":ALL},"n_clicks"),
    Input({"type":"di-rqd-export-btn","index":ALL},"n_clicks"),
    Input("btn-save-project","n_clicks"), Input("btn-kit-cap5","n_clicks"),
    prevent_initial_call=True,
)
def on_export_trigger(n_dom, n_pred, n_val, n_rqd, n_proj, n_kit):
    """
    (P3-3.3) Punto de entrada ÚNICO de las seis exportaciones. Nunca descarga
    directo: arma el descriptor (qué se exporta, cuántos registros, nombre de
    archivo) y abre el diálogo de confirmación. Sin datos que exportar, avisa
    en vez de abrir un diálogo vacío.
    """
    trig = callback_context.triggered_id
    trig_val = callback_context.triggered[0]["value"]
    if not trig_val: return no_update, no_update, no_update, no_update, no_update
    if isinstance(trig, dict):
        kind = "validacion" if trig.get("type") == "val-export-btn" else "di_rqd"
    else:
        kind = {"btn-exp-dom":"dominios", "btn-exp-pred":"predicciones",
               "btn-save-project":"proyecto", "btn-kit-cap5":"kit"}.get(trig)
    if kind is None: return no_update, no_update, no_update, no_update, no_update
    desc = _export_descriptor(kind)
    if desc is None:
        return no_update, no_update, no_update, "⚠ No hay datos para exportar.", True
    body = html.Div([
        html.P(desc["desc"], style={"fontSize":"12px"}),
        html.P([html.B(f"{desc['n']} "), desc["unidad"]], style={"fontSize":"13px"}),
        html.Small(f"Archivo: {desc['filename']}",
                  style={"color":"#888","fontFamily":"monospace","display":"block"}),
    ])
    return desc, True, body, no_update, no_update

@app.callback(Output("export-confirm-modal","is_open",allow_duplicate=True),
              Input("btn-export-cancel","n_clicks"), prevent_initial_call=True)
def on_export_cancel(n):
    return False if n else no_update

@app.callback(
    Output("download","data",allow_duplicate=True),
    Output("download-project","data",allow_duplicate=True),
    Output("kit-interval","disabled",allow_duplicate=True),
    Output("export-confirm-modal","is_open",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-export-confirm","n_clicks"),
    State("export-pending","data"),
    prevent_initial_call=True,
)
def on_export_confirm(n, pending):
    """(P3-3.3) Ejecuta la exportación confirmada. Los CSV que dependen de DI
    (predicciones, dominios, DI↔RQD) llevan los parámetros DI vigentes como
    encabezado '#' (P3-3.7): cualquier cambio altera todo aguas abajo."""
    if not n or not pending:
        return (no_update,)*6
    kind, fname = pending["kind"], pending["filename"]
    meta = [di_config_summary()]
    if kind == "dominios":
        csv = _csv_with_metadata(export_domain_csv(), meta)
        return dcc.send_string(csv, fname), no_update, no_update, False, no_update, no_update
    if kind == "predicciones":
        csv = _csv_with_metadata(export_predictions_csv(), meta)
        return dcc.send_string(csv, fname), no_update, no_update, False, no_update, no_update
    if kind == "validacion":
        return (dcc.send_data_frame(export_validation_csv().to_csv, fname, index=False),
               no_update, no_update, False, no_update, no_update)
    if kind == "di_rqd":
        csv = _csv_with_metadata(export_di_rqd_csv(), meta)
        return dcc.send_string(csv, fname), no_update, no_update, False, no_update, no_update
    if kind == "proyecto":
        if not wells:
            return no_update, no_update, no_update, False, "⚠ No hay datos cargados para guardar.", True
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".gwz", delete=False)
            tmp.close()
            save_project(tmp.name)
            with open(tmp.name, "rb") as f: data = f.read()
            os.unlink(tmp.name)
            return (no_update, dcc.send_bytes(data, fname), no_update, False,
                   f"✅ Guardado — {len(wells)} pozos.", True)
        except Exception as e:
            return no_update, no_update, no_update, False, f"❌ Error al guardar: {e}", True
    if kind == "kit":
        if not wells:
            return no_update, no_update, no_update, False, "⚠ No hay datos para exportar.", True
        with task_lock:
            if kit_task_state["running"]:
                return no_update, no_update, no_update, False, "⏳ Ya está generando el kit…", True
        kit_task_state["filename"] = fname
        threading.Thread(target=run_kit_task, daemon=True).start()
        return no_update, no_update, False, False, "⏳ Generando kit Cap.5…", True
    return no_update, no_update, no_update, False, no_update, no_update

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-group","n_clicks"),
    State("tol-ucs","value"), State("tol-di","value"), State("tol-int","value"),
    State("refresh","data"), prevent_initial_call=True,
)
def do_group(n, tucs, tdi, tint, ref):
    if not n: return no_update, no_update, no_update
    n_g = compute_domain_groups(float(tucs or 20), float(tdi or 0.15), float(tint or 2))
    return ref+1, f"✅ {n_g} grupos.", True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-pred","n_clicks"),
    State("tol-ucs","value"), State("tol-di","value"), State("tol-int","value"),
    State("refresh","data"), prevent_initial_call=True,
)
def do_pred(n, tucs, tdi, tint, ref):
    if not n: return no_update, no_update, no_update
    res = predict_unclassified(float(tucs or 20), float(tdi or 0.15), float(tint or 2))
    return ref+1, f"✅ {res['assigned']}/{res['total']} pts asignados.", True

@app.callback(
    Output("topn-result","children"),
    Input("btn-topn","n_clicks"),
    State("topn-domain","value"), State("topn-method","value"),
    prevent_initial_call=True,
)
def do_topn(n, group_id, method):
    if not n or not group_id: return no_update
    results = top_drilling(group_id, n=5, method=method)
    if not results:
        return dbc.Alert("Sin segmentos candidatos suficientes en este dominio (mín. 5 muestras continuas).",
                          color="warning", style={"fontSize":"11px","padding":"6px 10px"})
    method_labels = {"min_se_cv":"Mínima variación interna de SE","min_se":"Mínima SE","max_rop":"Máxima ROP"}
    header = dbc.Row([
        dbc.Col(html.Small("Pozo", style={"color":"#888","fontWeight":700}), width=2),
        dbc.Col(html.Small("Prof. [m]", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("ROP", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("SE", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("CV(SE)", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("PP", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("PR", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("PA", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("PD", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("PF", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("N", style={"color":"#888","fontWeight":700}), width=1),
    ], className="mb-1")
    body = [dbc.Row([
        dbc.Col(html.Small(r["well"], style={"color":"#3B8BD4"}), width=2),
        dbc.Col(html.Small(f"{r['largo']:.1f}", style={"color":"#ccc"}), width=1),
        dbc.Col(html.Small(f"{r['vel']:.2f}", style={"color":"#2ECC71"}), width=1),
        dbc.Col(html.Small(f"{r['se']:.1f}", style={"color":"#EF9F27"}), width=1),
        dbc.Col(html.Small(f"{r['se_cv']:.3f}", style={"color":"#aaa"}), width=1),
        dbc.Col(html.Small(f"{r['pp']:.1f}", style={"color":"#aaa"}), width=1),
        dbc.Col(html.Small(f"{r['pr']:.1f}", style={"color":"#aaa"}), width=1),
        dbc.Col(html.Small(f"{r['pa']:.1f}", style={"color":"#aaa"}), width=1),
        dbc.Col(html.Small(f"{r['pd']:.1f}", style={"color":"#aaa"}), width=1),
        dbc.Col(html.Small(f"{r['pf']:.1f}", style={"color":"#aaa"}), width=1),
        dbc.Col(html.Small(str(r["n_pts"]), style={"color":"#666"}), width=1),
    ], className="mb-1 py-1", style={"borderBottom":"1px solid #1a1a1a"}) for r in results]
    return html.Div([
        dbc.Badge(f"Criterio: {method_labels.get(method,method)}", color="info", className="mb-2"),
        header, *body,
    ])


# ─── T10: callbacks de guardar / cargar proyecto ──────────────────────────────
# (P3-3.3) "Guardar proyecto" (btn-save-project) ahora pasa por el diálogo de
# confirmación único: on_export_trigger / on_export_confirm más arriba.
@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("up-project","contents"),
    State("up-project","filename"),
    State("refresh","data"),
    prevent_initial_call=True,
)
def on_load_project(content, fname, ref):
    if not content: return no_update, no_update, no_update
    try:
        _, b64 = content.split(",", 1)
        raw = base64.b64decode(b64)
        tmp = tempfile.NamedTemporaryFile(suffix=".gwz", delete=False)
        tmp.write(raw); tmp.close()
        load_project(tmp.name)
        os.unlink(tmp.name)
        msg = (f"✅ Proyecto cargado — {len(wells)} pozos, "
               f"{sum(len(w.points) for w in wells.values())} pts. "
               "El modelo RF no se restaura: re-entrenar en Paso 4.")
        return ref+1, msg, True
    except Exception as e:
        return no_update, f"❌ Error al cargar: {e}", True

@app.callback(
    Output("up-project","style"),
    Input("btn-load-project","n_clicks"),
    prevent_initial_call=True,
)
def trigger_load_project(n):
    return {"display":"block"} if n else no_update

# ─── T11: callbacks de exportar kit Cap.5 ─────────────────────────────────────
# (P3-3.3) "Exportar kit" (btn-kit-cap5) ahora pasa por el diálogo de
# confirmación único: on_export_trigger inicia el diálogo, on_export_confirm
# lanza el hilo de fondo (rama kind == "kit"). Solo queda el polling aquí.
@app.callback(
    Output("download-kit","data"),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Output("kit-interval","disabled",allow_duplicate=True),
    Input("kit-interval","n_intervals"),
    prevent_initial_call=True,
)
def on_kit_poll(n):
    with task_lock:
        done = kit_task_state["done"]
        err = kit_task_state["error"]
        data = kit_task_state["bytes"]
        stage = kit_task_state["stage"]
        pct = kit_task_state["progress"]
        fname = kit_task_state.get("filename", "kit_cap5.zip")
    if not done:
        return no_update, f"⏳ Kit: {stage} ({pct}%)", True, False
    if err:
        return no_update, f"❌ Kit: {err}", True, True
    kit_task_state["bytes"] = None
    return dcc.send_bytes(data, fname), "✅ Kit Cap.5 listo — descargando.", True, True

@app.callback(
    Output("well-report-modal","is_open"),
    Output("report-well-name","data"),
    Output("well-report-title","children"),
    Input({"type":"open-well-report","index":ALL},"n_clicks"),
    Input("close-well-report","n_clicks"),
    State("well-report-modal","is_open"),
    prevent_initial_call=True,
)
def toggle_well_report(open_clicks, close_click, is_open):
    ctx = callback_context
    if not ctx.triggered: return no_update, no_update, no_update
    triggered_id = ctx.triggered_id
    if triggered_id == "close-well-report":
        return False, no_update, no_update
    if isinstance(triggered_id, dict) and triggered_id.get("type") == "open-well-report":
        val = ctx.triggered[0]["value"]
        if not val: return no_update, no_update, no_update
        wn = triggered_id["index"]
        return True, wn, f"Reporte de pozo — {wn}"
    return no_update, no_update, no_update

@app.callback(
    Output("well-report-graph","figure"),
    Output("well-report-stats-table","children"),
    Input("report-well-name","data"),
    Input("well-report-vars","value"),
    Input("well-report-profile-var","value"),
)
def update_well_report(well_name, hist_vars, profile_var):
    if not well_name or well_name not in wells:
        return go.Figure(), html.Div()
    fig = build_well_report_figure(well_name, hist_vars, profile_var or "di")
    stats = well_basic_stats(well_name)
    rows = [dbc.Row([
        dbc.Col(html.Small(s["label"], style={"color":"#ccc"}), width=3),
        dbc.Col(html.Small(f"media={s['media']:.2f}", style={"color":"#aaa"}), width=2),
        dbc.Col(html.Small(f"mediana={s['mediana']:.2f}", style={"color":"#aaa"}), width=2),
        dbc.Col(html.Small(f"std={s['std']:.2f}", style={"color":"#aaa"}), width=2),
        dbc.Col(html.Small(f"[{s['min']:.1f}, {s['max']:.1f}]", style={"color":"#aaa"}), width=3),
    ], className="mb-1") for s in stats.values()]
    table = html.Div([
        html.Hr(),
        html.Small("Estadísticas básicas", style={"color":"#666","letterSpacing":"1px"}),
        html.Div(rows, className="mt-2"),
    ])
    return fig, table

# ─── RENDERERS ────────────────────────────────────────────────────────────────
def _diagnostico_calce():
    if not layers or not wells: return None
    dxf_bmin = np.min([l.bbox_min for l in layers.values()], axis=0)
    dxf_bmax = np.max([l.bbox_max for l in layers.values()], axis=0)
    pts = list(all_points())
    if not pts: return None
    coords = np.array([[p.este, p.norte, p.cota] for p in pts])
    valid = np.all(np.isfinite(coords), axis=1)
    coords = coords[valid]
    if coords.size == 0: return None
    p_bmin = coords.min(0); p_bmax = coords.max(0)
    overlap = np.all(p_bmax >= dxf_bmin) and np.all(p_bmin <= dxf_bmax)
    if overlap:
        return dbc.Alert([
            html.B("✅ MWD y DXF calzan en la misma zona UTM."), html.Br(),
            html.Small(f"DXF: E=[{dxf_bmin[0]:.0f},{dxf_bmax[0]:.0f}] N=[{dxf_bmin[1]:.0f},{dxf_bmax[1]:.0f}] Z=[{dxf_bmin[2]:.0f},{dxf_bmax[2]:.0f}]", style={"color":"#aaa"}), html.Br(),
            html.Small(f"MWD: E=[{p_bmin[0]:.0f},{p_bmax[0]:.0f}] N=[{p_bmin[1]:.0f},{p_bmax[1]:.0f}] Z=[{p_bmin[2]:.0f},{p_bmax[2]:.0f}]", style={"color":"#aaa"}),
        ], color="success", style={"fontSize":"11px","padding":"7px 10px"})
    else:
        return dbc.Alert([
            html.B("⚠ MWD y DXF NO están en la misma zona UTM."), html.Br(),
            html.Small(f"DXF: E=[{dxf_bmin[0]:.0f},{dxf_bmax[0]:.0f}] N=[{dxf_bmin[1]:.0f},{dxf_bmax[1]:.0f}]", style={"color":"#aaa"}), html.Br(),
            html.Small(f"MWD: E=[{p_bmin[0]:.0f},{p_bmax[0]:.0f}] N=[{p_bmin[1]:.0f},{p_bmax[1]:.0f}]", style={"color":"#aaa"}), html.Br(),
            html.Small("Causa: DQ y MW de planes distintos, o TMatrix inconsistente.", style={"color":"#F39C12"}),
        ], color="warning", style={"fontSize":"11px","padding":"7px 10px"})

def _step1():
    all_pts = list(all_points())
    n_dxf, n_wells = len(layers), len(wells)
    n_ucs = sum(1 for p in all_pts if p.dominio and domains.get(p.dominio, {}).get("ucs_lab"))
    n_no_ucs = len(all_pts) - n_ucs
    n_excel = len(excel_data)
    diag = _diagnostico_calce()
    status_block = dbc.Alert([
        html.B("Etiquetado automático punto a punto"), html.Br(),
        html.Small("El cruce geométrico DXF ↔ MWD determina qué puntos tienen UCS."),
        html.Hr(style={"margin":"6px 0"}),
        dbc.Row([
            dbc.Col([html.Div(str(len(all_pts)),style={"fontSize":"22px","fontWeight":700}),
                     html.Small("Total MWD",style={"color":"#aaa"})], width=4),
            dbc.Col([html.Div(str(n_ucs),style={"fontSize":"22px","fontWeight":700,"color":"#2ECC71"}),
                     html.Small("Con UCS → ML",style={"color":"#aaa"})], width=4),
            dbc.Col([html.Div(str(n_no_ucs),style={"fontSize":"22px","fontWeight":700,"color":"#aaa"}),
                     html.Small("Sin UCS",style={"color":"#aaa"})], width=4),
        ]),
    ], color="dark", style={"fontSize":"12px"}) if all_pts else None
    s_act = active_site()
    n_pend = pending_alias_count()
    n_bloq = len(training_blockers())
    n_sitio = len(site_pending_confirms)
    return html.Div([
        html.H6("Paso 1 — Cargar datos", className="mb-3"),
        # (P1) Sitio activo y estado del vocabulario, arriba de todo: la
        # partición por sitio y los pendientes no pueden estar escondidos.
        dbc.Alert([
            html.Div([
                html.B(f"⛏ Sitio: {s_act['display']} ({s_act['id']})"),
                dbc.Button("Abrir registro de vocabulario →", id="btn-open-vocab-step1",
                           size="sm", color="link",
                           style={"fontSize":"10px","padding":"0 0 0 8px"}),
            ]),
            html.Small(
                f"Un archivo de trabajo = una mina. Todo objeto a más de "
                f"{_num_cl(s_act['margen_m'])} m del centroide exige confirmación explícita.",
                style={"fontSize":"10px","color":"#aaa","display":"block"}),
            html.Div([
                dbc.Badge(f"🚫 {n_sitio} fuera de sitio", color="danger",
                          className="me-1", style={"fontSize":"10px"}) if n_sitio else None,
                dbc.Badge(f"🏷 {n_pend} pendiente{'s' if n_pend != 1 else ''} de asignar",
                          color="warning", className="me-1",
                          style={"fontSize":"10px"}) if n_pend else None,
                dbc.Badge(f"⛔ {n_bloq} atributo(s) sin banda de UCS", color="danger",
                          className="me-1", style={"fontSize":"10px"}) if n_bloq else None,
                dbc.Badge("vocabulario OK", color="success",
                          style={"fontSize":"10px"}) if not (n_sitio or n_pend or n_bloq) else None,
            ], className="mt-1"),
        ], color="dark", style={"fontSize":"11px","padding":"8px 12px"}),
        card("Mallas DXF", [
            html.Small("Sólidos 3DFACE en UTM. Asigna UCS a cada capa (panel inferior).",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            dbc.Button([f"📂 Cargar DXF ({n_dxf} cargadas)"], id="btn-dxf",
                       color="primary", outline=True, size="sm"),
        ]),
        card("Registros MWD (XML IREDES)", [
            html.Small("Archivos DQ (con TMatrix) + archivos MW. Se cargan juntos.",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            dbc.Button([f"📊 Cargar XMLs ({n_wells} pozos)"], id="btn-xml",
                       color="primary", outline=True, size="sm"),
        ]),
        dbc.Button("🔎 Vista previa del cruce DXF↔MWD (opcional)", id="btn-preview-cross",
                   color="success", outline=True, size="sm", className="mb-2") if layers and wells else None,
        status_block, diag,
        card("Excel calibrador (opcional)", [
            html.Small("Promedios por tiro con UCS asignado.",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            dbc.Button([f"📈 Cargar Excel ({n_excel} tiros)"], id="btn-excel",
                       color="secondary", outline=True, size="sm"),
        ]),
        card("Excel geomecánico caserón×litología (bandas UCS/RMR/RQD/GSI)", [
            html.Small("Rangos de laboratorio por caserón×litología. Alimenta las "
                       "bandas [UCS_lo, UCS_hi] de las capas DXF y la verificación de "
                       "consistencia (Paso 5).",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            dbc.Button([f"🧪 Cargar Excel geomecánico ({len(geomech_bands['records'])} bandas)"],
                       id="btn-geomech", color="secondary", outline=True, size="sm"),
        ]),
        card("Sondajes con testigo (P2)", [
            html.Small("header · survey · lithology · structure · geomec · density "
                       "(6 CSV, ';' / latin-1). Fuente de verdad INDEPENDIENTE del MWD: "
                       "desurvey por curvatura mínima y cruce traza↔malla determinan "
                       "qué pozos son relevantes para las mallas de litología cargadas.",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            dbc.Row([
                dbc.Col(dbc.Button(f"🗿 Cargar CSV de sondajes ({len(drillholes)} cargados)",
                                    id="btn-drillhole", color="secondary", outline=True, size="sm"),
                        width="auto"),
                dbc.Col(dbc.Button("Ver / seleccionar pozos →", id="btn-open-drillhole-step1",
                                    color="link", size="sm") if drillholes else None, width="auto"),
            ], className="g-2"),
        ]),
        card("Proyecto (.gwz)", [
            html.Small("Guarda/carga toda la sesión (pozos, DXF, configuración). "
                       "El modelo RF no se guarda: re-entrena al cargar.",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            dbc.Row([
                dbc.Col(dbc.Button("💾 Guardar proyecto", id="btn-save-project",
                                    color="info", outline=True, size="sm"), width="auto"),
                dbc.Col(dbc.Button("📂 Cargar proyecto", id="btn-load-project",
                                    color="info", outline=True, size="sm"), width="auto"),
            ], className="g-2"),
        ]),
        dbc.Row([
            dbc.Col(dbc.Alert("Carga al menos un XML MWD.", color="warning",
                              style={"fontSize":"11px","padding":"5px 10px"}) if n_wells == 0 else html.Div()),
            dbc.Col(dbc.Button("Siguiente →", id={"type":"pill","index":2}, color="info", size="sm",
                                disabled=n_wells == 0, className="float-end"), width="auto"),
        ], className="mt-3"),
    ])

def _step2():
    all_pts = list(all_points())
    active = sum(1 for p in all_pts if p.entrenable)
    n_excel = len(excel_data)
    var_labels = {"vel":"ROP [m/min]","pp":"Percusión","pa":"Avance",
                  "pd":"Damper","pr":"Rotación","pf":"Flujo"}
    def cal_row(k, lbl):
        raw_vals = [getattr(p, f"raw_{k}") for p in all_pts]
        if raw_vals and any(np.isfinite(v) for v in raw_vals):
            rng = f"raw:[{np.nanmin(raw_vals):.1f}, {np.nanmax(raw_vals):.1f}]"
        else: rng = "sin datos"
        return dbc.Row([
            dbc.Col(html.Small(lbl, style={"color":"#aaa"}), width=3),
            dbc.Col(dbc.Input(id=f"cal-{k}", type="number",
                               value=round(cal_factors.get(k, 1.0), 4),
                               step=0.0001, min=0.001, size="sm",
                               style={"fontSize":"11px"}), width=3),
            dbc.Col(html.Small(rng, style={"color":"#555","fontSize":"10px"}), width=6),
        ], className="g-1 mb-1")
    # (P3-3.8) El corte de emboquillado se APLICA (apply_inicio_filter) pero
    # antes no figuraba en ninguna lista de filtros. Se antepone como entrada
    # sintética de solo lectura — no es removible aquí porque no es un filtro
    # de clean_filters, es el corte base que recompute_filters() siempre
    # reaplica primero.
    n_cut = sum(1 for p in all_pts if p.largo < inicio_cut_m)
    filter_items = [dbc.ListGroupItem([
        html.Small(f"Emboquillado — largo < {inicio_cut_m:g} m",
                   style={"fontSize":"11px","marginRight":"6px","flex":1}),
        dbc.Badge(f"-{n_cut} pts", color="danger", className="me-2"),
        html.Small("fijo", style={"color":"#555","fontSize":"9px","padding":"0 7px"}),
    ], className="d-flex align-items-center py-1 px-2")]
    filter_items += [dbc.ListGroupItem([
        html.Small(f"{f['varName']} — {f['label']} [{f['lo']}, {f['hi']}]",
                   style={"fontSize":"11px","marginRight":"6px","flex":1}),
        dbc.Badge(f"-{f['removed']} pts", color="danger", className="me-2"),
        dbc.Button("✕", id={"type":"rm-filt","index":i}, size="sm", color="danger",
                   outline=True, style={"fontSize":"10px","padding":"0px 7px"}),
    ], className="d-flex align-items-center py-1 px-2") for i, f in enumerate(clean_filters)]
    return html.Div([
        html.H6("Paso 2 — Calibración y limpieza", className="mb-3"),
        card("Calibración de unidades", [
            html.Small("Factor = media_Excel / media_raw por variable.",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            *[cal_row(k, l) for k, l in var_labels.items()],
            dbc.Row([
                dbc.Col(dbc.Button("Aplicar", id="btn-cal-apply", color="info",
                                    outline=True, size="sm"), width="auto"),
                dbc.Col(dbc.Button("Derivar del Excel", id="btn-cal-derive",
                                    color="secondary", outline=True, size="sm",
                                    disabled=n_excel == 0), width="auto"),
            ], className="g-1 mt-2"),
        ]),
        card("Entrenamiento preliminar con Excel", [
            html.Small("Modelo RF rápido con promedios por tiro. Se descarta al hacer ML real.",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            dbc.Button(f"🧪 Entrenar preliminar ({n_excel} tiros)",
                       id="btn-prelim", color="warning", outline=True, size="sm",
                       disabled=n_excel == 0),
        ]) if n_excel else None,
        card("Filtros de limpieza (globales)", [
            dbc.Alert(f"Activos: {active}/{len(all_pts)} pts · {len(wells)} pozos",
                      color="info", style={"fontSize":"11px","padding":"4px 8px"}, className="mb-2"),
            dbc.Row([
                dbc.Col(html.Small("Corte emboquillado (m):", style={"color":"#aaa"}), width=5),
                dbc.Col(dbc.Input(id="val-cut", type="number", value=inicio_cut_m, step=0.1,
                                   min=0, size="sm", style={"fontSize":"11px"}), width=3),
                dbc.Col(dbc.Button("Aplicar", id="btn-cut", size="sm",
                                    color="secondary", outline=True), width=4),
            ], className="g-1 mb-2"),
            dbc.Row([
                dbc.Col(dcc.Dropdown(id="sel-norm-var", value="se", clearable=False,
                    options=[{"label":l,"value":k} for k,l in
                             {"se":"SE","vel":"ROP","pp":"PP","pa":"AP","pr":"RP","pd":"DP","pf":"FP"}.items()],
                    style={"fontSize":"11px"}), width=4),
                dbc.Col(dcc.Dropdown(id="sel-norm-method", value="outliers_iqr", clearable=False,
                    options=[{"label":l,"value":v} for l,v in
                             [("IQR 1.5×","outliers_iqr"),("Q25-Q75","q25_q75"),
                              ("5%-95%","whisker5"),("Q10-Q90","quantile_reg")]],
                    style={"fontSize":"11px"}), width=5),
                dbc.Col(dbc.Button("+", id="btn-add-filt", size="sm",
                                    color="secondary", outline=True), width=3),
            ], className="g-1 mb-2"),
            dbc.ListGroup(filter_items, flush=True),
        ]),
        dbc.Row([
            dbc.Col(dbc.Button("← Atrás", id={"type":"pill","index":1}, color="secondary", outline=True, size="sm"), width="auto"),
            dbc.Col(dbc.Button("Siguiente → DI", id={"type":"pill","index":3}, color="info", size="sm"),
                     width="auto", className="ms-auto"),
        ], className="mt-3"),
    ])

def _di_rqd_card():
    """
    (T5c) Card "Validación independiente DI ↔ RQD" del Paso 3. El RQD del
    Excel geomecánico proviene de mapeo/sondajes — es independiente del MWD —
    y es la única validación externa del DI disponible en la mina. Solo se
    muestra si hay geomech_bands cargadas; si no hay ningún caserón evaluable
    (falta asignar caserón a alguna capa, o falta calcular el DI), se explicita
    el requisito faltante en vez de un gráfico vacío.
    """
    if not geomech_bands["records"]:
        return card("Validación independiente DI ↔ RQD", [
            dbc.Alert("Carga el Excel geomecánico (Paso 1) para habilitar esta validación.",
                      color="secondary", style={"fontSize":"11px","padding":"6px 10px"}),
        ])
    result = di_rqd_correlation()
    data = result["data"]
    if not data:
        return card("Validación independiente DI ↔ RQD", [
            dbc.Alert(f"Ningún caserón evaluable todavía: asigna caserón a una capa DXF "
                      f"(árbol de capas) con banda RQD, y calcula el DI (≥{DI_RQD_MIN_PUNTOS} "
                      f"puntos MWD dentro de esa malla).",
                      color="secondary", style={"fontSize":"11px","padding":"6px 10px"}),
        ])
    if result["rho"] is None:
        badge = dbc.Badge(f"n={result['n']} caserones — {result['warning']}", color="warning")
    else:
        badge = dbc.Badge(f"Spearman ρ = {result['rho']:.3f}  (n={result['n']})",
                          color="success" if result["rho"] < 0 else "danger")
    return card("Validación independiente DI ↔ RQD", [
        html.Small("El RQD proviene de mapeo/sondajes: es independiente del MWD. Es la "
                   "única validación externa del DI disponible en la mina.",
                   style={"color":"#aaa","display":"block","marginBottom":"6px"}),
        badge,
        dcc.Graph(figure=build_di_rqd_figure(data), config={"displayModeBar": False},
                  style={"marginTop":"6px"}),
        dbc.Alert("Se espera anticorrelación (ρ<0). Una correlación nula o positiva sugiere "
                  "revisar pesos/ventana del DI o la asignación de caserones a las mallas.",
                  color="dark", style={"fontSize":"10px","padding":"6px 10px","marginTop":"6px"}),
        dbc.Button("CSV DI↔RQD por caserón", id={"type":"di-rqd-export-btn","index":0},
                   color="secondary", outline=True, size="sm", className="mt-2"),
    ])

def _di_sensitivity_card():
    """
    (T7a) Card "Análisis de sensibilidad" del Paso 3: recalcula el DI de un
    pozo con ventanas 10/14/20 (sin sobrescribir el DI oficial) para justificar
    la elección de ventana=14. Dropdown y botón viven en contenido regenerado
    (wz-content) → ids pattern-matching, nunca fijos. El resultado se calcula
    en un callback normal (rápido, un solo pozo) y no requiere hilo de fondo.
    """
    well_opts = [{"label": wn, "value": wn} for wn in wells.keys()]
    if not well_opts:
        return card("Análisis de sensibilidad (ventanas 10/14/20)", [
            dbc.Alert("Carga y matchea pozos primero.", color="secondary",
                      style={"fontSize":"11px","padding":"6px 10px"}),
        ])
    return card("Análisis de sensibilidad (ventanas 10/14/20)", [
        html.Small("Recalcula el DI del pozo elegido con ventanas 10, 14 y 20 muestras "
                   "SIN sobrescribir el DI oficial de los puntos — útil para justificar "
                   "en la memoria la elección de ventana=14.",
                   style={"color":"#aaa","display":"block","marginBottom":"8px"}),
        dbc.Row([
            dbc.Col(dcc.Dropdown(id={"type":"sens-well-sel","index":0}, options=well_opts,
                    value=well_opts[0]["value"], clearable=False,
                    style={"fontSize":"11px"}), width=8),
            dbc.Col(dbc.Button("Analizar", id={"type":"sens-btn","index":0},
                    color="info", outline=True, size="sm"), width=4),
        ], className="g-2 mb-2"),
        html.Div(id={"type":"sens-output","index":0}),
    ])

def _step3():
    all_pts = list(all_points())
    n_di = sum(1 for p in all_pts if p.di is not None)
    n_disc = sum(1 for p in all_pts if p.di is not None and p.di > di_threshold)
    return html.Div([
        html.H6("Paso 3 — Índice de discontinuidad (DI)", className="mb-3"),
        card("Fórmula", [
            html.Small("DIᵢ = √(Σⱼ βⱼ · zⱼ(i)²), ventana 14 muestras ≈ 26 cm.", style={"color":"#ccc"}),
            html.Br(), html.Br(),
            html.Small("Pesos Fernández et al. 2023: PP=0.35, DP=0.25, FP=0.20, RP=0.20",
                       style={"color":"#666"}),
        ]),
        card("Configuración", [
            html.Small(di_config_summary(), style={
                "color": "#2ECC71" if di_config_is_default() else "#F39C12",
                "display": "block", "marginBottom": "8px", "fontFamily": "monospace"}),
            dbc.Row([
                dbc.Col([html.Small("Ventana", style={"color":"#aaa","display":"block"}),
                          # (P1-T1.6) Sin min/max en el componente: un valor
                          # fuera de rango llegaría como None y se perdería en
                          # silencio. La validación vive en do_di.
                          dbc.Input(id="di-window", type="number", value=di_config["window"],
                                     step=1, size="sm", style={"fontSize":"11px"})], width=3),
                dbc.Col([html.Small("Umbral", style={"color":"#aaa","display":"block"}),
                          dbc.Input(id="di-thresh", type="number", value=di_threshold,
                                     step=0.1, size="sm", style={"fontSize":"11px"})], width=3),
                dbc.Col(dbc.Button("🌀 Calcular DI", id="btn-di", color="info", size="sm",
                                    className="mt-3"), width=3),
                dbc.Col(dbc.Button("↺ Restaurar Fernández et al. 2023", id="btn-di-reset",
                                    color="secondary", outline=True, size="sm",
                                    className="mt-3"), width=3),
            ], className="g-2 mb-2"),
            html.Small("Pesos (P3-3.7):", style={"color":"#aaa","display":"block","marginBottom":"4px"}),
            dbc.Row([
                dbc.Col([html.Small("PP", style={"color":"#666","display":"block"}),
                          dbc.Input(id="di-w-pp", type="number", value=di_config["weights"]["pp"],
                                     step=0.01, size="sm", style={"fontSize":"11px"})], width=3),
                dbc.Col([html.Small("DP", style={"color":"#666","display":"block"}),
                          dbc.Input(id="di-w-pd", type="number", value=di_config["weights"]["pd"],
                                     step=0.01, size="sm", style={"fontSize":"11px"})], width=3),
                dbc.Col([html.Small("FP", style={"color":"#666","display":"block"}),
                          dbc.Input(id="di-w-pf", type="number", value=di_config["weights"]["pf"],
                                     step=0.01, size="sm", style={"fontSize":"11px"})], width=3),
                dbc.Col([html.Small("RP", style={"color":"#666","display":"block"}),
                          dbc.Input(id="di-w-pr", type="number", value=di_config["weights"]["pr"],
                                     step=0.01, size="sm", style={"fontSize":"11px"})], width=3),
            ], className="g-2"),
        ]),
        dbc.Badge(f"DI: {n_di} pts · {n_disc} discontinuidades", color="success",
                  className="mb-2") if n_di else None,
        _di_sensitivity_card(),
        _di_rqd_card(),
        dbc.Row([
            dbc.Col(dbc.Button("← Atrás", id={"type":"pill","index":2}, color="secondary", outline=True, size="sm"), width="auto"),
            dbc.Col(dbc.Button("Siguiente → ML", id={"type":"pill","index":4}, color="info", size="sm",
                                disabled=n_di == 0), width="auto", className="ms-auto"),
        ], className="mt-3"),
    ])

def _training_composition_card():
    """
    (P3-3.2) De dónde salen los datos de entrenamiento, ANTES de entrenar:
    total disponible y cuántos sobreviven cada filtro, incluido el corte de
    emboquillado (P3-3.8), que antes se aplicaba sin figurar aquí.
    """
    rep = training_composition_report()
    rows = [html.Tr([
        html.Td(html.Small(st["label"], style={"fontSize":"10px"})),
        html.Td(html.Small(f"{st['quedan']:,}".replace(",", "."), style={"fontSize":"10px"})),
        html.Td(html.Small(f"-{st['perdidos']:,}".replace(",", ".") if st["perdidos"] else "",
                          style={"fontSize":"10px","color":"#E74C3C"})),
    ]) for st in rep["funnel"]]
    return card("Composición del entrenamiento", [
        html.Small(f"{rep['n_total']:,} puntos MWD disponibles → {rep['n_final']:,} entrenables."
                   .replace(",", "."),
                   style={"color":"#aaa","display":"block","marginBottom":"6px"}),
        dbc.Table([
            html.Thead(html.Tr([html.Th("Etapa"), html.Th("Quedan"), html.Th("Perdidos")])),
            html.Tbody(rows),
        ], bordered=False, size="sm", style={"marginBottom":0}),
    ])


def _varjust_section_alert(rep):
    """Alerta uniforme para un estado 'sin_datos'/'sin_grupos'/'sin_caserones'."""
    return dbc.Alert(rep.get("motivo", "Sin datos suficientes todavía."),
                     color="secondary", style={"fontSize": "11px"})


def _varjust_panel_body():
    """
    (P3-3.9) Renderiza las cuatro secciones del reporte de justificación de
    variables. Cada sección se calcula al abrir el modal, sobre los datos
    vigentes: cuando no alcanzan, muestra el motivo en vez de un gráfico
    vacío o un número inventado.
    """
    rep = variable_justification_report()
    sections = []

    # 1) Correlación / multicolinealidad -------------------------------
    corr = rep["correlacion"]
    body = []
    if corr["status"] != "ok":
        body.append(_varjust_section_alert(corr))
    else:
        feats = corr["features"]
        fig = go.Figure(data=go.Heatmap(
            z=corr["matrix"], x=feats, y=feats, zmin=-1, zmax=1,
            colorscale="RdBu_r", reversescale=False,
            text=[[f"{v:.2f}" for v in row] for row in corr["matrix"]],
            texttemplate="%{text}", colorbar=dict(title="r")))
        fig.update_layout(template="plotly_dark", height=360,
                          margin=dict(l=40, r=10, t=10, b=30),
                          paper_bgcolor="#111", plot_bgcolor="#111")
        body.append(dcc.Graph(figure=fig, config={"displayModeBar": False}))
        corr_y_rows = [html.Tr([html.Td(html.Small(f, style={"fontSize":"10px"})),
                                html.Td(html.Small(f"{r:.3f}", style={"fontSize":"10px"}))])
                      for f, r in zip(feats, corr["corr_con_y"])]
        body.append(dbc.Table([
            html.Thead(html.Tr([html.Th("Variable"), html.Th("r con UCS")])),
            html.Tbody(corr_y_rows),
        ], bordered=False, size="sm", className="mt-2"))
        if corr["pairs_flagged"]:
            body.append(dbc.Alert([
                html.Small(f"Multicolinealidad (|r| > {corr['threshold']}): se conservan "
                          "ambas variables por defecto; la exclusión es una decisión manual.",
                          style={"display":"block","marginBottom":"4px"}),
                html.Ul([html.Li(html.Small(
                    f"{pr['a']} ↔ {pr['b']} (r={pr['r']}) — sugerencia: quitar {pr['sugerencia_quitar']}",
                    style={"fontSize":"10px"})) for pr in corr["pairs_flagged"]]),
            ], color="warning", className="mt-2"))
        else:
            body.append(html.Small("Sin pares con |r| por sobre el umbral.",
                                   style={"color":"#5cb85c","fontSize":"10px"}))
    sections.append(card("1. Correlación entre predictores y multicolinealidad", body))

    # 2) Importancia de variables ---------------------------------------
    imp = rep["importancia"]
    if not imp:
        body = [dbc.Alert("Entrena el modelo (Paso 4) para calcular la importancia de "
                          "variables por permutación.", color="secondary", style={"fontSize":"11px"})]
    else:
        ordered = sorted(imp.items(), key=lambda kv: -kv[1])
        body = [dbc.Table([
            html.Thead(html.Tr([html.Th("Variable"), html.Th("Importancia (permutación)")])),
            html.Tbody([html.Tr([html.Td(html.Small(k, style={"fontSize":"10px"})),
                                 html.Td(html.Small(f"{v:.4f}", style={"fontSize":"10px"}))])
                       for k, v in ordered]),
        ], bordered=False, size="sm")]
    sections.append(card("2. Importancia de variables (modelo entrenado)", body))

    # 3) Comparación de modelos, con / sin SE ----------------------------
    def _cmp_table(cmp_rep):
        if cmp_rep["status"] != "ok":
            return _varjust_section_alert(cmp_rep)
        rows = []
        for r in cmp_rep["rows"]:
            if r["error"]:
                rows.append(html.Tr([html.Td(html.Small(r["modelo"], style={"fontSize":"10px"})),
                                     html.Td(html.Small(f"error: {r['error']}",
                                                        style={"fontSize":"10px","color":"#E74C3C"}),
                                            colSpan=2)]))
            else:
                rows.append(html.Tr([
                    html.Td(html.Small(r["modelo"], style={"fontSize":"10px"})),
                    html.Td(html.Small(f"{r['r2_mean']:.3f} ± {r['r2_std']:.3f}", style={"fontSize":"10px"})),
                    html.Td(html.Small(f"{r['rmse_mean']:.1f} ± {r['rmse_std']:.1f}", style={"fontSize":"10px"})),
                ]))
        return dbc.Table([
            html.Thead(html.Tr([html.Th("Modelo"), html.Th("R² (CV por pozo)"), html.Th("RMSE")])),
            html.Tbody(rows),
        ], bordered=False, size="sm")

    sections.append(card("3. Comparación de modelos", [
        html.Small("Con proxy SE:", style={"color":"#aaa","display":"block","marginBottom":"4px"}),
        _cmp_table(rep["comparacion_con_se"]),
        html.Small("Sin proxy SE:", style={"color":"#aaa","display":"block","margin":"10px 0 4px"}),
        _cmp_table(rep["comparacion_sin_se"]),
    ]))

    # 4) Ablación de cota (LOCO-CV) ---------------------------------------
    abl = rep["ablacion_cota"]
    if abl["status"] != "ok":
        body = [_varjust_section_alert(abl)]
    else:
        def _fmt(pair):
            r2, err = pair
            return f"{r2:.3f}" if r2 is not None else f"— ({err})"
        rows = [
            html.Tr([html.Td(html.Small("Dentro del caserón (GroupKFold por pozo)", style={"fontSize":"10px"})),
                    html.Td(html.Small(_fmt(abl["dentro_caseron_sin_cota"]), style={"fontSize":"10px"})),
                    html.Td(html.Small(_fmt(abl["dentro_caseron_con_cota"]), style={"fontSize":"10px"}))]),
            html.Tr([html.Td(html.Small("LOCO-CV (deja un caserón fuera)", style={"fontSize":"10px"})),
                    html.Td(html.Small(_fmt(abl["loco_sin_cota"]), style={"fontSize":"10px"})),
                    html.Td(html.Small(_fmt(abl["loco_con_cota"]), style={"fontSize":"10px"}))]),
        ]
        body = [
            html.Small(f"{abl['n_samples']} puntos · caserones: {', '.join(abl['caserones'])}",
                       style={"color":"#aaa","display":"block","marginBottom":"6px"}),
            dbc.Table([
                html.Thead(html.Tr([html.Th("Validación"), html.Th("R² sin cota"), html.Th("R² con cota")])),
                html.Tbody(rows),
            ], bordered=False, size="sm"),
        ]
        if abl["memorizacion_espacial_sospechosa"] is True:
            body.append(dbc.Alert(
                "La cota mejora mucho más el desempeño dentro-del-caserón que en LOCO-CV: "
                "señal de que el modelo memoriza posición en vez de leer el MWD. Confirma "
                "que ML_FEATURES nunca incluya coordenadas en producción.",
                color="danger", className="mt-2", style={"fontSize":"11px"}))
        elif abl["memorizacion_espacial_sospechosa"] is False:
            body.append(html.Small("Sin señal de memorización espacial con este umbral.",
                                   style={"color":"#5cb85c","fontSize":"10px","display":"block","marginTop":"6px"}))
    sections.append(card("4. Ablación de cota — prueba de memorización espacial (LOCO-CV)", body))

    return html.Div(sections)


def _step4():
    all_pts = list(all_points())
    return html.Div([
        html.H6("Paso 4 — Modelo ML (UCS)", className="mb-3"),
        _training_composition_card(),
        dbc.Button("📐 Reporte de justificación de variables", id="btn-open-varjust",
                   color="link", size="sm", className="mb-2",
                   style={"padding":"0","fontSize":"11px"}),
        dbc.Row([
            # (P1-T1.6) Sin min/max en el componente: con ellos un valor fuera
            # de rango llega como None y `float(v or default)` lo sustituía en
            # silencio por el default, excluyendo una litología entera. La
            # validación vive en do_ml y rechaza con mensaje visible.
            dbc.Col([html.Small("UCS mín [MPa]", style={"color":"#aaa","display":"block"}),
                      dbc.Input(id="ucs-min", type="number", value=ucs_range["ucs_min"],
                                 step=5, size="sm", style={"fontSize":"11px"})], width=3),
            dbc.Col([html.Small("UCS máx [MPa]", style={"color":"#aaa","display":"block"}),
                      dbc.Input(id="ucs-max", type="number", value=ucs_range["ucs_max"],
                                 step=5, size="sm", style={"fontSize":"11px"})], width=3),
            dbc.Col(html.Small(f"Físico: [{UCS_CONFIG['physical_min']},{UCS_CONFIG['physical_max']}] MPa",
                                style={"color":"#555","fontSize":"10px","alignSelf":"flex-end"}), width=6),
        ], className="g-2 mb-2"),
        dbc.Button("🧠 Ejecutar Cruce + ML", id="btn-ml", color="info", size="sm",
                   disabled=task_state["running"]),
        html.Div([
            html.Small(id="ml-stage-label",
                       children=task_state["stage"] or "Sin ejecutar todavía.",
                       style={"color":"#aaa","display":"block","marginTop":"8px","marginBottom":"3px"}),
            dbc.Progress(id="ml-progress-bar", value=task_state["progress"],
                         label=f"{task_state['progress']}%", striped=task_state["running"],
                         animated=task_state["running"], style={"height":"18px"}),
            html.Div(id="ml-log-box", className="mt-2",
                     children=html.Div([
                         html.Div(line, style={"fontFamily":"monospace","fontSize":"10px","color":"#aaa"})
                         for line in task_state["log"][-40:]
                     ], style={"maxHeight":"140px","overflowY":"auto","background":"#050508",
                               "padding":"6px 8px","borderRadius":"4px","border":"1px solid #222"})),
        ], className="mb-2"),
        html.Div(id="ml-result", className="mb-2"),
        dbc.Row([
            dbc.Col(dbc.Button("← Atrás", id={"type":"pill","index":3}, color="secondary", outline=True, size="sm"), width="auto"),
            dbc.Col(dbc.Button("Siguiente → Dominios", id={"type":"pill","index":5}, color="info", size="sm",
                                disabled=rf_model is None), width="auto", className="ms-auto"),
        ], className="mt-3"),
    ])

def _domain_report_table():
    """
    Reporte de dominios geomecánicos detectados: litología, estructura,
    UCS-ML medio, DI medio y cantidad de tramos por dominio.
    """
    if not domain_groups:
        return dbc.Alert("Aún no se han agrupado dominios. Usa 'Agrupar dominios' primero.",
                          color="secondary", style={"fontSize":"11px","padding":"6px 10px"})
    rows = [gw_row for gw_row in sorted(domain_groups, key=lambda g: -g["count"])]
    def pct_compat(g):
        """% de puntos del dominio con banda compatible (sobre los evaluables)."""
        pts = g.get("pts", [])
        evaluados = [p for p in pts if p.band_check is not None]
        if not evaluados: return None
        comp = sum(1 for p in evaluados if p.band_check == "compatible")
        return 100.0 * comp / len(evaluados)
    def pct_cell(v):
        if v is None:
            return html.Small("—", style={"color":"#666"})
        color = "#2ECC71" if v >= 70 else ("#F1C40F" if v >= 40 else "#E74C3C")
        return html.Small(f"{v:.0f}%", style={"color":color, "fontWeight":700})
    header = dbc.Row([
        dbc.Col(html.Small("Dominio", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("Litología", style={"color":"#888","fontWeight":700}), width=2),
        dbc.Col(html.Small("Estructura", style={"color":"#888","fontWeight":700}), width=2),
        dbc.Col(html.Small("UCS-ML medio", style={"color":"#888","fontWeight":700}), width=2),
        dbc.Col(html.Small("DI medio", style={"color":"#888","fontWeight":700}), width=2),
        dbc.Col(html.Small("N tramos", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("% compat.", style={"color":"#888","fontWeight":700}), width=2),
    ], className="mb-1")
    body = [dbc.Row([
        dbc.Col(html.Small(g["id"], style={"color":"#3B8BD4","fontWeight":700}), width=1),
        dbc.Col(html.Small(g["lito"] or "—", style={"color":"#ccc"}), width=2),
        dbc.Col(html.Small(g["estructura"] or "—", style={"color":"#ccc"}), width=2),
        dbc.Col(html.Small(f"{g['ucsMean']:.1f} MPa", style={"color":"#2ECC71"}), width=2),
        dbc.Col(html.Small(f"{g['diMean']:.3f}", style={"color":"#EF9F27"}), width=2),
        dbc.Col(html.Small(str(g["count"]), style={"color":"#aaa"}), width=1),
        dbc.Col(pct_cell(pct_compat(g)), width=2),
    ], className="mb-1 py-1", style={"borderBottom":"1px solid #1a1a1a"}) for g in rows]
    return card(f"Dominios detectados ({len(domain_groups)})", [header] + body)

def _mesh_validation_card():
    """
    (T4e) Card "Validación de capas DXF" del Paso 5: tabla por malla de
    estructura, histograma de offsets y export CSV. Los componentes
    interactivos usan ids pattern-matching (viven en contenido regenerado);
    el cálculo corre en hilo de fondo (val_task_state + val-task-poll).
    """
    struct_layers = [n for n, l in layers.items() if l.kind == "estructura"]
    body = [html.Small(
        "Consistencia multipozo: si ≥3 pozos cruzan la misma estructura y sus "
        "picos DI apareados están sistemáticamente desplazados respecto de la "
        "malla, la evidencia favorece que la malla está corrida. El emboquillado "
        "se excluye con el corte existente (puntos no entrenables).",
        style={"color":"#aaa","display":"block","marginBottom":"8px"})]
    if not struct_layers:
        body.append(dbc.Alert("No hay mallas de estructura cargadas (el tipo se "
                              "infiere del nombre del DXF: falla/fault/struct/fractura).",
                              color="secondary", style={"fontSize":"11px","padding":"6px 10px"}))
    body.append(dbc.Button("🧭 Validar posición de mallas",
                           id={"type":"val-mesh-btn","index":0}, color="info",
                           outline=True, size="sm", className="mb-2",
                           disabled=not struct_layers or not wells))
    # Progreso de la tarea de fondo (lo actualiza el polling val-task-poll)
    body.append(dbc.Progress(id={"type":"val-progress","index":0},
                             value=val_task_state["progress"],
                             label=f"{val_task_state['progress']}%" if val_task_state["running"] else "",
                             striped=val_task_state["running"], animated=val_task_state["running"],
                             style={"height":"14px","fontSize":"9px","marginBottom":"4px"}))
    body.append(html.Small(id={"type":"val-progress-txt","index":0},
                           children=val_task_state["stage"] if val_task_state["running"] else "",
                           style={"color":"#777","fontSize":"10px","display":"block","marginBottom":"6px"}))
    if mesh_validation_results:
        header = dbc.Row([
            dbc.Col(html.Small("Malla", style={"color":"#888","fontWeight":700}), width=3),
            dbc.Col(html.Small("Cruzan", style={"color":"#888","fontWeight":700}), width=1),
            dbc.Col(html.Small("Apareados", style={"color":"#888","fontWeight":700}), width=1),
            dbc.Col(html.Small("Offset [m]", style={"color":"#888","fontWeight":700}), width=2),
            dbc.Col(html.Small("Offset ⊥ [m]", style={"color":"#888","fontWeight":700}), width=2),
            dbc.Col(html.Small("Veredicto", style={"color":"#888","fontWeight":700}), width=3),
        ], className="mb-1")
        rows = []
        for r in mesh_validation_results:
            off_txt = (f"{r['offset_medio']:+.2f} ± {r['offset_std']:.2f}"
                       if r["offset_medio"] is not None else "—")
            offn_txt = (f"{r['offset_normal_medio']:+.2f} ± {r['offset_normal_std']:.2f}"
                        if r["offset_normal_medio"] is not None else "—")
            ok = r["veredicto"] == "consistente"
            ver_color = "#2ECC71" if ok else ("#F1C40F" if r["veredicto"].startswith(("sin", "insuf")) else "#E74C3C")
            rows.append(dbc.Row([
                dbc.Col(html.Small(r["malla"], style={"color":"#ccc"}), width=3),
                dbc.Col(html.Small(str(r["n_pozos_cruzan"]), style={"color":"#aaa"}), width=1),
                dbc.Col(html.Small(str(r["n_pozos_apareados"]), style={"color":"#aaa"}), width=1),
                dbc.Col(html.Small(off_txt, style={"color":"#EF9F27"}), width=2),
                dbc.Col(html.Small(offn_txt, style={"color":"#EF9F27"}), width=2),
                dbc.Col(html.Small(r["veredicto"], style={"color":ver_color,"fontWeight":700}), width=3),
            ], className="mb-1 py-1", style={"borderBottom":"1px solid #1a1a1a"}))
        body.extend([header] + rows)
        # Histograma de offsets (solo lectura: no participa en callbacks)
        fig = go.Figure()
        for r in mesh_validation_results:
            if r["offsets"]:
                fig.add_trace(go.Histogram(x=r["offsets"], name=r["malla"],
                                           nbinsx=20, opacity=0.7))
        fig.add_vline(x=0, line_dash="dash", line_color="#888")
        fig.update_layout(barmode="overlay", template="plotly_dark",
                          paper_bgcolor="#0d0d1a", plot_bgcolor="#0d0d1a", height=240,
                          margin=dict(l=40, r=10, t=10, b=35),
                          xaxis_title="Offset pico − malla [m]", yaxis_title="N pares",
                          legend=dict(font=dict(size=9)))
        body.append(dcc.Graph(figure=fig, config={"displayModeBar": False},
                              style={"marginTop":"6px"}))
        body.append(dbc.Button("CSV detalle por pozo",
                               id={"type":"val-export-btn","index":0},
                               color="secondary", outline=True, size="sm", className="mt-2"))
    return card("Validación de capas DXF (consistencia multipozo)", body)

def _step5():
    all_pts = list(all_points())
    n_nodom = sum(1 for p in all_pts if not p.dominio)
    return html.Div([
        html.H6("Paso 5 — Dominios geomecánicos", className="mb-3"),
        card("Agrupación", [
            dbc.Row([
                dbc.Col([html.Small("Tol UCS", style={"color":"#aaa","display":"block"}),
                          dbc.Input(id="tol-ucs", type="number", value=20, min=1, step=1,
                                     size="sm", style={"fontSize":"11px"})], width=3),
                dbc.Col([html.Small("Tol DI", style={"color":"#aaa","display":"block"}),
                          dbc.Input(id="tol-di", type="number", value=0.15, min=0.01, step=0.01,
                                     size="sm", style={"fontSize":"11px"})], width=3),
                dbc.Col([html.Small("Tramo (m)", style={"color":"#aaa","display":"block"}),
                          dbc.Input(id="tol-int", type="number", value=group_interval_m,
                                     min=0.5, step=0.5, size="sm", style={"fontSize":"11px"})], width=3),
            ], className="g-2 mb-2"),
            dbc.Button("🔀 Agrupar dominios", id="btn-group", color="info", outline=True, size="sm"),
        ]),
        _domain_report_table(),
        _mesh_validation_card(),
        card("Predicción sin DXF", [
            html.Small(f"{n_nodom} pts sin dominio DXF recibirán grupo inferido.",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            dbc.Button("🎯 Ejecutar predicción", id="btn-pred", color="warning",
                       outline=True, size="sm", disabled=not domain_groups),
        ]),
        card("Recomendación Top-N de parámetros de perforación", [
            html.Small("Selecciona un dominio y el criterio de selección. Los segmentos "
                       "candidatos siempre pertenecen al mismo dominio predicho por el ML.",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            dbc.Row([
                dbc.Col(dcc.Dropdown(id="topn-domain", clearable=False,
                    options=[{"label":f"{g['id']} ({g['lito'] or '—'} / {g['estructura'] or '—'})",
                              "value":g["id"]} for g in domain_groups],
                    value=domain_groups[0]["id"] if domain_groups else None,
                    style={"fontSize":"11px"}), width=5),
                dbc.Col(dcc.Dropdown(id="topn-method", clearable=False,
                    options=[
                        {"label":"Mínima variación interna de SE (cm a cm)","value":"min_se_cv"},
                        {"label":"Mínima SE (más eficiente energéticamente)","value":"min_se"},
                        {"label":"Máxima ROP (mayor productividad)","value":"max_rop"},
                    ], value="min_se_cv", style={"fontSize":"11px"}), width=5),
                dbc.Col(dbc.Button("Top-5", id="btn-topn", color="info", outline=True, size="sm"), width=2),
            ], className="g-1 mb-2") if domain_groups else
                html.Small("Agrupa dominios primero.", style={"color":"#555"}),
            html.Div(id="topn-result"),
        ]),
        card("Exportar", [
            dbc.Row([
                dbc.Col(dbc.Button("CSV dominios", id="btn-exp-dom", color="secondary",
                                    outline=True, size="sm"), width="auto"),
                dbc.Col(dbc.Button("CSV predicciones", id="btn-exp-pred", color="secondary",
                                    outline=True, size="sm"), width="auto"),
                dbc.Col(dbc.Button("📦 Exportar kit Cap.5", id="btn-kit-cap5",
                                    color="warning", outline=True, size="sm"), width="auto"),
            ], className="g-1"),
        ]),
        dbc.Button("← Atrás", id={"type":"pill","index":4}, color="secondary", outline=True, size="sm", className="mt-3"),
    ])

if __name__ == "__main__":
    print(f"\n{'='*65}\n  {APP_TITLE} v{APP_VERSION}")
    print(f"  Formación Punta del Cobre — UCS: {UCS_CONFIG['default_min']}–{UCS_CONFIG['default_max']} MPa")
    print(f"{'='*65}")
    if IN_COLAB:
        try:
            from pyngrok import ngrok
            public_url = ngrok.connect(PORT)
            print(f"\n  ✅ URL: {public_url}\n")
        except Exception:
            print(f"\n  ⚠ Configura pyngrok:\n     !pip install pyngrok -q\n     !ngrok authtoken TU_TOKEN\n")
    else:
        print(f"\n  Abre: http://localhost:{PORT}\n")
    app.run(debug=False, host="0.0.0.0", port=PORT)
