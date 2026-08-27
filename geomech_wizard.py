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

import os, sys, json, time, base64, tempfile, re, warnings, threading, traceback, math, hashlib, collections
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
from sklearn.model_selection import cross_val_score, cross_val_predict, cross_validate, GroupKFold, LeaveOneGroupOut
from sklearn.inspection import permutation_importance
from sklearn.cluster import DBSCAN
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
    # Mediana de las probetas, cuando la faena la documenta. No se calcula
    # desde min/max/media: sin los datos de probeta no existe, y fabricarla
    # sería inventar una estadística.
    ucs_mediana: Optional[float] = None
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

    def ucs_ancla(self, modo: Optional[str] = None) -> Optional[float]:
        """
        Valor puntual de UCS a usar como etiqueta. None si no hay banda.

        Una banda de UCS no es un número sino una ESTADÍSTICA, así que cuál se
        usa como etiqueta es una decisión y no un detalle: `modo` la nombra y
        el perfil de faena la guarda.

          central      el valor documentado como central (σci de Hoek-Brown),
                       distinto de una media aritmética de probetas.
          media        la media de las probetas.
          mediana      la mediana, si la faena la documenta.
          rango_medio  el punto medio de la banda min-max.

        Un modo sin dato documentado devuelve None en vez de caer en silencio
        a otra estadística: entregar la media cuando se pidió la mediana es
        exactamente la clase de sustitución silenciosa que el proyecto prohíbe.

        `auto` (y `modo=None`) mantiene el orden histórico —central, si no
        media, si no punto medio del rango, si no el extremo que haya— y es el
        defecto: un modo estricto deja sin etiqueta a los atributos que no
        documentan esa estadística, y esos puntos saldrían del entrenamiento
        sin que ninguna métrica lo delate.
        """
        if modo in (None, "auto"):
            if self.ucs_central is not None: return float(self.ucs_central)
            if self.ucs_media is not None: return float(self.ucs_media)
            if self.ucs_min is not None and self.ucs_max is not None:
                return (float(self.ucs_min) + float(self.ucs_max)) / 2.0
            for v in (self.ucs_min, self.ucs_max):
                if v is not None: return float(v)
            return None
        if modo == "central":
            return float(self.ucs_central) if self.ucs_central is not None else None
        if modo == "media":
            return float(self.ucs_media) if self.ucs_media is not None else None
        if modo == "mediana":
            return float(self.ucs_mediana) if self.ucs_mediana is not None else None
        if modo == "rango_medio":
            if self.ucs_min is not None and self.ucs_max is not None:
                return (float(self.ucs_min) + float(self.ucs_max)) / 2.0
            return None
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


# ─── ALTA Y BAJA DE ATRIBUTOS DESDE LA APLICACIÓN ───────────────────────────
# El registro se siembra con la Tabla 3.2 de Karzulovic, que caracteriza cinco
# unidades de Punta del Cobre. Pucobre opera TRES faenas con litologías
# distintas, y el propio MPC ya tiene unidades fuera de esa tabla (las Calizas
# de la Formación Abundancia; las mallas de PCS_1059). Sin alta/baja en
# caliente, registrar cualquiera de ellas obliga a editar
# seed_attribute_registry() en el fuente, lo que hace la plataforma
# intransferible a otra faena sin un programador.

def create_attribute(attr_id: str, nombre_oficial: str, rol: str = "litologia",
                     nivel: str = "unidad", padre: Optional[str] = None,
                     **campos) -> Attribute:
    """
    Registra un atributo canónico nuevo. Valida ANTES de tocar el registro:
    un atributo a medias es peor que ninguno, porque contamina el
    entrenamiento y la matriz de traslape sin que nada lo delate.

    `campos` acepta el resto de los campos de Attribute (ucs_min, ucs_max,
    ucs_media, ucs_central, dispersion_min/max, ucs_cv, ucs_sd, ucs_n,
    calidad, fuente, mi, modulo_E, poisson, densidad, notas...).

    Lanza ValueError con el motivo concreto; nunca corrige en silencio.
    """
    aid = (attr_id or "").strip()
    nombre = (nombre_oficial or "").strip()
    if not aid:
        raise ValueError("El id del atributo no puede estar vacío.")
    if not nombre:
        raise ValueError(f"'{aid}': el nombre oficial no puede estar vacío.")
    if aid in attr_registry:
        raise ValueError(f"'{aid}' ya existe en el registro "
                         f"({attr_registry[aid].nombre_oficial}). Edítalo en vez de "
                         f"volver a crearlo, o usa otro id.")
    if rol not in ATTR_ROLES:
        raise ValueError(f"'{aid}': rol '{rol}' inválido. Válidos: {', '.join(ATTR_ROLES)}.")
    if nivel not in ("unidad", "subunidad"):
        raise ValueError(f"'{aid}': nivel '{nivel}' inválido (unidad | subunidad).")
    if nivel == "subunidad":
        if not padre:
            raise ValueError(f"'{aid}': una subunidad debe declarar su unidad padre.")
        p = attr_registry.get(padre)
        if p is None:
            raise ValueError(f"'{aid}': el padre '{padre}' no existe en el registro.")
        if p.nivel != "unidad":
            raise ValueError(f"'{aid}': el padre '{padre}' es una subunidad, no una unidad.")
        if p.rol != rol:
            raise ValueError(f"'{aid}': rol '{rol}' distinto del de su padre '{padre}' "
                             f"('{p.rol}'). La jerarquía solo existe dentro de un rol.")
    elif padre:
        raise ValueError(f"'{aid}': es unidad pero declara padre '{padre}'.")

    validos = set(Attribute.__dataclass_fields__)
    desconocidos = set(campos) - validos
    if desconocidos:
        raise ValueError(f"'{aid}': campo(s) desconocido(s): {', '.join(sorted(desconocidos))}.")

    # (T1.6) Límites físicos de UCS: se RECHAZA, nunca se trunca en silencio.
    lo, hi = UCS_CONFIG["physical_min"], UCS_CONFIG["physical_max"]
    for c in ("ucs_min", "ucs_max", "ucs_media", "ucs_central",
              "dispersion_min", "dispersion_max"):
        v = campos.get(c)
        if v is None: continue
        try: v = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"'{aid}': {c}='{campos[c]}' no es un número.")
        if not (lo <= v <= hi):
            raise ValueError(f"'{aid}': {c}={v:g} MPa fuera del rango físico "
                             f"[{lo:g}, {hi:g}]. No se trunca: corrige el valor.")
        campos[c] = v
    for lo_c, hi_c in (("ucs_min", "ucs_max"), ("dispersion_min", "dispersion_max")):
        a_, b_ = campos.get(lo_c), campos.get(hi_c)
        if a_ is not None and b_ is not None and a_ > b_:
            raise ValueError(f"'{aid}': {lo_c}={a_:g} > {hi_c}={b_:g}.")
    if "calidad" in campos and campos["calidad"] not in QUALITY_LABELS:
        raise ValueError(f"'{aid}': calidad {campos['calidad']} fuera del catálogo "
                         f"{sorted(QUALITY_LABELS)}.")
    # (A.1) La banda de UCS es propiedad de la litología: ofrecérsela a otro
    # rol dejaría el registro en un estado que validate_attribute_tree marca
    # como inválido apenas se recargue.
    if rol not in ROLES_CON_BANDA_UCS:
        sucios = [c for c in ("ucs_min", "ucs_max", "ucs_media", "ucs_central",
                              "ucs_sd", "ucs_n", "dispersion_min", "dispersion_max", "ucs_cv")
                  if campos.get(c) is not None]
        if sucios:
            raise ValueError(f"'{aid}': el rol '{rol}' no lleva banda de UCS, pero se "
                             f"le pasó {', '.join(sucios)}. La banda es propiedad de "
                             f"la litología.")

    a = Attribute(id=aid, nombre_oficial=nombre, rol=rol, nivel=nivel, padre=padre, **campos)
    attr_registry[aid] = a
    log_warn(f'Vocabulario: atributo "{aid}" ({nombre}) creado · rol={rol} · '
             f'nivel={nivel}' + (f' · padre={padre}' if padre else '') +
             (f' · UCS ancla={a.ucs_ancla():g} MPa' if a.ucs_ancla() is not None else
              ' · SIN banda de UCS'))
    return a


def attribute_usage(attr_id: str) -> Dict:
    """Dónde está en uso un atributo: capas, puntos clasificados y alias."""
    capas = sorted(n for n, lay in layers.items()
                   if attr_id in (getattr(lay, "atributos", None) or {}).values())
    alias = sorted(al.texto_crudo for al in alias_registry.values()
                   if attr_id in al.atributos.values())
    return {"capas": capas, "puntos": attribute_point_counts().get(attr_id, 0),
            "alias": alias, "hijos": sorted(attribute_children(attr_id))}


def delete_attribute(attr_id: str, force: bool = False) -> Dict:
    """
    Elimina un atributo del registro. Si está EN USO —referenciado por capas
    cargadas o por puntos ya clasificados— exige `force=True`: borrarlo en
    silencio dejaría puntos apuntando a un id fantasma y el entrenamiento
    etiquetaría contra un dominio que ya no existe.

    Una unidad con subunidades NUNCA se borra (las dejaría huérfanas): hay
    que borrar o reasignar las subunidades primero.

    Los alias que apuntaban al atributo se van con él —quedarían resolviendo
    a un id inexistente— y el reporte los nombra.
    """
    if attr_id not in attr_registry:
        raise KeyError(f"Atributo '{attr_id}' no existe en el registro.")
    uso = attribute_usage(attr_id)
    if uso["hijos"]:
        raise ValueError(f"'{attr_id}' tiene subunidades ({', '.join(uso['hijos'])}); "
                         f"borrarlo las dejaría huérfanas. Bórralas o reasígnalas primero.")
    if not force and (uso["capas"] or uso["puntos"]):
        detalle = []
        if uso["capas"]: detalle.append(f"{len(uso['capas'])} capa(s): {', '.join(uso['capas'][:5])}")
        if uso["puntos"]: detalle.append(f"{uso['puntos']} punto(s) clasificado(s)")
        raise ValueError(f"'{attr_id}' está en uso por {' y '.join(detalle)}. "
                         f"Usa force=True si de verdad quieres borrarlo: los puntos "
                         f"quedarán sin ese dominio hasta reclasificar.")
    for texto in uso["alias"]:
        alias_registry.pop(_norm_txt(texto), None)
    attribute_exclusions.pop(attr_id, None)
    attr_registry.pop(attr_id, None)
    log_warn(f'Vocabulario: atributo "{attr_id}" eliminado' +
             (f' · {uso["puntos"]} punto(s) quedan sin ese dominio hasta reclasificar'
              if uso["puntos"] else '') +
             (f' · alias arrastrados: {", ".join(uso["alias"])}' if uso["alias"] else ''))
    return uso


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
    folder: str = "Litología"
    # Etiquetado caserón×litología (T2): el caserón se asigna por dropdown en
    # el árbol de capas; lito_alias permite matchear la litología cuando el
    # nombre de la capa DXF no coincide literal con el atributo canónico.
    #
    # (Simplificación) La capa YA NO lleva UCS. La banda de UCS es propiedad
    # del ATRIBUTO y el registro de atributos es su única fuente: tener además
    # un ucs_lab por capa y una banda autocompletada desde un Excel eran tres
    # verdades para el mismo número, y cuál ganaba dependía del orden de carga.
    caseron: Optional[str] = None; lito_alias: Optional[str] = None
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
    # (Paso 2) RQD del sondaje más cercano, PROPAGADO. Los tres campos viajan
    # juntos a propósito: un RQD sin su sondaje de origen y sin la distancia a
    # la que estaba es una etiqueta que se puede confundir con una medición
    # hecha en este mismo punto, y no lo es. Sobre los datos reales la
    # distancia mediana al intervalo de RQD más cercano son 26,1 m.
    rqd_sondaje: Optional[float] = None
    rqd_sondaje_origen: Optional[str] = None
    rqd_sondaje_dist_m: Optional[float] = None
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
    # (C.1) Capa DXF concreta que aportó la litología del punto. El dominio
    # guarda el atributo canónico, que NO basta para la guardia de
    # circularidad: la misma litología puede venir de la malla de tres
    # caserones distintos, y comparar contra la malla que produjo la etiqueta
    # es exactamente lo que hay que rechazar.
    capa_lito: Optional[str] = None

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
    # (Paso 1) Perfiles de DI calculados con VARIANTES de configuración.
    # Viven acá, en el pozo, y no en p.di: el DI de la convención es uno solo
    # y ninguna variante lo pisa.
    di_variantes: Dict[str, np.ndarray] = field(default_factory=dict)
    # Error de coherencia con el que se asignó el collar, en %. None cuando el
    # match fue estricto. Viaja con el pozo para que una posición aproximada
    # nunca se confunda con una exacta.
    asignacion_err_pct: Optional[float] = None
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
# Bandas geomecánicas de laboratorio (T2): registros por caserón×litología.
#   by_pair    : {(caseron_norm, lito_norm): band}
#   by_lito    : {lito_norm: [band, ...]}          (misma litología, varios caserones)
#   by_caseron : {caseron_norm: [band, ...]}       (mismo caserón, varias litologías)
#   records    : lista completa de bandas parseadas
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
# Nombre de la variante de convención. Vive acá arriba, junto a DI_DEFAULTS,
# porque `di_variante_activa` lo necesita antes de que se declare el registro
# de variantes; el registro mismo se siembra más abajo (seed_di_variants).
DI_VARIANTE_CONVENCION = "convencion_Fernandez_2023"
di_config = {"params": ["pp","pr","pd","pf"], "weights": dict(DI_DEFAULTS["weights"]),
            "window": DI_DEFAULTS["window"]}
di_threshold: float = DI_DEFAULTS["threshold"]
# Qué variante del DI está corriendo AHORA. `di_config` y `di_threshold` son su
# reflejo, no una segunda verdad: se escriben solo desde `activar_di()`.
di_variante_activa: str = DI_VARIANTE_CONVENCION


def di_activo() -> str:
    """Nombre de la variante de DI con la que se está calculando."""
    return di_variante_activa


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
    linea = (f"DI «{di_variante_activa}»: ventana={di_config['window']} "
            f"umbral={di_threshold:g} "
            f"pesos(PP={w.get('pp')},DP={w.get('pd')},FP={w.get('pf')},RP={w.get('pr')})")
    linea += (" [convención Fernández et al. 2023]" if di_config_is_default()
              else " [VARIANTE, distinta de Fernández et al. 2023]")
    return linea
group_interval_m: float = 2.0
ucs_range = dict(ucs_min=UCS_CONFIG["default_min"], ucs_max=UCS_CONFIG["default_max"])
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

def match_and_place_wells(dq_results, mw_by_hole,
                          asignar_por_tolerancia: bool = False,
                          tolerancia_err_pct: float = 0.0):
    """
    Matching MW↔DQ con multi-DQ hermanos + colocación espacial.

    Para cada pozo MWD elige el DQ×hole cuyo collar/final CUMPLE la coherencia
    de largo (|largo_max − dist(collar,final)|/largo_max < COHERENCE_TOL),
    probando candidatos en orden: match exacto de plan_id primero, luego DQ
    hermanos ordenados por similitud de prefijo de plan_id.

    UN POZO SIN POSICIÓN NO ES UN POZO. Antes, los que no encontraban DQ
    coherente se colocaban en el centro global, y ahí quedaban los 16 pozos
    apilados sobre la misma vertical que se veían como traslape en la vista 3D.
    Ahora se DESCARTAN y se declaran uno por uno.

    Para el caso intermedio —hay candidatos, pero ninguno dentro de la
    coherencia estricta— existe `asignar_por_tolerancia`: una sola decisión
    tomada al cargar, con su tolerancia, y la asignación se hace tomando el
    candidato de MENOR error entre los que caen dentro de ella.

    COLOCACIÓN: cada punto va a su profundidad REALMENTE medida sobre la
    dirección del tiro, no estirado sobre el largo del tiro por un parámetro
    normalizado. Cuando el MWD deja de registrar antes del fondo —20 pozos de
    los datos reales, hasta 1,65 m sobre tiros de 35 m— estirar desplaza cada
    punto casi un bloque entero.

    Devuelve los contadores, incluida la lista `descartados` con su motivo.
    """
    # Índice por hole_id de todos los DQ (fallback por hole)
    all_holes = {}
    for pid, dq in dq_results.items():
        for hid, tiro in dq["tiros"].items():
            all_holes.setdefault(hid, []).append((pid, tiro))

    counts = {"matched": 0, "fallback": 0, "ambiguous": 0, "no_dq": 0,
              "tolerancia": 0, "descartados_sin_posicion": 0,
              "descartados_sin_registro": 0, "descartados": []}
    largo_min = get_param("carga.largo_min_m")
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

        # ── Registro despreciable: no es un pozo, se descarta antes de nada ──
        pts_previos = best["puntos"]
        if not pts_previos or largo_max < largo_min:
            counts["descartados_sin_registro"] += 1
            counts["descartados"].append({
                "pozo": key, "motivo": (
                    f"Registro de {largo_max:.2f} m, bajo el mínimo de "
                    f"{largo_min:g} m del perfil de faena. Un pozo con este "
                    "registro se dibuja como el collar y una medición suelta, y "
                    "no aporta metraje al modelo.")})
            log_warn(f'MW "{key}": {largo_max:.2f} m de registro, bajo el mínimo '
                     f'de {largo_min:g} m. Descartado.')
            continue

        # ── Elegir el primer candidato que cumpla la coherencia de largo ──
        collar = final_pt = None; origin = "no_dq"
        chosen_pid = None; discarded = []; err_asignacion = None
        for pid_dq, tiro in candidates:
            err = _coherence_err(largo_max, tiro["collar"], tiro["final_pt"])
            if err < COHERENCE_TOL:
                collar, final_pt = tiro["collar"], tiro["final_pt"]
                chosen_pid = pid_dq
                err_asignacion = err * 100.0
                break
            discarded.append((pid_dq, err))

        # ── Ninguno estricto: asignación por tolerancia, de MENOR a mayor error ──
        if chosen_pid is None and candidates and asignar_por_tolerancia:
            dentro = [(p, e) for p, e in discarded if e * 100.0 <= tolerancia_err_pct]
            if dentro:
                mejor_pid, mejor_err = min(dentro, key=lambda x: x[1])
                tiro = next(t for p, t in candidates if p == mejor_pid)
                collar, final_pt = tiro["collar"], tiro["final_pt"]
                origin = "tolerancia"; counts["tolerancia"] += 1
                err_asignacion = mejor_err * 100.0
                log_warn(f'MW "{key}": ningún DQ cumple la coherencia estricta; '
                         f'asignado "{_plan_short(mejor_pid)}" por tolerancia '
                         f'(error {mejor_err*100:.1f}% ≤ {tolerancia_err_pct:g}%). '
                         "La posición es aproximada y queda declarada como tal.")

        if origin == "tolerancia":
            pass
        elif chosen_pid is not None:
            if chosen_pid == pid:
                origin = "matched"; counts["matched"] += 1
            else:
                origin = "fallback_hole"; counts["fallback"] += 1
                log_warn(f'MW "{key}" plan="{pid}" hole={hid}: usado DQ hermano '
                         f'"{chosen_pid}" (coherencia OK).')
        elif candidates:
            # Había candidatos por hole_id pero NINGUNO cumple coherencia ni
            # entra en la tolerancia: sin posición creíble no se carga.
            counts["ambiguous"] += 1
            counts["descartados_sin_posicion"] += 1
            # Solo los mejores candidatos: listar los 55 de un hole_id repetido
            # llena el reporte de ruido y esconde el dato que importa, que es
            # cuán cerca estuvo el mejor de pasar.
            mejores = sorted(discarded, key=lambda x: x[1])[:5]
            det = ", ".join(f'{_plan_short(p)} (err {e*100:.1f}%)' for p, e in mejores)
            if len(discarded) > len(mejores):
                det += f" y {len(discarded) - len(mejores)} más"
            counts["descartados"].append({
                "pozo": key, "motivo": (
                    f"Ningún DQ cumple la coherencia de largo (<{COHERENCE_TOL*100:.0f}%)"
                    + (f" ni la tolerancia de {tolerancia_err_pct:g}%"
                       if asignar_por_tolerancia else "")
                    + f". Candidatos: {det}.")})
            log_warn(f'MW "{key}" plan="{pid}" hole={hid}: sin DQ coherente. '
                     f'Descartados: {det}. Pozo NO cargado.')
            continue
        else:
            counts["no_dq"] += 1
            counts["descartados_sin_posicion"] += 1
            counts["descartados"].append({
                "pozo": key, "motivo": ("Sin ningún DQ que le dé collar. Un pozo "
                                        "sin posición no se puede cruzar contra "
                                        "ninguna malla ni interpolar a bloques.")})
            log_warn(f'MW "{key}": sin DQ. Pozo NO cargado.')
            continue

        pts = best["puntos"]
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
        if global_center is None:
            set_center(collar["norte"], collar["este"], collar["cota"])
        # Cada punto a su profundidad REALMENTE medida sobre la dirección del
        # tiro. Con `t` normalizado, un registro que no llega al fondo se
        # estiraba sobre todo el largo del tiro.
        vx = final_pt["este"] - collar["este"]
        vy = final_pt["norte"] - collar["norte"]
        vz = final_pt["cota"] - collar["cota"]
        L = math.sqrt(vx * vx + vy * vy + vz * vz)
        if L <= 1e-9:
            counts["descartados_sin_posicion"] += 1
            counts["descartados"].append({
                "pozo": key, "motivo": ("El DQ da collar y fondo en el mismo punto: "
                                        "el tiro no tiene dirección.")})
            log_warn(f'MW "{key}": collar y fondo coinciden en el DQ. Pozo NO cargado.')
            continue
        ux, uy, uz = vx / L, vy / L, vz / L
        for p in pts:
            p.este = collar["este"] + p.largo * ux
            p.norte = collar["norte"] + p.largo * uy
            p.cota = collar["cota"] + p.largo * uz
        w = Well(well_name=key, plan_id=pid, hole_id=hid or "",
                 points=pts, collar=collar, final_pt=final_pt, origin=origin,
                 dq_candidates=cand_info)
        w.asignacion_err_pct = (round(err_asignacion, 3)
                                if err_asignacion is not None else None)
        wells[key] = w
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

# ─── EXCEL GEOMECÁNICO caserón×litología (T2) ─────────────────────────────────
# Columnas por índice (fila de encabezados = índice 2, datos desde índice 3):
#   2=Caserón · 3=Nivel · 23=Litología · 24=UCS[MPa] · 25=RMR · 26=RQD · 27=GSI
GEO_HEADER_ROW = 2   # 0-indexado; datos desde GEO_HEADER_ROW+1

def _norm_txt(s):
    """Normaliza texto para matching: minúsculas, sin acentos, sin espacios extra."""
    if s is None: return ""
    s = str(s).strip().lower()
    trans = str.maketrans("áàäâãéèëêíìïîóòöôõúùüûñ", "aaaaaeeeeiiiiooooouuuun")
    return " ".join(s.translate(trans).split())

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
            # (C.1) Qué CAPA aportó cada identidad de litología. El dominio
            # guarda el atributo canónico, que no alcanza para la guardia de
            # circularidad: la misma litología puede venir de tres caserones.
            capa_de: List[Dict[str, str]] = [{} for _ in pts]
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
                            if rol == "litologia":
                                capa_de[i].setdefault(ident, name)
                except Exception as e:
                    log_warn(f'Clasificación "{name}" en "{wn}": {e}')
            for i, p in enumerate(pts):
                overlap_stats["n_puntos"] += 1
                resuelto, motivo, anidado = resolve_overlap_by_role(hits[i])
                if anidado: overlap_stats["n_subunidad_gana"] += 1
                p.ambiguo = False; p.ambiguo_motivo = None; p.capa_lito = None
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
                p.capa_lito = capa_de[i].get(lh) if lh else None
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
    modo_ucs = get_param("ucs.estadistica_ml")
    for p in all_points():
        d = p.dominio or "(sin dominio)"
        if d not in domains:
            domains[d] = {"count": 0, "ucs_lab": None, "atributo_id": None,
                          "alteracion_id": None, "estructura_id": None,
                          "pi_factor": None, "calidad": None, "fuente_ucs": None,
                          "modo_ucs": None}
        domains[d]["count"] += 1
    for d, info in domains.items():
        lito, alt, est = parse_dominio(d)
        info["alteracion_id"] = alt
        info["estructura_id"] = est
        if not lito: continue
        attr = attr_registry.get(lito)
        if attr is not None and attr.rol != "litologia": attr = None
        # UNA sola fuente de UCS: el registro de atributos. El campo manual
        # por capa y las bandas del Excel geomecánico eran dos verdades más
        # para el mismo número, y cuál ganaba dependía del orden de carga.
        ucs = attr.ucs_ancla(modo=modo_ucs) if attr else None
        info["modo_ucs"] = modo_ucs
        if ucs is not None:
            info["ucs_lab"] = ucs
            info["fuente_ucs"] = attr.fuente if attr else None
        if attr is not None:
            info["atributo_id"] = attr.id
            info["pi_factor"] = attr.pi_factor()
            info["calidad"] = attr.calidad

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

# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  PASO 1 — VARIANTES DEL DI, SIN TOCAR LA CONVENCIÓN                     ║
# ║                                                                          ║
# ║  CLAUDE.md fija el DI de Fernández et al. 2023 como convención           ║
# ║  inmutable: ventana 14, pesos PP 0,35 · DP 0,25 · FP 0,20 · RP 0,20,     ║
# ║  umbral 1,5. Calibrar esos pesos contra el RQD de los sondajes es lo     ║
# ║  que hace falta, y sobrescribirlos sería violar la convención.           ║
# ║                                                                          ║
# ║  La salida: el DI de la convención queda INTOCADO y se registran         ║
# ║  VARIANTES con nombre propio, cada una con sus pesos, su ventana y su    ║
# ║  umbral. Conviven y se comparan. La de convención no se puede editar ni  ║
# ║  borrar, y `p.di` sigue siendo siempre la suya: las variantes viven en   ║
# ║  el pozo, en `well.di_variantes`.                                        ║
# ║                                                                          ║
# ║  Esto es además lo que vuelve la plataforma transferible: otra faena     ║
# ║  calibra su propia variante sin tocar la referencia publicada.           ║
# ╚══════════════════════════════════════════════════════════════════════════╝

# DI_VARIANTE_CONVENCION se declara junto a DI_DEFAULTS, más arriba.
di_variantes: Dict[str, Dict] = {}


class DIVarianteProtegida(Exception):
    """Se intentó editar o borrar la variante de convención. Es un error."""


def seed_di_variants(force: bool = False):
    """Siembra la variante de convención. Idempotente salvo `force`."""
    if di_variantes and not force:
        return
    di_variantes.clear()
    di_variantes[DI_VARIANTE_CONVENCION] = {
        "nombre": DI_VARIANTE_CONVENCION,
        "window": DI_DEFAULTS["window"],
        "params": list(di_config["params"]),
        "weights": dict(DI_DEFAULTS["weights"]),
        "threshold": DI_DEFAULTS["threshold"],
        "fuente": ("Fernández et al. 2023, doi:10.1016/j.ijmst.2023.02.004. "
                   "Convención del proyecto: el autor del artículo es el "
                   "profesor guía de la memoria."),
        "notas": ("Referencia intocable. Cualquier calibración vive en una "
                  "variante aparte para que la comparación siga siendo posible."),
        "solo_lectura": True,
    }
    # Sembrar el registro sin reponer el DI vigente dejaría corriendo una
    # variante que ya no existe: el mismo defecto, por otra puerta.
    activar_di(DI_VARIANTE_CONVENCION)


def di_variant(nombre: str) -> Optional[Dict]:
    return di_variantes.get(nombre)


def activar_di(nombre: str) -> Dict:
    """
    Pone a correr una variante: `di_config` y `di_threshold` pasan a ser SU
    reflejo, y `di_activo()` la nombra.

    Es el único camino por el que se escribe la configuración vigente del DI.
    El panel escribía directo sobre `di_config` y `di_threshold`, que son la
    convención de Fernández: el DI corría con otros pesos mientras el parámetro
    protegido del perfil y la variante de solo lectura seguían declarando los
    originales. Dos fuentes de verdad mintiendo a la vez, y todo reporte
    citando a Fernández con pesos que no eran los suyos.
    """
    global di_threshold, di_variante_activa
    v = di_variantes.get(nombre)
    if v is None:
        raise KeyError(f'No existe una variante de DI llamada "{nombre}". '
                       f"Registradas: {sorted(di_variantes)}.")
    di_config["window"] = int(v["window"])
    di_config["params"] = list(v["params"])
    di_config["weights"] = dict(v["weights"])
    di_threshold = float(v["threshold"])
    di_variante_activa = nombre
    return v


def _misma_config_di(v: Dict, window: int, threshold: float,
                     weights: Dict[str, float]) -> bool:
    if int(v["window"]) != int(window) or abs(float(v["threshold"]) - float(threshold)) > 1e-12:
        return False
    # Se comparan las presiones que PARTICIPAN: un peso 0 escrito y una clave
    # ausente son la misma configuración de DI.
    a = {k: float(x) for k, x in v["weights"].items() if float(x) > 0}
    b = {k: float(x) for k, x in weights.items() if float(x) > 0}
    if set(a) != set(b):
        return False
    return all(abs(a[k] - b[k]) <= 1e-9 for k in b)


def aplicar_di_config(window: int, threshold: float, weights: Dict[str, float],
                      nombre: str = "", fuente: str = "", notas: str = "") -> str:
    """
    Lo que hace el panel del DI cuando el usuario cambia parámetros: NO pisa la
    convención, sino que resuelve a qué variante corresponde esa configuración
    y la activa. Devuelve el nombre de la variante que quedó corriendo.

    · Si los valores coinciden con los de Fernández, vuelve a la convención.
    · Si coinciden con una variante ya registrada, activa esa en vez de
      fabricar una copia con otro nombre.
    · Si no, crea una variante nueva y la activa.
    """
    w, params = _normalizar_pesos(weights)
    win = int(window)
    if win < 3:
        raise ValueError(f"La ventana del DI tiene que ser 3 o más; se recibió {win}.")
    thr = float(threshold)
    if thr <= 0:
        raise ValueError(f"El umbral del DI tiene que ser positivo; se recibió {thr}.")
    for nom, v in di_variantes.items():
        if _misma_config_di(v, win, thr, w):
            activar_di(nom)
            return nom
    if nombre and str(nombre).strip():
        destino = str(nombre).strip()
    else:
        k = 1
        while f"panel_{k}" in di_variantes:
            k += 1
        destino = f"panel_{k}"
    create_di_variant(destino, weights=w, window=win, threshold=thr,
                      fuente=fuente or "Ajustada a mano en el panel del DI.",
                      notas=notas or ("Creada porque los valores del panel no son "
                                      "los de la convención. La convención queda "
                                      "intacta para poder comparar contra ella."))
    activar_di(destino)
    return destino


def _normalizar_pesos(weights: Dict[str, float]) -> Tuple[Dict[str, float], List[str]]:
    """
    Pesos a suma 1. Los PARÁMETROS son las claves con peso > 0; un peso 0
    explícito se conserva en `weights` como 0,0 en vez de desaparecer: pedir
    que una presión no participe es una decisión, y tiene que quedar escrita
    como tal y no como un campo ausente que nadie sabe si se olvidó.
    """
    todos = {k: float(v) for k, v in (weights or {}).items()}
    if any(v < 0 for v in todos.values()):
        raise ValueError("Ningún peso del DI puede ser negativo: "
                         f"se recibió {weights!r}.")
    activos = {k: v for k, v in todos.items() if v > 0}
    total = sum(activos.values())
    if not activos or total <= 0:
        raise ValueError("Los pesos del DI tienen que sumar más que cero: "
                         f"se recibió {weights!r}.")
    # Si ya suman 1, no se dividen: reescalar por 1,0000000000000002 mete ruido
    # de coma flotante en pesos que están documentados con dos decimales.
    if abs(total - 1.0) > 1e-12:
        todos = {k: (v / total if v > 0 else 0.0) for k, v in todos.items()}
    return todos, sorted(activos)


def create_di_variant(nombre: str, weights: Dict[str, float],
                      window: int = None, threshold: float = None,
                      fuente: str = "", notas: str = "") -> Dict:
    """
    Registra una variante del DI. Valida ANTES de tocar el registro: una
    variante a medias produce perfiles que nadie puede reproducir.
    """
    if not nombre or not str(nombre).strip():
        raise ValueError("La variante necesita un nombre.")
    nombre = str(nombre).strip()
    if nombre in di_variantes:
        raise ValueError(f'Ya existe una variante de DI llamada "{nombre}".')
    w, params = _normalizar_pesos(weights)
    win = int(window if window is not None else DI_DEFAULTS["window"])
    if win < 3:
        raise ValueError(f"La ventana del DI tiene que ser 3 o más; se recibió {win}.")
    thr = float(threshold if threshold is not None else DI_DEFAULTS["threshold"])
    if thr <= 0:
        raise ValueError(f"El umbral del DI tiene que ser positivo; se recibió {thr}.")
    di_variantes[nombre] = {"nombre": nombre, "window": win, "params": params,
                            "weights": w, "threshold": thr, "fuente": fuente,
                            "notas": notas, "solo_lectura": False}
    return di_variantes[nombre]


def _variante_editable(nombre: str) -> Dict:
    v = di_variantes.get(nombre)
    if v is None:
        raise KeyError(f'No existe una variante de DI llamada "{nombre}".')
    if v.get("solo_lectura"):
        raise DIVarianteProtegida(
            f'"{nombre}" es la variante de CONVENCIÓN y no se puede modificar ni '
            "borrar. Crear una variante nueva es la forma de calibrar sin perder "
            "la referencia con la que se comparan todos los resultados.")
    return v


def update_di_variant(nombre: str, **campos) -> Dict:
    v = _variante_editable(nombre)
    if "weights" in campos:
        v["weights"], v["params"] = _normalizar_pesos(campos.pop("weights"))
    if "window" in campos:
        win = int(campos.pop("window"))
        if win < 3:
            raise ValueError(f"La ventana del DI tiene que ser 3 o más; se recibió {win}.")
        v["window"] = win
    if "threshold" in campos:
        thr = float(campos.pop("threshold"))
        if thr <= 0:
            raise ValueError(f"El umbral del DI tiene que ser positivo; se recibió {thr}.")
        v["threshold"] = thr
    for k in ("fuente", "notas"):
        if k in campos:
            v[k] = campos.pop(k)
    if campos:
        raise ValueError(f"Campos desconocidos para una variante de DI: {sorted(campos)}")
    # El perfil guardado ya no corresponde a estos parámetros: se invalida en
    # vez de quedar como un valor viejo que nadie sabe de dónde salió.
    for w in wells.values():
        w.di_variantes.pop(nombre, None)
    # Si es la que está corriendo, el reflejo vigente quedó viejo.
    if di_variante_activa == nombre:
        activar_di(nombre)
    return v


def delete_di_variant(nombre: str) -> None:
    _variante_editable(nombre)
    di_variantes.pop(nombre, None)
    for w in wells.values():
        w.di_variantes.pop(nombre, None)
    # Borrar la variante que está corriendo dejaría el DI apuntando a algo que
    # ya no existe. Se vuelve a la convención, que es el único destino que
    # siempre está disponible.
    if di_variante_activa == nombre:
        activar_di(DI_VARIANTE_CONVENCION)


def compute_di_variant(nombre: str) -> Dict:
    """
    Calcula el perfil de la variante en todos los pozos y lo guarda en
    `well.di_variantes[nombre]`. NO toca `p.di`.
    """
    v = di_variantes.get(nombre)
    if v is None:
        raise KeyError(f'No existe una variante de DI llamada "{nombre}".')
    n_ok, cortos = 0, []
    for wn, well in wells.items():
        if len(well.points) < v["window"]:
            cortos.append(wn); continue
        perfil = di_profile(well.points, v["window"], v["params"], v["weights"])
        if perfil is None:
            cortos.append(wn); continue
        well.di_variantes[nombre] = perfil
        n_ok += 1
    return {"variante": nombre, "n_pozos": n_ok, "pozos_cortos": cortos,
            "config": {k: v[k] for k in ("window", "params", "weights", "threshold")}}


def di_variant_values(well, nombre: str) -> Optional[np.ndarray]:
    """Perfil de la variante en un pozo, o None si no se calculó para ese pozo."""
    if nombre not in di_variantes:
        raise KeyError(f'No existe una variante de DI llamada "{nombre}".')
    return well.di_variantes.get(nombre)



# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  PERFIL DE FAENA — LOS PARÁMETROS SE CONFIGURAN, NO SE ENTIERRAN        ║
# ║                                                                          ║
# ║  Pucobre tiene tres faenas con litología distinta, y el burden, la       ║
# ║  desviación de perforación, el rango operacional de PP y hasta los       ║
# ║  límites físicos de UCS cambian de una a otra. Para que la plataforma    ║
# ║  sea replicable, esas decisiones tienen que poder cambiarse DESDE EL     ║
# ║  PROGRAMA. Un número fijo en el código es un número que obliga a tocar   ║
# ║  el código para llevar esto a otra mina.                                 ║
# ║                                                                          ║
# ║  Cada parámetro declara valor, defecto, límites, unidades y PROCEDENCIA. ║
# ║  Un número sin procedencia no se puede defender en una revisión.         ║
# ║                                                                          ║
# ║  Los PROTEGIDOS son los que CLAUDE.md fija como convención inmutable:    ║
# ║  se leen y se exportan, nunca se escriben. Misma regla que protege la    ║
# ║  variante de convención del DI.                                          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

param_registry: Dict[str, Dict] = {}


class ParametroProtegido(Exception):
    """Se intentó escribir un parámetro de convención. Es un error."""


def _param(pid, seccion, etiqueta, defecto, tipo, unidad, procedencia,
           minimo=None, maximo=None, global_name=None, protegido=False,
           descripcion="", opciones=None):
    return {"id": pid, "seccion": seccion, "etiqueta": etiqueta,
            "valor": defecto, "defecto": defecto, "tipo": tipo, "unidad": unidad,
            "min": minimo, "max": maximo, "procedencia": procedencia,
            "global": global_name, "protegido": protegido,
            "descripcion": descripcion, "opciones": opciones}


def seed_param_registry(force: bool = False):
    """Siembra el perfil con los valores de Punta del Cobre. Idempotente."""
    if param_registry and not force:
        return
    param_registry.clear()
    P = [
        _param("repo.ruta", "Repositorio", "Carpeta-repositorio de la faena",
               "", "texto", "ruta",
               "Carpeta del computador desde la que se cargan DXF, XML y CSV "
               "de sondaje sin subirlos uno por uno. El caserón se deduce de "
               "la carpeta que contiene cada archivo."),
        _param("repo.patron_caseron", "Repositorio",
               "Patrón que identifica un caserón en la ruta",
               r"PC[SC]_\d{3,4}", "texto", "regex",
               "Expresión regular buscada en la ruta completa del archivo, "
               "incluido su nombre. En MPC los caserones son PCS_1043, "
               "PCC_0042, PCC_1541… y el patrón tiene que ser específico: uno "
               "genérico como [A-Za-z]{2,4}_\\d{3,4} se traga el prefijo del "
               "archivo y devuelve QPCC_1502 en vez de PCC_1502. Otra faena "
               "con otra nomenclatura cambia el patrón acá, sin tocar código."),
        _param("repo.ruta_proyecto", "Repositorio",
               "Dónde guardar el proyecto (.gwz)", "", "texto", "ruta",
               "Guardar a disco esquiva la descarga del navegador, que falla "
               "sin avisar con proyectos de decenas de MB."),
        # ── Carga de pozos ───────────────────────────────────────────────────
        _param("carga.largo_min_m", "Carga de pozos",
               "Registro mínimo para cargar un pozo", 1.0, "float", "m",
               "Bajo esto el pozo se dibuja como el collar y una medición "
               "suelta y no aporta metraje. Medido en MPC: cuatro pozos con "
               "menos de 1,5 m, uno con 3 muestras y 7 cm.",
               0.0, 100.0),
        _param("carga.asignar_por_tolerancia", "Carga de pozos",
               "Asignar collar aproximado cuando no hay match exacto", 0, "int",
               "0/1", "Decisión que se toma UNA vez al cargar. Con 1, los pozos "
               "sin DQ coherente reciben el candidato de menor error que caiga "
               "dentro de la tolerancia; con 0 se descartan.", 0, 1),
        _param("carga.tolerancia_err_pct", "Carga de pozos",
               "Tolerancia de error para el collar aproximado", 15.0, "float",
               "%", "Error de coherencia de largo máximo admitido al asignar un "
               "collar aproximado. La asignación va de menor a mayor error.",
               0.0, 100.0),
        # ── Modelo de bloques ────────────────────────────────────────────────
        _param("bloques.tamano_m", "Modelo de bloques", "Tamaño de bloque", 2.5,
               "float", "m", "Burden y espaciamiento de la operación en MPC. "
               "Un bloque más fino que la malla de perforación promete un "
               "detalle que el dato no tiene.", 0.5, 25.0, "BLOQUE_M"),
        _param("bloques.holgura_m", "Modelo de bloques",
               "Holgura sobre el espacio perforado", 15.0, "float", "m",
               "Rango 10-20 m fijado por el autor: extiende el dominio lo justo "
               "para servir de soporte a dilución, estabilidad y fortificación.",
               0.0, 100.0, "HOLGURA_MODELO_M"),
        _param("bloques.radio_h_m", "Modelo de bloques",
               "Radio de búsqueda en planta", 7.5, "float", "m",
               "Tres bloques. Sube la cobertura a costa de extrapolar más lejos.",
               1.0, 100.0, "IDW_RADIO_H_M"),
        _param("bloques.radio_v_m", "Modelo de bloques",
               "Radio de búsqueda en cota", 2.5, "float", "m",
               "Un bloque. Menor que el horizontal porque el yacimiento es "
               "estratiforme.", 0.5, 100.0, "IDW_RADIO_V_M"),
        _param("bloques.anisotropia_z", "Modelo de bloques",
               "Penalización de la separación vertical", 3.0, "float", "×",
               "Un metro de separación en cota cuenta como tres en planta. La "
               "asimetría ES el modelo geológico: estratiforme.", 1.0, 20.0),
        _param("bloques.potencia_idw", "Modelo de bloques", "Potencia del IDW",
               2.0, "float", "—", "Inverso de la distancia al cuadrado, uso "
               "estándar en interpolación de leyes.", 0.5, 6.0, "IDW_POTENCIA"),
        _param("bloques.min_muestras", "Modelo de bloques",
               "Muestras mínimas por bloque", 3, "int", "registros",
               "Máscara de soporte: bajo esto el bloque queda VACÍO en vez de "
               "interpolarse desde lejos.", 1, 100, "IDW_MIN_MUESTRAS"),
        # ── Plano del abanico ────────────────────────────────────────────────
        _param("abanico.eps_m", "Plano del abanico", "Radio de agrupamiento de picos",
               2.5, "float", "m", "El burden de la operación: dos picos más "
               "cerca que esto son candidatos a la misma superficie.",
               0.5, 25.0, "ABANICO_EPS_M"),
        _param("abanico.min_picos", "Plano del abanico", "Picos mínimos por grupo",
               3, "int", "picos", "Bajo tres picos no hay plano que ajustar.",
               3, 100, "ABANICO_MIN_PICOS"),
        _param("abanico.planaridad_tiros", "Plano del abanico",
               "Planaridad máxima de los tiros", 0.15, "float", "—",
               "Razón entre el tercer y el segundo valor singular del ajuste a "
               "los trazados: bajo esto, los tiros forman un plano.",
               0.01, 1.0, "ABANICO_PLANARIDAD_TIROS"),
        _param("abanico.ang_max_grad", "Plano del abanico",
               "Ángulo máximo con el plano del abanico", 20.0, "float", "°",
               "Criterio secundario: solo aplica cuando el grupo de picos es lo "
               "bastante planar para tener normal utilizable.",
               0.0, 90.0, "ABANICO_ANG_MAX_GRAD"),
        _param("abanico.tol_plano_m", "Plano del abanico",
               "Piso de tolerancia al plano", 0.75, "float", "m",
               "Piso absoluto. La tolerancia efectiva es la mayor entre este "
               "piso y el espesor MEDIDO del abanico.",
               0.0, 20.0, "ABANICO_TOL_PLANO_M"),
        _param("abanico.factor_dispersion", "Plano del abanico",
               "Factor sobre el espesor del abanico", 1.0, "float", "×",
               "Auto-calibración: con otra desviación de perforación el criterio "
               "se adapta solo, sin necesitar un número nuevo.",
               0.0, 5.0, "ABANICO_FACTOR_DISPERSION"),
        # ── Discriminador ────────────────────────────────────────────────────
        _param("disc.ventana_m", "Discriminador", "Media ventana del evento",
               0.30, "float", "m", "Tramo alrededor del pico donde se mide la "
               "firma. 0,30 m son ~15 registros al paso de 2 cm del MWD real.",
               0.05, 5.0, "DISC_VENTANA_M"),
        _param("disc.base_m", "Discriminador", "Tramo de referencia previo",
               1.00, "float", "m", "Roca inmediatamente anterior al evento. No "
               "es un promedio del pozo: la roca cambia a lo largo del tiro y "
               "una referencia global diluiría la firma.",
               0.1, 20.0, "DISC_BASE_M"),
        _param("disc.caida_rel", "Discriminador", "Caída que cuenta como «cae»",
               0.10, "float", "fracción", "Mismo umbral que decide que el "
               "dámper NO cae, que es lo que separa las dos firmas.",
               0.01, 0.9, "DISC_CAIDA_REL"),
        _param("disc.subida_vel_rel", "Discriminador",
               "Subida de velocidad que cuenta como «aumenta»", 0.10, "float",
               "fracción", "Firma de zona fracturada: la broca entra en vacío y "
               "el avance se dispara.", 0.01, 0.9, "DISC_SUBIDA_VEL_REL"),
        _param("disc.var_factor", "Discriminador", "Factor de varianza no esperada",
               1.5, "float", "×", "El coeficiente de variación dentro del evento "
               "supera este factor por el de la referencia.",
               1.0, 10.0, "DISC_VAR_FACTOR"),
        _param("disc.radio_etiqueta_m", "Discriminador",
               "Radio de apareo pico-sondaje", 3.0, "float", "m",
               "Los sondajes de exploración y los tiros de producción son "
               "perforaciones distintas; más allá de este radio la "
               "correspondencia deja de ser creíble.",
               0.5, 100.0, "DISC_RADIO_ETIQUETA_M"),
        # ── RQD ──────────────────────────────────────────────────────────────
        _param("rqd.tramo_min_m", "RQD", "Tramo mínimo de Deere", 0.10, "float",
               "m", "Definición de Deere: tramos continuos de 10 cm o más sin "
               "discontinuidad. Es la definición, no una elección; cambiarla "
               "deja de ser RQD.", 0.01, 1.0, "RQD_TRAMO_MIN_M"),
        _param("rqd.radio_max_m", "RQD", "Radio de propagación del RQD",
               10.0, "float", "m", "Sobre los datos de MPC la distancia mediana "
               "de un punto MWD al intervalo de RQD más cercano son 26,1 m: el "
               "radio decide cuánto dato recibe etiqueta y con qué credibilidad.",
               1.0, 200.0, "RQD_RADIO_MAX_M"),
        _param("rqd.min_puntos_intervalo", "RQD",
               "Puntos MWD mínimos por intervalo", 30, "int", "registros",
               "Bajo esto el RQD_MWD de un intervalo es ruido de unos pocos "
               "registros.", 2, 10000, "RQD_MIN_PUNTOS_INTERVALO"),
        # ── Presión de percusión ─────────────────────────────────────────────
        _param("pp.min_bar", "Presión de percusión", "PP mínima operacional",
               90.0, "float", "bar", "Rango operacional declarado en CLAUDE.md "
               "para MPC. PP es la ÚNICA variable que manipula el operador.",
               0.0, 500.0, "PP_MIN_OPERACIONAL"),
        _param("pp.max_bar", "Presión de percusión", "PP máxima operacional",
               230.0, "float", "bar", "Rango operacional declarado en CLAUDE.md "
               "para MPC.", 0.0, 500.0, "PP_MAX_OPERACIONAL"),
        _param("pp.paso_bar", "Presión de percusión", "Paso de los bins de PP",
               10.0, "float", "bar", "Resolución de las curvas de respuesta.",
               1.0, 50.0, "PP_PASO_BAR"),
        _param("pp.min_puntos_bin", "Presión de percusión",
               "Puntos mínimos por bin", 20, "int", "registros",
               "Bajo esto la mediana del bin no significa nada.",
               2, 10000, "PP_MIN_PUNTOS_BIN"),
        # ── Límites físicos ──────────────────────────────────────────────────
        _param("rop.min_fisica", "Límites físicos", "ROP mínima con sentido físico",
               0.05, "float", "m/min", "Bajo esto la energía específica no tiene "
               "significado físico: SE = (PP+RP+AP)/ROP se dispara. Criterio "
               "físico y trazable, NO un percentil.",
               0.001, 1.0, "ROP_MIN_FISICA"),
        _param("ucs.estadistica_ml", "Etiqueta de UCS",
               "Estadística que alimenta el modelo", "auto", "opcion", "—",
               "Una banda de UCS es una estadística, no un número: cuál se usa "
               "como etiqueta es una decisión de la faena. 'auto' es la cadena "
               "histórica —central, si no media, si no el punto medio del "
               "rango— y es el defecto porque los modos estrictos dejan sin "
               "etiqueta a los atributos que no documentan esa estadística, y "
               "esos puntos saldrían del entrenamiento sin que nada lo delate. "
               "NINGUNA opción construye la etiqueta desde SE: SE es una "
               "PREDICTORA y describe la roca —una caída de SE hace esperar "
               "menos resistencia o más discontinuidades—, así que derivar la "
               "etiqueta de ella haría que el modelo aprendiera esa aritmética "
               "en vez de la roca, y obligaría a sacar SE de las predictoras. "
               "Las dos cosas son inaceptables.",
               opciones=["auto", "central", "media", "mediana", "rango_medio"]),
        _param("ucs.min_fisico", "Límites físicos", "UCS mínima", 0.0, "float",
               "MPa", "Límite físico declarado en CLAUDE.md. Sin truncamiento "
               "silencioso jamás.", 0.0, 1000.0),
        _param("ucs.max_fisico", "Límites físicos", "UCS máxima", 450.0, "float",
               "MPa", "Límite físico declarado en CLAUDE.md.", 0.0, 1000.0),
        # ── Convención inmutable ─────────────────────────────────────────────
        _param("di.ventana", "DI (convención)", "Ventana del DI", 14, "int",
               "registros", "CLAUDE.md, convención inmutable: Fernández et al. "
               "2023, doi:10.1016/j.ijmst.2023.02.004. Para calibrar se crea "
               "una VARIANTE con nombre propio; la convención no se toca.",
               protegido=True),
        _param("di.umbral", "DI (convención)", "Umbral del DI", 1.5, "float", "—",
               "CLAUDE.md, convención inmutable. Fernández et al. 2023.",
               protegido=True),
        _param("di.peso_pp", "DI (convención)", "Peso de PP", 0.35, "float", "—",
               "CLAUDE.md, convención inmutable. Fernández et al. 2023.",
               protegido=True),
        _param("di.peso_dp", "DI (convención)", "Peso de DP", 0.25, "float", "—",
               "CLAUDE.md, convención inmutable. Fernández et al. 2023.",
               protegido=True),
        _param("di.peso_fp", "DI (convención)", "Peso de FP", 0.20, "float", "—",
               "CLAUDE.md, convención inmutable. Fernández et al. 2023.",
               protegido=True),
        _param("di.peso_rp", "DI (convención)", "Peso de RP", 0.20, "float", "—",
               "CLAUDE.md, convención inmutable. Fernández et al. 2023.",
               protegido=True),
    ]
    for p in P:
        param_registry[p["id"]] = p
    # Sembrar el registro sin reponer los globales dejaría el módulo con los
    # valores de la sesión anterior y el registro diciendo otra cosa: dos
    # verdades distintas para el mismo parámetro.
    for p in param_registry.values():
        if p.get("global"):
            globals()[p["global"]] = p["valor"]
    _sincronizar_globales_derivados()


def get_param(pid: str):
    p = param_registry.get(pid)
    if p is None:
        raise KeyError(f'No existe el parámetro de perfil "{pid}".')
    return p["valor"]


def _validar_param(p: Dict, valor):
    if p["tipo"] == "texto":
        if not isinstance(valor, str):
            raise TypeError(f'"{p["id"]}" es texto; se recibió {valor!r}.')
        return valor
    if p["tipo"] == "opcion":
        if valor not in (p.get("opciones") or []):
            raise ValueError(f'"{p["id"]}" admite {p.get("opciones")}; '
                             f"se recibió {valor!r}.")
        return valor
    if p["tipo"] == "int":
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            raise TypeError(f'"{p["id"]}" es entero; se recibió {valor!r}.')
        if float(valor) != int(valor):
            raise ValueError(f'"{p["id"]}" es entero; se recibió {valor!r}.')
        valor = int(valor)
    elif p["tipo"] == "float":
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            raise TypeError(f'"{p["id"]}" es numérico; se recibió {valor!r}.')
        valor = float(valor)
    if p["min"] is not None and valor < p["min"]:
        raise ValueError(f'"{p["id"]}" no puede bajar de {p["min"]} {p["unidad"]}; '
                         f"se recibió {valor}.")
    if p["max"] is not None and valor > p["max"]:
        raise ValueError(f'"{p["id"]}" no puede superar {p["max"]} {p["unidad"]}; '
                         f"se recibió {valor}.")
    return valor


def set_param(pid: str, valor):
    """
    Escribe un parámetro del perfil. Valida ANTES de tocar nada: un parámetro
    a medias produce resultados que nadie puede reproducir.
    """
    p = param_registry.get(pid)
    if p is None:
        raise KeyError(f'No existe el parámetro de perfil "{pid}".')
    if p.get("protegido"):
        raise ParametroProtegido(
            f'"{pid}" es parte de la convención inmutable del proyecto y no se '
            f"puede escribir. Procedencia: {p['procedencia']}")
    valor = _validar_param(p, valor)
    p["valor"] = valor
    # El valor tiene que llegar al módulo, no quedarse en el registro: las
    # funciones que lo leen en su cuerpo lo toman de ahí.
    if p.get("global"):
        globals()[p["global"]] = valor
    _sincronizar_globales_derivados()
    return valor


def reset_param(pid: str):
    p = param_registry.get(pid)
    if p is None:
        raise KeyError(f'No existe el parámetro de perfil "{pid}".')
    if p.get("protegido"):
        raise ParametroProtegido(f'"{pid}" es de convención: no hay nada que reponer.')
    p["valor"] = p["defecto"]
    if p.get("global"):
        globals()[p["global"]] = p["defecto"]
    _sincronizar_globales_derivados()
    return p["valor"]


def _sincronizar_globales_derivados():
    """Globales que no son un parámetro suelto sino una combinación de varios."""
    global IDW_ANISOTROPIA, UCS_CONFIG, PP_ESTRATOS
    IDW_ANISOTROPIA = (1.0, 1.0, float(param_registry["bloques.anisotropia_z"]["valor"]))
    UCS_CONFIG["physical_min"] = float(param_registry["ucs.min_fisico"]["valor"])
    UCS_CONFIG["physical_max"] = float(param_registry["ucs.max_fisico"]["valor"])


def export_site_profile() -> str:
    """Perfil como JSON: lo que una faena nueva recibe para arrancar."""
    return json.dumps({
        "sitio": ACTIVE_SITE,
        "app_version": APP_VERSION,
        "generado": time.strftime("%Y-%m-%d %H:%M"),
        "nota": ("Perfil de faena. Los parámetros protegidos se exportan como "
                 "referencia pero no se pueden importar: son la convención "
                 "inmutable del proyecto."),
        "parametros": {pid: p["valor"] for pid, p in param_registry.items()},
        "procedencias": {pid: p["procedencia"] for pid, p in param_registry.items()},
    }, ensure_ascii=False, indent=1)


def import_site_profile(texto: str) -> Dict:
    """
    Aplica un perfil. Lo que no se puede aplicar NO detiene la importación:
    se aplica el resto y se declara uno por uno lo rechazado, con su motivo.
    Un perfil que falla entero por un valor malo obliga a editar JSON a mano.
    """
    try:
        d = json.loads(texto) if isinstance(texto, str) else texto
    except Exception as e:
        return {"status": "error", "motivo": f"JSON ilegible: {e}",
                "n_aplicados": 0, "rechazados": []}
    params = (d or {}).get("parametros")
    if not isinstance(params, dict):
        return {"status": "error",
                "motivo": "El perfil no trae un objeto 'parametros'.",
                "n_aplicados": 0, "rechazados": []}
    aplicados, rechazados = [], []
    for pid, valor in params.items():
        try:
            set_param(pid, valor)
            aplicados.append(pid)
        except ParametroProtegido:
            rechazados.append({"id": pid, "valor": valor,
                               "motivo": "Parámetro de convención: no se importa."})
        except Exception as e:
            rechazados.append({"id": pid, "valor": valor, "motivo": str(e)})
    return {"status": "ok", "n_aplicados": len(aplicados), "aplicados": aplicados,
            "rechazados": rechazados,
            "sitio_del_perfil": (d or {}).get("sitio"),
            "advertencia": (f"{len(rechazados)} parámetro(s) no se aplicaron y se "
                            "listan con su motivo." if rechazados else None)}


def site_profile_report() -> Dict:
    """Qué se movió respecto del defecto, para la interfaz y para el anexo."""
    mod = [{"id": p["id"], "seccion": p["seccion"], "etiqueta": p["etiqueta"],
            "defecto": p["defecto"], "valor": p["valor"], "unidad": p["unidad"],
            "procedencia": p["procedencia"]}
           for p in param_registry.values()
           if p["valor"] != p["defecto"]]
    secciones: Dict[str, list] = {}
    for p in param_registry.values():
        secciones.setdefault(p["seccion"], []).append(p["id"])
    return {"sitio": ACTIVE_SITE, "n_parametros": len(param_registry),
            "n_modificados": len(mod), "modificados": mod,
            "secciones": {k: sorted(v) for k, v in sorted(secciones.items())},
            "n_protegidos": sum(1 for p in param_registry.values() if p.get("protegido")),
            "nota": ("Los parámetros protegidos son la convención inmutable del "
                     "proyecto: se leen y exportan, nunca se escriben.")}


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

def di_peaks(well, min_gap_m=0.5, variante: Optional[str] = None):
    """
    (T4b) Profundidades de picos con DI > umbral. Picos separados menos de
    min_gap_m se fusionan en un solo evento (se toma el largo del máximo DI
    del grupo). Se ignoran los puntos con entrenable=False (excluye el
    emboquillado con el corte ya existente). Devuelve
    [(largo_pico, coord_utm(3,), di_max), ...].

    (Paso 1) `variante` pide los picos de una VARIANTE del DI en vez de los de
    la convención. Si la variante existe pero no se calculó en este pozo, la
    respuesta es vacía —no se cae a la convención en silencio, que sería
    devolver los picos de otra configuración sin decirlo—.
    """
    if variante is not None:
        v = di_variantes.get(variante)
        if v is None:
            raise KeyError(f'No existe una variante de DI llamada "{variante}".')
        perfil = well.di_variantes.get(variante)
        if perfil is None:
            return []
        umbral = v["threshold"]
        cand = [(p.largo, np.array([p.este, p.norte, p.cota], dtype=np.float64),
                 float(perfil[i]))
                for i, p in enumerate(well.points)
                if p.entrenable and i < len(perfil) and np.isfinite(perfil[i])
                and perfil[i] > umbral]
    else:
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
    "total", "entrenable", "caseron_entrena", "con_dominio", "sin_ambiguedad",
    "banda_ucs", "no_excluido", "rango_ucs", "roca_intacta",
]

# Caserones que ENTRENAN. None = todos los cargados. La asignación
# entrena/prueba es un parámetro de ejecución, no una constante del proyecto:
# se necesita para dejar un caserón como holdout limpio (1541 en el plan) y
# para que la guardia de circularidad (C.1) pueda admitir la comparación
# contra la malla de un caserón que el modelo nunca vio.
training_caserones: Optional[set] = None


def set_training_caserones(caserones=None):
    """
    Fija qué caserones entrenan. `None` (o vacío) restaura "todos".
    Devuelve el conjunto vigente y lo declara: cambiar el reparto
    entrena/prueba cambia todas las métricas aguas abajo.
    """
    global training_caserones
    training_caserones = set(caserones) if caserones else None
    disponibles = {c for c in (caseron_de_pozo(w) for w in wells.values()) if c}
    if training_caserones:
        desconocidos = training_caserones - disponibles
        if desconocidos:
            log_warn(f"Entrenamiento: caserón(es) {', '.join(sorted(desconocidos))} "
                     f"no están entre los cargados ({', '.join(sorted(disponibles)) or '—'}).")
        log_warn(f"Entrenamiento restringido a: {', '.join(sorted(training_caserones))}. "
                 f"Quedan fuera: {', '.join(sorted(disponibles - training_caserones)) or '—'}.")
    else:
        log_warn(f"Entrenamiento con TODOS los caserones cargados "
                 f"({', '.join(sorted(disponibles)) or '—'}).")
    return training_caserones

def _training_funnel(ucs_min, ucs_max):
    """
    Devuelve (X, y, groups, n_excl_di, funnel). `funnel` es una lista de
    {"etapa","label","quedan","perdidos"} en el orden de TRAINING_FUNNEL_STAGES.

    (C.1) De paso registra la PROCEDENCIA de las etiquetas —qué mallas y qué
    caserones las produjeron—, que es lo que la guardia de circularidad
    necesita para negarse a comparar el modelo contra su propia fuente.
    """
    _prov_capas.clear(); _prov_caserones.clear(); _prov_ucs.clear()
    pts = list(all_points())
    labels = {
        "total": "Total de puntos MWD",
        "entrenable": f"Entrenable (emboquillado <{inicio_cut_m:g} m + filtros de limpieza)",
        "caseron_entrena": ("En un caserón que ENTRENA ("
                            + (", ".join(sorted(training_caserones)) if training_caserones
                               else "todos los cargados") + ")"),
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
        cas_w = caseron_de_pozo(well)
        entrena_cas = (training_caserones is None) or (cas_w in training_caserones)
        for p in well.points:
            if not p.entrenable: continue
            n["entrenable"] += 1
            # Holdout por caserón: sus puntos se cuentan como disponibles pero
            # NO entrenan, y la etapa lo declara en el embudo.
            if not entrena_cas: continue
            n["caseron_entrena"] += 1
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
            # (C.1) Procedencia de la etiqueta: qué malla y qué caserón la
            # produjeron. Se registra AQUÍ, en el mismo pase que arma X/y,
            # para que no pueda desincronizarse de lo que el modelo entrenó.
            if p.capa_lito: _prov_capas.add(p.capa_lito)
            _prov_ucs.add(float(ucs))
            cas = caseron_de_pozo(well)
            if cas: _prov_caserones.add(cas)
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
        # No basta con decir "insuficientes": el embudo sabe DÓNDE se
        # perdieron, y la etapa que más descartó es la que hay que mirar.
        etapas = {st["etapa"]: st for st in funnel}
        peor = max((st for st in funnel if st["etapa"] != "total"),
                   key=lambda st: st["perdidos"], default=None)
        detalle = ""
        if peor and peor["perdidos"]:
            detalle = f" La etapa que más descartó: «{peor['label']}» (-{peor['perdidos']})."
        cas = etapas.get("caseron_entrena")
        if training_caserones and cas and cas["perdidos"]:
            detalle += (f" El reparto entrena/prueba vigente deja fuera "
                        f"{cas['perdidos']} punto(s): entrenan "
                        f"{', '.join(sorted(training_caserones))}.")
        return {"error": f"Insuficientes puntos ({len(X)} < 10).{detalle}", "funnel": funnel}
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
# ║  SESIÓN C — CONCORDANCIA                                                 ║
# ║                                                                          ║
# ║  C.0 (encuadre, gobierna todo lo demás): esto es ANÁLISIS DE            ║
# ║  CONCORDANCIA, no validación. La malla de Leapfrog NO es verdad         ║
# ║  terreno: es una interpolación construida desde los sondajes, casi      ║
# ║  exacta junto al sondaje porque ahí está restringida, e hipótesis       ║
# ║  progresivamente más débil al alejarse. Un desacuerdo entre MWD y malla ║
# ║  NO es un error del MWD hasta que se demuestre cuál de los dos falla.   ║
# ║                                                                          ║
# ║  Terminología obligatoria en interfaz, exportaciones y memoria:         ║
# ║  "modelo geológico informado por MWD". Nunca "corregido", nunca         ║
# ║  "exacto".                                                              ║
# ╚══════════════════════════════════════════════════════════════════════════╝

TERMINOLOGIA_C = "modelo geológico informado por MWD"

# (C.1) Procedencia de las etiquetas del último entrenamiento: qué mallas y
# qué caserones las produjeron. Lo puebla _training_funnel en el mismo pase
# que arma X/y, para que no pueda desincronizarse de lo que el modelo vio.
_prov_capas: set = set()
_prov_caserones: set = set()
# Etiquetas de UCS que el modelo llegó a ver. Sirve para saber qué unidades
# puede predecir: una que nunca entrenó es inalcanzable, y su discordancia
# mide el hueco de muestreo, no el método (riesgo 4 de la sesión 5).
_prov_ucs: set = set()


def _prov_ucs_entrenadas() -> set:
    return set(_prov_ucs)


def training_provenance() -> Dict[str, set]:
    """De dónde salieron las etiquetas con las que se entrenó el modelo."""
    return {"capas": set(_prov_capas), "caserones": set(_prov_caserones)}


def training_provenance_reset():
    _prov_capas.clear(); _prov_caserones.clear(); _prov_ucs.clear()


def circularity_check(capas) -> Optional[str]:
    """
    (C.1 — BLOQUEANTE) None si la comparación es admisible; el motivo del
    rechazo si no lo es.

    Si el modelo se entrenó con etiquetas derivadas de una malla, comparar
    sus predicciones contra ESA MISMA malla no demuestra concordancia:
    demuestra memorización. El sistema debe rechazarlo y decir por qué.

    Comparaciones admitidas:
      1. Contra registros de sondaje (sin mallas) — fuente independiente.
      2. Contra la malla de un caserón EXCLUIDO del entrenamiento.

    Basta UNA malla contaminada para rechazar el reporte completo: un
    resultado global mezclado con memorización no se puede leer.
    """
    if rf_model is None:
        return ("No hay modelo entrenado: sin procedencia de las etiquetas no se "
                "puede verificar la circularidad, así que la comparación no se "
                "autoriza. Entrena el modelo primero.")
    capas = [c for c in (capas or []) if c]
    if not capas:
        return None                      # contraste contra sondajes: independiente
    culpables = sorted(set(capas) & set(_prov_capas))
    if not culpables:
        return None
    return (f"Comparación RECHAZADA por circularidad: "
            f"{'la malla' if len(culpables)==1 else 'las mallas'} "
            f"{', '.join(culpables)} produjo las etiquetas con las que se entrenó "
            f"este modelo. Comparar sus predicciones contra su propia fuente solo "
            f"demostraría memorización, no concordancia. Contrasta contra registros "
            f"de sondaje, o contra la malla de un caserón excluido del "
            f"entrenamiento (entrenaron: {', '.join(sorted(_prov_caserones)) or '—'}).")


def concordance_report(fuente: str = "sondajes", capas=None) -> Dict:
    """
    (C.1/C.2) Reporte de concordancia. `fuente` es "sondajes" (Nivel 1: donde
    sondaje y MWD están colocalizados, único lugar con algo próximo a verdad
    terreno) o "malla" (Nivel 2: se reporta concordancia y se analiza la
    estructura espacial del desacuerdo).

    La guardia de circularidad corre ANTES de calcular nada: un reporte
    rechazado no trae métricas, para que no haya un número que alguien pueda
    citar fuera de contexto.
    """
    if rf_model is None:
        return {"status": "sin_modelo",
                "motivo": ("No hay modelo entrenado. El reporte de concordancia "
                           "compara predicciones contra una fuente de contraste; "
                           "sin modelo no hay predicciones que contrastar."),
                "terminologia": TERMINOLOGIA_C}
    motivo = circularity_check(capas if fuente == "malla" else [])
    if motivo:
        return {"status": "rechazado", "motivo": motivo, "fuente": fuente,
                "capas": sorted(capas or []), "terminologia": TERMINOLOGIA_C}
    return {"status": "ok", "fuente": fuente, "capas": sorted(capas or []),
            "nivel": 1 if fuente == "sondajes" else 2,
            "encuadre": ("Análisis de concordancia, no validación: la malla no es "
                         "verdad terreno. Un desacuerdo no es un error del MWD "
                         "hasta demostrar cuál de los dos falla. Terminología: "
                         + TERMINOLOGIA_C + "."),
            "terminologia": TERMINOLOGIA_C}


# ─── C.3 · DIAGNÓSTICO PRINCIPAL — concordancia vs distancia al sondaje ──────

def distancia_a_sondaje(este: float, norte: float, cota: float) -> Optional[float]:
    """
    Distancia euclidiana al punto más cercano de cualquier traza de sondaje.
    None si no hay sondajes cargados — un 0 ahí sería una mentira cómoda: no
    es que el punto esté sobre un sondaje, es que no hay con qué medir.
    """
    mejor = None
    for dh in drillholes.values():
        if not dh.trace: continue
        t = np.asarray(dh.trace, dtype=np.float64)
        d = np.sqrt(((t[:, 1:4] - np.array([este, norte, cota])) ** 2).sum(axis=1)).min()
        mejor = d if mejor is None else min(mejor, d)
    return float(mejor) if mejor is not None else None


def ucs_a_litologia(ucs: float) -> Optional[str]:
    """
    Litología cuya banda de UCS queda más cerca del valor predicho.

    El modelo predice UCS continua, pero la concordancia se juzga contra una
    LITOLOGÍA logueada. Traducir de vuelta es una decisión declarada, no un
    hecho: dos unidades con bandas traslapadas (ver B.7) son intrínsecamente
    confundibles a partir del UCS solo, y la matriz de confusión de C.6
    cruza justamente eso.
    """
    if ucs is None or not np.isfinite(ucs): return None
    mejor, mejor_d = None, None
    for a in attr_registry.values():
        if not a.usa_banda_ucs() or not a.tiene_banda_ucs(): continue
        ancla = a.ucs_ancla()
        if ancla is None: continue
        lo = a.ucs_min if a.ucs_min is not None else ancla
        hi = a.ucs_max if a.ucs_max is not None else ancla
        d = 0.0 if lo <= ucs <= hi else min(abs(ucs - lo), abs(ucs - hi))
        if mejor_d is None or d < mejor_d:
            mejor, mejor_d = a.id, d
    return mejor


def _lito_de_sondaje(este: float, norte: float, cota: float,
                     tol_m: float = 3.0) -> Optional[str]:
    """Unidad logueada en el testigo, en el tramo más cercano al punto dado."""
    mejor, mejor_d = None, None
    for dh in drillholes.values():
        if not dh.trace or not dh.lithology: continue
        t = np.asarray(dh.trace, dtype=np.float64)
        dd = np.sqrt(((t[:, 1:4] - np.array([este, norte, cota])) ** 2).sum(axis=1))
        i = int(dd.argmin())
        if mejor_d is not None and dd[i] >= mejor_d: continue
        prof = float(t[i, 0])
        for L in dh.lithology:
            try: f, to = float(L.get("from")), float(L.get("to"))
            except (TypeError, ValueError): continue
            if f <= prof <= to:
                u = L.get("unidad") or L.get("lito")
                if u: mejor, mejor_d = u, float(dd[i])
                break
    return mejor if (mejor_d is not None and mejor_d <= tol_m) else None


def _pares_contraste(fuente: str = "sondajes", capas=None):
    """
    Pares (punto, lito_predicha, lito_contraste, distancia_a_sondaje) para los
    puntos con predicción y una fuente de contraste disponible.
    """
    out = []
    for w in wells.values():
        for p in w.points:
            if p.ucs_ml is None: continue
            pred = ucs_a_litologia(p.ucs_ml)
            if pred is None: continue
            if fuente == "sondajes":
                real = _lito_de_sondaje(p.este, p.norte, p.cota)
            else:
                real = p.lito
            if real is None: continue
            out.append((p, pred, real, distancia_a_sondaje(p.este, p.norte, p.cota)))
    return out


def concordance_vs_distance(fuente: str = "sondajes", capas=None, n_bins: int = 5) -> Dict:
    """
    (C.3 — DIAGNÓSTICO PRINCIPAL) Concordancia en función de la distancia al
    sondaje más cercano, con la PENDIENTE reportada, no solo el gráfico.

    Lectura del signo (C.3):
      · alta cerca y DECAE al alejarse → la malla se degrada lejos del dato y
        el MWD aporta donde la interpolación ya no tiene información. Es el
        mejor resultado posible: valida el MWD y cuantifica el alcance útil
        de la malla.
      · plana → la malla es tan buena lejos como cerca; el MWD no agrega.
      · BAJA cerca de los sondajes → el problema es del modelo: ahí la malla
        está anclada al dato duro y no puede estar equivocada.
    """
    guard = circularity_check(capas if fuente == "malla" else [])
    if guard:
        return {"status": "rechazado", "motivo": guard, "terminologia": TERMINOLOGIA_C}
    pares = [x for x in _pares_contraste(fuente, capas) if x[3] is not None]
    if len(pares) < 10:
        return {"status": "sin_datos",
                "motivo": (f"Solo {len(pares)} punto(s) con predicción y fuente de "
                           f"contraste con distancia medible; se necesitan 10."),
                "terminologia": TERMINOLOGIA_C}
    d = np.array([x[3] for x in pares], dtype=np.float64)
    ok = np.array([x[1] == x[2] for x in pares], dtype=np.float64)
    # (riesgo 4 de la sesión 5, aplicado aquí) Una unidad presente en el
    # contraste pero AUSENTE del entrenamiento es inalcanzable para el
    # modelo: su discordancia mide el hueco de muestreo, no el método. Sin
    # declararlo, una concordancia baja se leería como fallo del modelo.
    entrenadas = {a for a in (ucs_a_litologia(v) for v in _prov_ucs_entrenadas()) if a}
    contraste = collections.Counter(x[2] for x in pares)
    no_entr = sorted(u for u in contraste if u not in entrenadas)
    n_no_entr = sum(contraste[u] for u in no_entr)
    cobertura = {"unidades_contraste": sorted(contraste),
                 "entrenadas": sorted(entrenadas),
                 "no_entrenadas": no_entr,
                 "n_no_entrenada": n_no_entr,
                 "frac_no_entrenada": round(n_no_entr / len(pares), 4)}
    bordes = np.linspace(d.min(), d.max(), n_bins + 1)
    bins = []
    for i in range(n_bins):
        m = (d >= bordes[i]) & (d <= bordes[i + 1] if i == n_bins - 1 else d < bordes[i + 1])
        if not m.any(): continue
        bins.append({"d_min": round(float(bordes[i]), 2), "d_max": round(float(bordes[i + 1]), 2),
                     "n": int(m.sum()), "concordancia": round(float(ok[m].mean()), 4)})
    # Pendiente sobre los puntos, no sobre los bins: no depende del binning.
    pend = float(np.polyfit(d, ok, 1)[0]) if d.std() > 0 else 0.0
    if cobertura["frac_no_entrenada"] > 0.5:
        interp = (
            f"NO se puede leer como fallo del modelo: el "
            f"{100*cobertura['frac_no_entrenada']:.0f}% de la fuente de contraste "
            f"es de unidad(es) que el entrenamiento NUNCA vio "
            f"({', '.join(no_entr)}), así que el modelo no puede predecirlas y su "
            f"discordancia mide el HUECO DE MUESTREO, no el método. Carga mallas "
            f"de esas unidades, o restringe el contraste a las unidades "
            f"entrenadas ({', '.join(sorted(entrenadas)) or '—'}), antes de "
            f"interpretar la pendiente.")
    elif pend < -1e-4:
        interp = ("La concordancia DECAE al alejarse del sondaje: la malla se degrada "
                  "lejos del dato duro y el MWD aporta información donde la "
                  "interpolación ya no la tiene. Es el mejor resultado posible — "
                  "valida el MWD y cuantifica el alcance útil de la malla.")
    elif pend > 1e-4:
        interp = ("La concordancia es MÁS BAJA cerca de los sondajes, donde la malla "
                  "está anclada al dato duro y no puede estar equivocada. El problema "
                  "es del modelo, no de la malla: revisar antes de seguir.")
    else:
        interp = ("La concordancia es plana con la distancia: la malla es tan buena "
                  "lejos como cerca del dato, y el MWD no agrega información "
                  "geológica en este conjunto.")
    return {"status": "ok", "fuente": fuente, "nivel": 1 if fuente == "sondajes" else 2,
            "n": len(pares), "bins": bins, "cobertura": cobertura,
            "pendiente": round(pend, 6),
            "pendiente_unidad": "Δconcordancia por metro de distancia al sondaje",
            "concordancia_global": round(float(ok.mean()), 4),
            "interpretacion": interp, "terminologia": TERMINOLOGIA_C}


# ─── C.4 · ESTRUCTURA ESPACIAL DEL DESACUERDO ───────────────────────────────

def distancia_a_borde_malla(este: float, norte: float, cota: float,
                            capa: str) -> Optional[float]:
    """
    Distancia al borde más cercano del bbox de la malla. Aproximación
    deliberada y declarada: la distancia exacta a la superficie triangulada
    es cara, y para separar "a uno o dos metros de un borde" de "en el
    interior macizo" —que es lo que C.4 necesita distinguir— el bbox basta.
    """
    lay = layers.get(capa)
    if lay is None: return None
    p = np.array([este, norte, cota], dtype=np.float64)
    dentro = np.all((p >= lay.bbox_min) & (p <= lay.bbox_max))
    if not dentro: return 0.0
    return float(np.min(np.concatenate([p - lay.bbox_min, lay.bbox_max - p])))


BORDE_MALLA_M = 2.0     # "a uno o dos metros de un borde" (C.4)


def disagreement_vs_mesh_edge(fuente: str = "sondajes", capas=None) -> Dict:
    """
    (C.4) Clasifica cada punto DISCORDANTE por su distancia al borde de malla:
    cerca del borde es precisión de interpolación, esperable; en el interior
    macizo de un cuerpo es un problema real que hay que investigar. La
    distinción separa "la malla está corrida" de "el modelo está mal".
    """
    guard = circularity_check(capas if fuente == "malla" else [])
    if guard:
        return {"status": "rechazado", "motivo": guard, "terminologia": TERMINOLOGIA_C}
    pares = _pares_contraste(fuente, capas)
    if not pares:
        return {"status": "sin_datos",
                "motivo": "No hay puntos con predicción y fuente de contraste.",
                "terminologia": TERMINOLOGIA_C}
    disc = [(p, pr, re) for p, pr, re, _ in pares if pr != re]
    if not disc:
        return {"status": "sin_desacuerdos", "n_pares": len(pares),
                "terminologia": TERMINOLOGIA_C}
    dists, interior = [], []
    for p, pr, re in disc:
        d = distancia_a_borde_malla(p.este, p.norte, p.cota, p.capa_lito) if p.capa_lito else None
        if d is None: continue
        dists.append(d)
        if d > BORDE_MALLA_M:
            interior.append({"este": round(p.este, 2), "norte": round(p.norte, 2),
                             "cota": round(p.cota, 2), "d_borde_m": round(d, 2),
                             "predicha": pr, "contraste": re, "capa": p.capa_lito})
    if not dists:
        return {"status": "sin_datos",
                "motivo": "Los puntos discordantes no tienen capa de litología asociada.",
                "terminologia": TERMINOLOGIA_C}
    arr = np.array(dists)
    hist, bordes = np.histogram(arr, bins=min(10, max(3, len(arr) // 5)))
    return {"status": "ok", "n_discordantes": len(disc), "n_medidos": len(dists),
            "histograma": {"conteo": hist.tolist(),
                           "bordes_m": [round(float(b), 2) for b in bordes]},
            "cerca_del_borde": int((arr <= BORDE_MALLA_M).sum()),
            "interior_macizo": int((arr > BORDE_MALLA_M).sum()),
            "umbral_borde_m": BORDE_MALLA_M,
            "zonas_interior": interior[:200],
            "interpretacion": (
                f"{int((arr <= BORDE_MALLA_M).sum())} desacuerdo(s) a ≤{BORDE_MALLA_M:g} m "
                f"de un borde: precisión de interpolación, esperable. "
                f"{int((arr > BORDE_MALLA_M).sum())} en el interior macizo de un cuerpo: "
                f"ahí el desacuerdo no se explica por el borde y hay que investigarlo."),
            "terminologia": TERMINOLOGIA_C}


def interior_disagreement_zones(fuente: str = "sondajes", capas=None) -> List[Dict]:
    """(C.7) Zonas de desacuerdo interior con coordenadas, para geología."""
    rep = disagreement_vs_mesh_edge(fuente, capas)
    return rep.get("zonas_interior", []) if rep.get("status") == "ok" else []


# ─── C.5 · DESFASE DE CONTACTOS ─────────────────────────────────────────────

def contact_offset_report(max_busqueda_m: float = 10.0) -> Dict:
    """
    (C.5) Para cada contacto que predice la malla, el desfase δ hasta la firma
    detectada por el MWD (pico de DI). Reporta media, mediana, desviación y
    sesgo.

    · δ con SESGO SISTEMÁTICO  → la malla está desplazada, y δ cuantifica cuánto.
    · δ SIMÉTRICO con dispersión → ruido de interpolación.

    Ese δ es el margen operacional de la función de anticipación: cuántos
    metros antes del contacto previsto conviene bajar PP.
    """
    deltas = []
    for wn, w in wells.items():
        pts = w.points
        if len(pts) < 3: continue
        # Contactos de la malla: donde cambia la litología a lo largo del pozo.
        contactos = [pts[i].largo for i in range(1, len(pts))
                     if pts[i].lito != pts[i - 1].lito and (pts[i].lito or pts[i - 1].lito)]
        if not contactos: continue
        picos = [lp for lp, _, _ in di_peaks(w)]
        if not picos: continue
        pa = np.array(picos, dtype=np.float64)
        for c in contactos:
            d = pa - c                      # signo: + el pico va DESPUÉS del contacto
            j = int(np.abs(d).argmin())
            if abs(d[j]) <= max_busqueda_m:
                deltas.append(float(d[j]))
    if len(deltas) < 3:
        return {"status": "sin_datos",
                "motivo": (f"Solo {len(deltas)} contacto(s) con firma MWD a menos de "
                           f"{max_busqueda_m:g} m; se necesitan 3 para hablar de sesgo."),
                "terminologia": TERMINOLOGIA_C}
    a = np.array(deltas)
    media, mediana, sd = float(a.mean()), float(np.median(a)), float(a.std())
    sesgo = float(((a - media) ** 3).mean() / (sd ** 3)) if sd > 0 else 0.0
    sistematico = abs(media) > sd / 2 if sd > 0 else abs(media) > 0
    interp = (
        f"δ medio {media:+.2f} m con desviación {sd:.2f} m: "
        + ("SESGO SISTEMÁTICO — la malla está desplazada y δ cuantifica cuánto. "
           f"Margen operacional sugerido para la anticipación: {abs(media):.1f} m "
           "antes del contacto previsto."
           if sistematico else
           "distribución simétrica alrededor de cero — es ruido de interpolación, "
           "no un desplazamiento de la malla."))
    return {"status": "ok", "n": len(deltas), "media": round(media, 3),
            "mediana": round(mediana, 3), "desviacion": round(sd, 3),
            "sesgo": round(sesgo, 3), "sistematico": bool(sistematico),
            "margen_operacional_m": round(abs(media), 2) if sistematico else None,
            "interpretacion": interp, "terminologia": TERMINOLOGIA_C}


# ─── C.6 · MATRIZ DE CONFUSIÓN, CRUZADA CON EL TRASLAPE DE BANDAS ───────────

def confusion_matrix_report(fuente: str = "sondajes", capas=None) -> Dict:
    """
    (C.6) Matriz de confusión entre la litología predicha por MWD y la de la
    fuente de contraste. Reporta concordancia global, por unidad, y los pares
    que más se confunden.

    Y los CRUZA con B.7: las unidades cuyas bandas de UCS se traslapan
    deberían ser las que más se confunden — si se confunden unidades de
    bandas bien separadas, hay algo más ocurriendo, y eso es lo que hay que
    mirar.
    """
    guard = circularity_check(capas if fuente == "malla" else [])
    if guard:
        return {"status": "rechazado", "motivo": guard, "terminologia": TERMINOLOGIA_C}
    pares = _pares_contraste(fuente, capas)
    if len(pares) < 5:
        return {"status": "sin_datos",
                "motivo": f"Solo {len(pares)} par(es) predicción↔contraste; se necesitan 5.",
                "terminologia": TERMINOLOGIA_C}
    unidades = sorted({x[1] for x in pares} | {x[2] for x in pares})
    idx = {u: i for i, u in enumerate(unidades)}
    M = np.zeros((len(unidades), len(unidades)), dtype=int)
    for _, pred, real, _ in pares:
        M[idx[real], idx[pred]] += 1          # filas = contraste, columnas = predicha
    diag = int(np.trace(M)); total = int(M.sum())
    por_unidad = {}
    for u in unidades:
        i = idx[u]; n = int(M[i].sum())
        if n: por_unidad[u] = {"n": n, "concordancia": round(float(M[i, i] / n), 4)}
    confundidos = []
    for i, ui in enumerate(unidades):
        for j, uj in enumerate(unidades):
            if i == j or M[i, j] == 0: continue
            confundidos.append({"contraste": ui, "predicha": uj, "n": int(M[i, j])})
    confundidos.sort(key=lambda c: -c["n"])

    # Cruce con B.7: ¿los pares confundidos son los de bandas traslapadas?
    traslape = ucs_band_overlap_report()
    pares_trasl = {frozenset((p["a"], p["b"])) for p in traslape["confianza"]}
    cruce = []
    for c in confundidos[:10]:
        par = frozenset((c["contraste"], c["predicha"]))
        se_traslapan = par in pares_trasl
        cruce.append({**c, "bandas_se_traslapan": se_traslapan,
                      "nota": ("esperable: sus bandas de UCS se traslapan (B.7)"
                               if se_traslapan else
                               "ATENCIÓN: bandas bien separadas y aun así se confunden — "
                               "hay algo más ocurriendo que el traslape de UCS")})
    return {"status": "ok", "fuente": fuente, "unidades": unidades,
            "matriz": M.tolist(), "orden": "filas=contraste, columnas=predicha por MWD",
            "n": total, "concordancia_global": round(diag / total, 4) if total else None,
            "por_unidad": por_unidad, "pares_confundidos": confundidos[:20],
            "cruce_traslape_ucs": cruce, "terminologia": TERMINOLOGIA_C}


# ─── C.7 · SALIDAS ──────────────────────────────────────────────────────────

def concordance_full_report(fuente: str = "sondajes", capas=None) -> Dict:
    """(C.7) Reporte completo: encuadre + C.3 a C.6 en una sola llamada."""
    return {
        "encuadre": ("ANÁLISIS DE CONCORDANCIA, NO VALIDACIÓN. La malla no es verdad "
                     "terreno: es una interpolación construida desde los sondajes, "
                     "restringida junto al sondaje e hipótesis progresivamente más "
                     "débil al alejarse. Un desacuerdo no es un error del MWD hasta "
                     "demostrar cuál de los dos falla. Terminología: "
                     + TERMINOLOGIA_C + "."),
        "fuente": fuente, "capas": sorted(capas or []),
        "c3": concordance_vs_distance(fuente, capas),
        "c4": disagreement_vs_mesh_edge(fuente, capas),
        "c5": contact_offset_report(),
        "c6": confusion_matrix_report(fuente, capas),
        "terminologia": TERMINOLOGIA_C,
    }


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  COHERENCIA FÍSICA SE ↔ UCS SOBRE ROCA INTACTA                          ║
# ║                                                                          ║
# ║  Test de validez del supuesto fundamental, previo al ML: si la energía  ║
# ║  específica de los pozos que caen en litologías con UCS bien conocido   ║
# ║  por ensayo no ordena esas litologías por resistencia, el MWD no mide   ║
# ║  lo que creemos y ningún modelo lo arregla.                             ║
# ║                                                                          ║
# ║  Separa dos preguntas que el R² del modelo confunde:                    ║
# ║    · ¿el MWD tiene señal física?           -> este reporte              ║
# ║    · ¿las etiquetas alcanzan para entrenar? -> el R² y el LOCO-CV       ║
# ║                                                                          ║
# ║  EL CONFUNDIMIENTO A SORTEAR: SE_reacción = (PP + RP + AP) / ROP, y PP  ║
# ║  es la ÚNICA variable que el operador manipula — y la sube en roca      ║
# ║  dura. Parte de la relación SE↔UCS podría venir de la RESPUESTA DEL     ║
# ║  OPERADOR, no de la roca. Por eso el reporte estratifica por PP y mira  ║
# ║  ROP por separado: ROP no se fija directamente, así que si también      ║
# ║  ordena las litologías, la señal es de la roca.                         ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def _spearman(x, y) -> Optional[float]:
    """Correlación de rangos. None si no hay varianza en alguno de los dos."""
    x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    if x.size < 2 or y.size < 2: return None
    rx = np.argsort(np.argsort(x)).astype(np.float64)
    ry = np.argsort(np.argsort(y)).astype(np.float64)
    if rx.std() == 0 or ry.std() == 0: return None
    return float(np.corrcoef(rx, ry)[0, 1])


# Velocidad de penetración mínima FÍSICA. Por debajo, la broca no está
# rompiendo roca: es cambio de barra, atasco o registro con el avance
# detenido, y SE = (PP+RP+AP)/ROP se dispara a valores sin significado
# (se observaron medianas de 2·10¹¹ en tramos con ROP→0). Es un límite
# físico y trazable, NO un percentil: el proyecto prohíbe filtrar por
# percentiles justamente para no recortar datos válidos sin criterio.
ROP_MIN_FISICA = 0.05          # m/min


def _se_por_dominio(solo_roca_intacta: bool = True) -> Tuple[Dict[str, Dict], Dict]:
    """
    SE, ROP y PP agregados por LITOLOGÍA con UCS de laboratorio conocido.

    Dos exclusiones, ambas declaradas en el reporte:

    · Dominios donde predomina una ESTRUCTURA (A.5) — "Bht::PCS_1043:FM1" y
      similares. Heredan el ucs_lab de su litología, pero un dominio de falla
      es por definición lo contrario de roca intacta, y mezclarlo destruye el
      análisis: con los datos reales inflaba tres litologías a diecinueve
      dominios, todos repitiendo el mismo UCS con SE dispares, lo que anula
      la correlación de rangos.
    · Puntos con ROP por debajo de ROP_MIN_FISICA, donde SE no tiene
      significado físico.

    `solo_roca_intacta` aparta además los puntos con DI sobre el umbral, que
    es justamente lo que el DI existe para permitir.
    """
    acc: Dict[str, Dict[str, list]] = {}
    apartados_estructura, rop_no_fisica = set(), 0
    for w in wells.values():
        for p in w.points:
            if not p.entrenable or not p.dominio: continue
            if getattr(p, "ambiguo", False): continue
            dom = domains.get(p.dominio)
            if not dom or dom.get("ucs_lab") is None: continue
            # Dominio con estructura predominante: no es roca intacta.
            if dom.get("estructura_id") or "::" in p.dominio:
                apartados_estructura.add(p.dominio); continue
            if solo_roca_intacta and p.di is not None and p.di > di_threshold:
                continue
            if p.vel is None or not np.isfinite(p.vel) or p.vel < ROP_MIN_FISICA:
                rop_no_fisica += 1; continue
            if p.se is None or not np.isfinite(p.se): continue
            # La litología, no el dominio compuesto: Bht~Fk y Bht comparten
            # matriz y banda de UCS, y separarlos fragmentaría la muestra.
            lito = p.lito or p.dominio
            d = acc.setdefault(lito, {"se": [], "rop": [], "pp": [],
                                      "ucs_lab": dom["ucs_lab"]})
            d["se"].append(float(p.se))
            d["rop"].append(float(p.vel))
            if p.pp is not None and np.isfinite(p.pp): d["pp"].append(float(p.pp))
    out = {}
    for k, v in acc.items():
        se = np.array(v["se"])
        if se.size < 5: continue
        out[k] = {"dominio": k, "ucs_lab": float(v["ucs_lab"]), "n": int(se.size),
                  "se_mediana": round(float(np.median(se)), 2),
                  "se_media": round(float(se.mean()), 2),
                  "se_cv": round(float(se.std() / abs(se.mean())), 4) if se.mean() else None,
                  "rop_mediana": round(float(np.median(v["rop"])), 4) if v["rop"] else None,
                  "pp_mediana": round(float(np.median(v["pp"])), 2) if v["pp"] else None}
    return out, {"estructura": sorted(apartados_estructura), "rop": rop_no_fisica}


def _coherencia_desde(porcion: Dict[str, Dict]) -> Dict:
    """Métricas de coherencia a partir del agregado por dominio."""
    doms = sorted(porcion.values(), key=lambda d: d["ucs_lab"])
    ucs = [d["ucs_lab"] for d in doms]
    se = [d["se_mediana"] for d in doms]
    rop = [d["rop_mediana"] for d in doms if d["rop_mediana"] is not None]
    rho = _spearman(ucs, se)
    monotona = all(se[i] <= se[i + 1] for i in range(len(se) - 1)) if len(se) > 1 else None
    cvs = [d["se_cv"] for d in doms if d["se_cv"] is not None]
    return {"dominios": doms, "rho_spearman": round(rho, 4) if rho is not None else None,
            "monotona": monotona,
            "cv_medio_intra_dominio": round(float(np.mean(cvs)), 4) if cvs else None,
            "rho_rop": (round(_spearman(ucs[:len(rop)], rop), 4)
                        if len(rop) == len(ucs) and _spearman(ucs, rop) is not None else None),
            "se_mediana_por_dominio": {d["dominio"]: d["se_mediana"] for d in doms}}


PP_ESTRATOS = ((90, 130), (130, 170), (170, 230))     # PP: 90 a 230 bar


def se_ucs_coherence_report() -> Dict:
    """
    Coherencia entre la energía específica de reacción y el UCS de
    laboratorio, por dominio y sobre ROCA INTACTA.

    La regla física que debe cumplirse: a mayor UCS de la matriz, mayor
    energía específica para romperla. Si no se cumple, el problema está
    antes del modelo.

    Devuelve además:
      · la MISMA comparación SIN apartar las discontinuidades, para ver si
        el DI mejora la coherencia (validación empírica del DI);
      · la relación estratificada por PP, y la de ROP sola, para separar la
        señal de la roca de la respuesta del operador.
    """
    intacta, excl = _se_por_dominio(solo_roca_intacta=True)
    if len(intacta) < 2:
        return {"status": "sin_datos",
                "motivo": (f"Solo {len(intacta)} dominio(s) con UCS de laboratorio y "
                           f"≥5 puntos de roca intacta. Hacen falta al menos 2 para "
                           f"poder hablar de coherencia: con uno solo no hay nada "
                           f"que ordenar."),
                "terminologia": TERMINOLOGIA_C}
    base = _coherencia_desde(intacta)
    todo, _ = _se_por_dominio(solo_roca_intacta=False)
    comp = _coherencia_desde(todo) if len(todo) >= 2 else {}

    # ¿Apartar las discontinuidades mejoró la coherencia? Dos señales: la
    # correlación de rangos sube, o la dispersión intra-dominio baja.
    di_mejora = None
    if comp:
        r0 = comp.get("rho_spearman"); r1 = base.get("rho_spearman")
        c0 = comp.get("cv_medio_intra_dominio"); c1 = base.get("cv_medio_intra_dominio")
        mejor_rho = (r1 is not None and r0 is not None and r1 > r0 + 1e-9)
        mejor_cv = (c1 is not None and c0 is not None and c1 < c0 - 1e-9)
        di_mejora = bool(mejor_rho or mejor_cv)

    # Estratificación por PP: si la relación se sostiene DENTRO de rangos
    # estrechos de PP, no es artefacto de que el operador suba PP en roca dura.
    estratos = []
    for lo, hi in PP_ESTRATOS:
        acc: Dict[str, Dict] = {}
        for w in wells.values():
            for p in w.points:
                if not p.entrenable or not p.dominio: continue
                if p.di is not None and p.di > di_threshold: continue
                if p.pp is None or not (lo <= p.pp < hi): continue
                dom = domains.get(p.dominio)
                if not dom or dom.get("ucs_lab") is None: continue
                if dom.get("estructura_id") or "::" in p.dominio: continue
                if p.vel is None or not np.isfinite(p.vel) or p.vel < ROP_MIN_FISICA: continue
                if p.se is None or not np.isfinite(p.se): continue
                d = acc.setdefault(p.lito or p.dominio, {"se": [], "ucs_lab": dom["ucs_lab"]})
                d["se"].append(float(p.se))
        doms = [{"dominio": k, "ucs_lab": v["ucs_lab"],
                 "se_mediana": round(float(np.median(v["se"])), 2), "n": len(v["se"])}
                for k, v in acc.items() if len(v["se"]) >= 5]
        if len(doms) >= 2:
            doms.sort(key=lambda d: d["ucs_lab"])
            rho = _spearman([d["ucs_lab"] for d in doms], [d["se_mediana"] for d in doms])
            estratos.append({"pp_min": lo, "pp_max": hi, "n_dominios": len(doms),
                             "rho_spearman": round(rho, 4) if rho is not None else None,
                             "dominios": doms})

    rho = base["rho_spearman"]
    if rho is None:
        veredicto = ("No se puede evaluar la coherencia: no hay variación suficiente "
                     "entre dominios.")
    elif rho > 0.5 and base["monotona"]:
        veredicto = (f"COHERENTE: la energía específica ordena las litologías por su "
                     f"UCS de laboratorio (ρ={rho:+.2f}, monotonía respetada). Es la "
                     f"regla física que debe cumplirse en roca intacta, y se cumple: "
                     f"el MWD está midiendo resistencia de matriz.")
    elif rho > 0.5:
        veredicto = (f"COHERENTE EN TENDENCIA pero sin monotonía estricta (ρ={rho:+.2f}): "
                     f"la SE sube con el UCS en conjunto, pero al menos un par de "
                     f"dominios queda fuera de orden. Revisar cuál y por qué.")
    elif rho < -0.5:
        veredicto = (f"INCOHERENTE — relación INVERTIDA (ρ={rho:+.2f}): la roca de mayor "
                     f"UCS de laboratorio sale con MENOS energía específica. Eso "
                     f"contradice la física de la perforación en roca intacta. Antes de "
                     f"modelar nada hay que explicar esto: revisar la asignación de "
                     f"bandas de UCS, el cruce punto↔malla, o si los tramos siguen "
                     f"contaminados por discontinuidades.")
    else:
        veredicto = (f"SIN COHERENCIA CLARA (ρ={rho:+.2f}): la energía específica no "
                     f"ordena las litologías por su UCS. O las bandas de laboratorio no "
                     f"representan a estos dominios, o el MWD no está resolviendo la "
                     f"diferencia entre ellos.")

    return {
        "status": "ok",
        "dominios": base["dominios"],
        "n_dominios_estructura_apartados": len(excl["estructura"]),
        "dominios_estructura_apartados": excl["estructura"][:20],
        "n_puntos_rop_no_fisica": excl["rop"],
        "rop_min_fisica": ROP_MIN_FISICA,
        "rho_spearman": rho,
        "monotona": base["monotona"],
        "cv_medio_intra_dominio": base["cv_medio_intra_dominio"],
        "se_mediana_por_dominio": base["se_mediana_por_dominio"],
        "veredicto": veredicto,
        "sin_apartar_discontinuidades": comp,
        "di_mejora_coherencia": di_mejora,
        "di_nota": (
            "Apartar los tramos con DI sobre el umbral MEJORA la coherencia SE↔UCS: "
            "el DI está haciendo su trabajo en estos datos, no solo por autoridad de "
            "Fernández et al. 2023." if di_mejora else
            "Apartar los tramos con DI sobre el umbral NO mejora la coherencia aquí. "
            "No invalida el DI, pero conviene revisar el umbral y los pesos antes de "
            "apoyarse en él." if di_mejora is False else
            "No hay con qué comparar el efecto de apartar discontinuidades."),
        "rop": {"rho_spearman": base["rho_rop"],
                "nota": ("ROP NO la fija directamente el operador: si también ordena "
                         "las litologías por UCS, la señal es de la roca y no de la "
                         "respuesta del operador.")},
        "estratos_pp": estratos,
        "advertencia_pp": (
            "SE_reacción = (PP + RP + AP) / ROP, y PP es la ÚNICA variable que el "
            "operador manipula — y la sube en roca dura. Parte de la relación SE↔UCS "
            "puede venir de esa respuesta y no de la roca. Por eso se reporta la "
            "relación DENTRO de estratos estrechos de PP: si se sostiene ahí, no es "
            "artefacto del operador. El análisis agregado de PP se aborda de frente "
            "en la sesión de curvas de respuesta."),
        "terminologia": TERMINOLOGIA_C,
    }


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  SESIÓN 7 — CURVAS DE RESPUESTA A PP Y PRESCRIPCIÓN                     ║
# ║                                                                          ║
# ║  EL CONFUNDIMIENTO QUE GOBIERNA LA SESIÓN: PP es la ÚNICA variable que  ║
# ║  el operador manipula, y la manipula EN RESPUESTA a la roca — sube PP   ║
# ║  en roca dura. El análisis agregado muestra por eso la relación         ║
# ║  INVERTIDA: parece que subir PP endurece la roca. En estos datos el     ║
# ║  efecto ya está medido: PP mediana 211 bar en Bht y Kpcli contra 180    ║
# ║  en Brecha mixta, que es la unidad que se perfora más lento.            ║
# ║                                                                          ║
# ║  De ahí la separación:                                                  ║
# ║    · CARACTERIZACIÓN  roca <- MWD, PP como covariable de CONTEXTO       ║
# ║                       (train_rf / ML_FEATURES — no se toca desde aquí)  ║
# ║    · PRESCRIPCIÓN     desempeño <- dominio y PP, PP como variable de    ║
# ║                       DECISIÓN optimizable (este bloque)                ║
# ║                                                                          ║
# ║  Todo análisis de PP va ESTRATIFICADO POR DOMINIO. Agregado no          ║
# ║  significa nada, y el reporte lo calcula solo para poder mostrar la     ║
# ║  trampa junto a su advertencia.                                         ║
# ╚══════════════════════════════════════════════════════════════════════════╝

PP_MIN_OPERACIONAL, PP_MAX_OPERACIONAL = 90.0, 230.0     # bar
PP_PASO_BAR = 10.0          # ancho del bin de PP en las curvas
PP_MIN_PUNTOS_BIN = 20      # bins con menos muestras no se grafican


def _bins_pp(pp: float) -> float:
    """Centro del bin de PP al que cae una medición."""
    return float(np.floor(pp / PP_PASO_BAR) * PP_PASO_BAR + PP_PASO_BAR / 2.0)


def _curva_pp(puntos) -> List[Dict]:
    """Curva PP → (ROP, SE, CV(SE)) a partir de una lista de MWDPoint."""
    acc: Dict[float, Dict[str, list]] = {}
    for p in puntos:
        if p.pp is None or not np.isfinite(p.pp): continue
        if not (PP_MIN_OPERACIONAL <= p.pp <= PP_MAX_OPERACIONAL): continue
        if p.vel is None or not np.isfinite(p.vel) or p.vel < ROP_MIN_FISICA: continue
        if p.se is None or not np.isfinite(p.se): continue
        d = acc.setdefault(_bins_pp(p.pp), {"rop": [], "se": []})
        d["rop"].append(float(p.vel)); d["se"].append(float(p.se))
    curva = []
    for pp in sorted(acc):
        rop = np.array(acc[pp]["rop"]); se = np.array(acc[pp]["se"])
        if rop.size < PP_MIN_PUNTOS_BIN: continue
        curva.append({"pp": pp, "n": int(rop.size),
                      "rop_mediana": round(float(np.median(rop)), 4),
                      "se_mediana": round(float(np.median(se)), 2),
                      # CV(SE): la dispersión de la energía específica es la
                      # señal de que el equipo trabaja inestable a ese PP.
                      "cv_se": round(float(se.std() / abs(se.mean())), 4) if se.mean() else None})
    return curva


def _saturacion(curva: List[Dict]) -> Optional[float]:
    """
    PP a partir del cual subir más deja de mejorar la ROP. Se toma el primer
    bin cuya ROP ya alcanzó el 98% del máximo de la curva: pasado ese punto,
    más percusión es desgaste sin retorno.
    """
    if len(curva) < 3: return None
    rops = [c["rop_mediana"] for c in curva]
    techo = max(rops)
    if techo <= 0: return None
    for c in curva:
        if c["rop_mediana"] >= 0.98 * techo:
            return c["pp"]
    return None


def _pendiente(xs, ys) -> Optional[float]:
    x, y = np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)
    if x.size < 2 or x.std() == 0: return None
    return float(np.polyfit(x, y, 1)[0])


def pp_response_curves(solo_roca_intacta: bool = True) -> Dict:
    """
    (Sesión 7) Curvas PP → (ROP, SE, CV(SE)) POR DOMINIO, con punto de
    saturación. Estratificado por dominio siempre: el agregado se calcula
    aparte y viene con su advertencia, porque es justo la lectura que el
    confundimiento del operador vuelve engañosa.
    """
    por_dom: Dict[str, list] = {}
    todos = []
    # Misma exclusión que el análisis de coherencia SE↔UCS: un dominio donde
    # predomina una ESTRUCTURA ("Bht::PCS_1043:FM1") no es roca intacta, y su
    # curva de respuesta describe el comportamiento del equipo dentro de una
    # falla, no dentro de una litología. Se aparta y se declara.
    apartados_estructura = set()
    for w in wells.values():
        for p in w.points:
            if not p.entrenable or not p.dominio: continue
            if getattr(p, "ambiguo", False): continue
            dom_reg = domains.get(p.dominio) or {}
            if solo_roca_intacta and (dom_reg.get("estructura_id") or "::" in p.dominio):
                apartados_estructura.add(p.dominio); continue
            if solo_roca_intacta and p.di is not None and p.di > di_threshold:
                continue
            por_dom.setdefault(p.lito or p.dominio, []).append(p)
            todos.append(p)
    if not por_dom:
        return {"status": "sin_datos",
                "motivo": ("No hay puntos con dominio asignado para construir curvas."
                           + (f" Se apartaron {len(apartados_estructura)} dominio(s) "
                              "con estructura predominante, que no son roca intacta."
                              if apartados_estructura else "")),
                "apartados_estructura": sorted(apartados_estructura),
                "estratificado_por_dominio": True}
    dominios = {}
    for dom, pts in por_dom.items():
        curva = _curva_pp(pts)
        if len(curva) < 2: continue
        sat = _saturacion(curva)
        pend = _pendiente([c["pp"] for c in curva], [c["rop_mediana"] for c in curva])
        interp = (
            f"Dentro de {dom}, subir PP "
            + ("MEJORA el avance" if (pend or 0) > 0 else
               "NO mejora el avance" if (pend or 0) == 0 else "EMPEORA el avance")
            + (f"; la ROP satura en {sat:g} bar, y más percusión pasado ese punto es "
               f"desgaste sin retorno." if sat is not None else
               "; no se detecta saturación en el rango observado."))
        dominios[dom] = {"curva": curva, "pp_saturacion": sat,
                         "pendiente_rop": round(pend, 6) if pend is not None else None,
                         "n_puntos": len(pts), "interpretacion": interp}
    if not dominios:
        return {"status": "sin_datos",
                "motivo": (f"Ningún dominio alcanza {PP_MIN_PUNTOS_BIN} puntos en al "
                           f"menos dos bins de PP de {PP_PASO_BAR:g} bar."),
                "estratificado_por_dominio": True}

    # El agregado existe SOLO para mostrar la trampa junto a su advertencia.
    curva_agg = _curva_pp(todos)
    pend_agg = _pendiente([c["pp"] for c in curva_agg],
                          [c["rop_mediana"] for c in curva_agg]) if curva_agg else None
    # Si el agregado se invierte respecto de los dominios se dice; y si NO se
    # invierte, también. Que la trampa no se materialice con esta mezcla de
    # dominios no vuelve legítimo el agregado: sigue sin poder usarse para
    # decidir PP, porque el signo depende de qué litologías pesen en la
    # muestra, no de la física del equipo.
    pend_dom = [d["pendiente_rop"] for d in dominios.values()
                if d["pendiente_rop"] is not None]
    invertido = (pend_agg is not None and pend_dom
                 and all(p > 0 for p in pend_dom) and pend_agg < 0)
    if pend_agg is None or not pend_dom:
        medido = "No hay pendientes suficientes para comparar el agregado con los dominios."
    elif invertido:
        medido = (f"MEDIDO: dentro de cada dominio la pendiente es positiva y el "
                  f"agregado sale {pend_agg:+.6f} — la relación aparece INVERTIDA, "
                  "que es exactamente la trampa.")
    else:
        medido = (f"MEDIDO: con esta mezcla de dominios el agregado sale "
                  f"{pend_agg:+.6f} y NO se invierte. Es una coincidencia de qué "
                  "litologías pesan en la muestra, no una validación del agregado.")
    agregado = {
        "curva": curva_agg, "pendiente_rop": round(pend_agg, 6) if pend_agg is not None else None,
        "invertido": bool(invertido),
        "advertencia": (
            "NO USAR para decidir PP. Este agregado mezcla dominios y el operador "
            "sube PP en roca dura, así que su pendiente mide la mezcla de "
            "litologías de la muestra, no la respuesta del equipo. Es la trampa "
            "que esta sesión existe para evitar; se calcula solo para poder "
            "mostrarla al lado de las curvas por dominio. " + medido),
    }
    return {"status": "ok", "estratificado_por_dominio": True,
            "dominios": dominios, "agregado_todos_los_dominios": agregado,
            "apartados_estructura": sorted(apartados_estructura),
            "solo_roca_intacta": solo_roca_intacta,
            "rango_pp_bar": [PP_MIN_OPERACIONAL, PP_MAX_OPERACIONAL],
            "advertencia_confundimiento": (
                "PP es la ÚNICA variable que el operador manipula, y la manipula EN "
                "RESPUESTA a la roca. Por eso toda curva va estratificada por dominio: "
                "agregar dominios invierte la relación. Estas curvas describen el "
                "desempeño del EQUIPO dentro de una roca dada, no la roca."),
            "terminologia": TERMINOLOGIA_C}


def pp_prescription(dominio: str, objetivo: str = "rop") -> Dict:
    """
    (Sesión 7) Modelo de PRESCRIPCIÓN: qué PP conviene en un dominio dado.

    Aquí PP es variable de DECISIÓN, no covariable de contexto — al revés que
    en el modelo de caracterización, que sigue usándola como contexto en
    ML_FEATURES y no se toca desde acá.

    `objetivo`: "rop" maximiza avance; "estabilidad" minimiza CV(SE), que es
    la dispersión de la energía específica y delata al equipo trabajando
    inestable.

    Sin datos del dominio NO recomienda nada: una recomendación de PP sin
    respaldo histórico es peor que ninguna.
    """
    rep = pp_response_curves()
    if rep["status"] != "ok" or dominio not in rep.get("dominios", {}):
        return {"status": "sin_datos", "dominio": dominio, "pp_recomendada": None,
                "rol_de_pp": "variable de decisión",
                "motivo": (f"No hay curva de respuesta para «{dominio}»: se necesitan "
                           f"al menos dos bins de PP con {PP_MIN_PUNTOS_BIN} puntos "
                           f"cada uno en roca intacta de ese dominio. Sin casos "
                           f"históricos comparables NO se recomienda un PP."),
                "terminologia": TERMINOLOGIA_C}
    d = rep["dominios"][dominio]
    curva = d["curva"]
    if objetivo == "estabilidad":
        cands = [c for c in curva if c["cv_se"] is not None]
        if not cands:
            return {"status": "sin_datos", "dominio": dominio, "pp_recomendada": None,
                    "rol_de_pp": "variable de decisión",
                    "motivo": "No hay CV(SE) calculable en la curva.",
                    "terminologia": TERMINOLOGIA_C}
        mejor = min(cands, key=lambda c: c["cv_se"])
        obj_txt = "minimizar CV(SE): el equipo trabaja más estable"
    else:
        # Con saturación, el PP recomendado es el de saturación: más allá es
        # desgaste sin ganancia de avance.
        mejor = (next((c for c in curva if c["pp"] == d["pp_saturacion"]), None)
                 if d["pp_saturacion"] is not None else None)
        if mejor is None:
            mejor = max(curva, key=lambda c: c["rop_mediana"])
        obj_txt = "maximizar ROP sin pasar el punto de saturación"
    pp = float(np.clip(mejor["pp"], PP_MIN_OPERACIONAL, PP_MAX_OPERACIONAL))
    return {"status": "ok", "dominio": dominio, "pp_recomendada": pp,
            "objetivo": obj_txt, "rol_de_pp": "variable de decisión",
            "rop_esperada": mejor["rop_mediana"], "cv_se_esperado": mejor["cv_se"],
            "n_respaldo": mejor["n"], "pp_saturacion": d["pp_saturacion"],
            "nota": ("Prescripción basada en el desempeño histórico del EQUIPO dentro "
                     "de este dominio. No dice nada sobre la roca: para eso está el "
                     "modelo de caracterización, donde PP es covariable de contexto."),
            "terminologia": TERMINOLOGIA_C}


def contact_anticipation(dominio: Optional[str] = None) -> Dict:
    """
    (Sesión 7) Función de anticipación: cuántos metros antes del contacto
    previsto conviene bajar PP.

    El margen operacional NO se inventa: sale del desfase δ medido en C.5
    entre los contactos que predice la malla y la firma detectada por el MWD.
    Si ese desfase no es sistemático —o no hay con qué medirlo— se ADVIERTE
    sin recomendar.
    """
    c5 = contact_offset_report()
    if c5.get("status") != "ok":
        return {"status": "sin_datos", "margen_m": None,
                "fuente_margen": "desfase δ de contactos (C.5)",
                "motivo": ("No hay desfase de contactos medido: "
                           + str(c5.get("motivo", "sin datos"))
                           + " Sin ese margen NO se recomienda anticipar el cambio de "
                             "PP; hacerlo sería inventar una distancia operacional."),
                "terminologia": TERMINOLOGIA_C}
    if not c5.get("sistematico"):
        return {"status": "sin_datos", "margen_m": None,
                "fuente_margen": "desfase δ de contactos (C.5)",
                "motivo": (f"El desfase medido (media {c5['media']:+.2f} m, desviación "
                           f"{c5['desviacion']:.2f} m) es simétrico alrededor de cero: "
                           f"es ruido de interpolación, no un desplazamiento de la "
                           f"malla. ADVERTENCIA sin recomendación: no hay margen "
                           f"sistemático que anticipar."),
                "terminologia": TERMINOLOGIA_C}
    margen = c5["margen_operacional_m"]
    pres = pp_prescription(dominio) if dominio else None
    return {"status": "ok", "margen_m": margen,
            "fuente_margen": "desfase δ de contactos (C.5)",
            "sesgo_delta_m": c5["media"], "desviacion_delta_m": c5["desviacion"],
            "dominio": dominio,
            "pp_sugerida_tras_el_contacto": (pres or {}).get("pp_recomendada"),
            "recomendacion": (
                f"El desfase entre el contacto que predice la malla y la firma del MWD "
                f"es sistemático ({c5['media']:+.2f} ± {c5['desviacion']:.2f} m): "
                f"conviene anticipar el cambio de PP {margen:.1f} m antes del contacto "
                f"previsto."
                + (f" PP sugerida en el dominio de destino «{dominio}»: "
                   f"{pres['pp_recomendada']:g} bar." if pres and pres.get("pp_recomendada")
                   else " No hay PP respaldada para el dominio de destino.")),
            "terminologia": TERMINOLOGIA_C}


def export_pp_curves_csv(rep: Optional[Dict] = None) -> str:
    """Curvas de respuesta a PP como CSV, con las advertencias arriba."""
    rep = rep if rep is not None else pp_response_curves()
    if rep.get("status") != "ok":
        return f"# {rep.get('motivo', 'sin datos')}\n"
    filas = []
    for dom, d in rep["dominios"].items():
        for c in d["curva"]:
            filas.append({"dominio": dom, "pp_bar": c["pp"], "n": c["n"],
                          "rop_mediana": c["rop_mediana"], "se_mediana": c["se_mediana"],
                          "cv_se": c["cv_se"], "pp_saturacion": d["pp_saturacion"]})
    cab = "\n".join("# " + l for l in [
        "Curvas de respuesta a PP por dominio (roca intacta).",
        rep["advertencia_confundimiento"],
        "PP es variable de DECISIÓN aquí; en el modelo de caracterización es "
        "covariable de contexto. Son modelos distintos.",
        f"generado: {time.strftime('%Y-%m-%d %H:%M')}"])
    return cab + "\n" + pd.DataFrame(filas).to_csv(index=False)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  SESIÓN 8 — DISCRIMINADOR FRACTURA / CONTACTO  ·  RQD_MWD               ║
# ║                                                                          ║
# ║  NO es un DI nuevo. El DI ya dice DÓNDE hay una discontinuidad; esto    ║
# ║  clasifica QUÉ es cada pico que el DI encontró. El DI sigue siendo la   ║
# ║  variable de trabajo del resto del pipeline y aquí no se toca.          ║
# ║                                                                          ║
# ║  Firmas físicas, definidas por el autor:                                ║
# ║    · ZONA FRACTURADA: el dámper CAE, la percusión cae, la velocidad     ║
# ║      aumenta. La broca entra en vacío — no hay macizo que amortiguar    ║
# ║      ni contra el cual percutir, y el avance se dispara.                ║
# ║    · CONTACTO: el dámper NO CAE, la percusión se DESESTABILIZA (sube o  ║
# ║      baja, con varianza no esperada), la rotación varía fuerte, la      ║
# ║      velocidad pierde su patrón. Hay roca a ambos lados: lo que cambia  ║
# ║      es cuál.                                                            ║
# ║                                                                          ║
# ║  Lo que no cumple ninguna de las dos firmas queda INDETERMINADO. No hay ║
# ║  default silencioso.                                                     ║
# ╚══════════════════════════════════════════════════════════════════════════╝

# Media ventana del evento: el tramo alrededor del pico donde se mide la
# firma. 0,30 m ≈ 15 registros al paso de 2 cm del MWD real.
DISC_VENTANA_M = 0.30
# Tramo de referencia inmediatamente ANTES del evento, contra el cual se mide
# si algo "cae" o "se desestabiliza". No es un promedio del pozo entero: la
# roca cambia a lo largo del pozo y una referencia global diluiría la firma.
DISC_BASE_M = 1.00
# Caída relativa que cuenta como "cae". Por debajo de esto la variable se
# considera estable — es el mismo umbral que decide que el dámper NO cae.
DISC_CAIDA_REL = 0.10
# Subida relativa de velocidad que cuenta como "aumenta".
DISC_SUBIDA_VEL_REL = 0.10
# "Varianza no esperada": el coeficiente de variación dentro del evento supera
# este factor por el de la referencia.
DISC_VAR_FACTOR = 1.5
# Radio de apareo pico↔etiqueta de sondaje. Los sondajes de exploración y los
# tiros de producción son perforaciones distintas: la etiqueta nunca cae en el
# mismo punto, y más allá de este radio la correspondencia deja de ser creíble.
DISC_RADIO_ETIQUETA_M = 3.0

DISC_CLASES = ("fractura", "contacto", "indeterminado")


def _tramo_stats(pts, campo: str) -> Optional[Tuple[float, float]]:
    """Media y coeficiente de variación de `campo` sobre una lista de puntos."""
    v = np.array([getattr(p, campo) for p in pts], dtype=np.float64)
    v = v[np.isfinite(v)]
    if v.size < 3:
        return None
    m = float(v.mean())
    if abs(m) < 1e-9:
        return None
    return m, float(v.std() / abs(m))


def peak_signature(well, largo: float, ventana_m: Optional[float] = None,
                   base_m: Optional[float] = None) -> Optional[Dict]:
    """
    (8.1) Firma física del evento centrado en `largo`: cuánto cambia cada
    variable dentro del evento respecto del tramo de roca inmediatamente
    anterior, y cuánto se desestabiliza.

    Devuelve None si el evento o su referencia no tienen puntos suficientes
    —cerca del collar, típicamente—. None es "no evaluable", no "sin firma":
    el llamador lo distingue y lo declara.
    """
    ventana_m = get_param("disc.ventana_m") if ventana_m is None else ventana_m
    base_m = get_param("disc.base_m") if base_m is None else base_m
    pts = sorted(well.points, key=lambda p: p.largo)
    ev = [p for p in pts if abs(p.largo - largo) <= ventana_m]
    base = [p for p in pts
            if largo - ventana_m - base_m <= p.largo < largo - ventana_m]
    if len(ev) < 3 or len(base) < 3:
        return None
    firma = {"n_evento": len(ev), "n_base": len(base),
             "ventana_m": ventana_m, "base_m": base_m}
    for var, campo in (("pd", "pd"), ("pp", "pp"), ("pr", "pr"), ("vel", "vel")):
        se_ev = _tramo_stats(ev, campo)
        se_ba = _tramo_stats(base, campo)
        if se_ev is None or se_ba is None:
            return None
        m_ev, cv_ev = se_ev
        m_ba, cv_ba = se_ba
        firma[f"delta_{var}_rel"] = round((m_ev - m_ba) / abs(m_ba), 4)
        firma[f"cv_{var}_rel"] = round(cv_ev / cv_ba, 4) if cv_ba > 1e-9 else None
    return firma


def classify_peak_signature(firma: Optional[Dict]) -> Dict:
    """
    (8.2) Aplica las dos firmas físicas. Cada condición cumplida deja su
    evidencia en palabras: la clase nunca sale sin el porqué.

    Cuando las dos firmas empatan, o cuando ninguna reúne evidencia
    suficiente, el resultado es "indeterminado" con el motivo. Un pico sin
    firma clara es información — no un caso a rellenar con la clase más
    frecuente.
    """
    if firma is None:
        return {"clase": "indeterminado", "evidencia": [],
                "motivo": ("Evento no evaluable: no hay puntos suficientes en el "
                           "evento o en su tramo de referencia (típico cerca del "
                           "collar)."),
                "score_fractura": None, "score_contacto": None}

    d_pd = firma["delta_pd_rel"]; d_pp = firma["delta_pp_rel"]
    d_vel = firma["delta_vel_rel"]
    cv_pp = firma.get("cv_pp_rel"); cv_pr = firma.get("cv_pr_rel")
    cv_vel = firma.get("cv_vel_rel")

    ev_f, ev_c = [], []
    if d_pd <= -DISC_CAIDA_REL:
        ev_f.append(f"el dámper cae {abs(d_pd)*100:.0f}%")
    if d_pp <= -DISC_CAIDA_REL:
        ev_f.append(f"la percusión cae {abs(d_pp)*100:.0f}%")
    if d_vel >= DISC_SUBIDA_VEL_REL:
        ev_f.append(f"la velocidad aumenta {d_vel*100:.0f}%")

    if abs(d_pd) < DISC_CAIDA_REL:
        ev_c.append(f"el dámper no cae (Δ {d_pd*100:+.0f}%)")
    if cv_pp is not None and cv_pp > DISC_VAR_FACTOR:
        ev_c.append(f"la percusión se desestabiliza (CV ×{cv_pp:.1f})")
    if cv_pr is not None and cv_pr > DISC_VAR_FACTOR:
        ev_c.append(f"la rotación varía fuerte (CV ×{cv_pr:.1f})")
    if cv_vel is not None and cv_vel > DISC_VAR_FACTOR:
        ev_c.append(f"la velocidad pierde su patrón (CV ×{cv_vel:.1f})")

    sf, sc = len(ev_f), len(ev_c)
    # La caída del dámper es la condición que separa las dos firmas: sin ella
    # no hay fractura, y con ella el "no cae" del contacto es imposible.
    fractura_viable = d_pd <= -DISC_CAIDA_REL and sf >= 2
    contacto_viable = abs(d_pd) < DISC_CAIDA_REL and sc >= 3

    if fractura_viable and not contacto_viable:
        clase, motivo = "fractura", None
    elif contacto_viable and not fractura_viable:
        clase, motivo = "contacto", None
    elif fractura_viable and contacto_viable:
        clase = "indeterminado"
        motivo = ("Las dos firmas reúnen evidencia a la vez, que físicamente no "
                  "puede pasar: revisar el evento antes de usarlo.")
    else:
        faltan = []
        if d_pd > -DISC_CAIDA_REL:
            faltan.append("el dámper no cae lo suficiente para ser fractura")
        if abs(d_pd) >= DISC_CAIDA_REL:
            faltan.append("el dámper se mueve demasiado para ser contacto")
        if sf < 2 and d_pd <= -DISC_CAIDA_REL:
            faltan.append("la firma de fractura solo reúne una condición")
        if sc < 3 and abs(d_pd) < DISC_CAIDA_REL:
            faltan.append(f"la firma de contacto solo reúne {sc} de 4 condiciones")
        clase = "indeterminado"
        motivo = "Sin firma clara: " + "; ".join(faltan) + "."
    return {"clase": clase, "evidencia": ev_f if clase == "fractura" else
            ev_c if clase == "contacto" else (ev_f + ev_c),
            "motivo": motivo, "score_fractura": sf, "score_contacto": sc}


def discriminate_peaks(well, min_gap_m: float = 0.5) -> List[Dict]:
    """
    (8.3) Clasifica cada pico DI del pozo. Reutiliza di_peaks() tal cual: los
    picos son los que el DI ya definió con la ventana y el umbral de la
    convención — esta función no los redefine.
    """
    salida = []
    for largo, coord, di_max in di_peaks(well, min_gap_m=min_gap_m):
        firma = peak_signature(well, largo)
        cls = classify_peak_signature(firma)
        salida.append({
            "pozo": well.well_name, "caseron": getattr(well, "caseron", None),
            "plan_id": getattr(well, "plan_id", None),
            "largo": round(float(largo), 3), "di": round(float(di_max), 3),
            "este": float(coord[0]), "norte": float(coord[1]), "cota": float(coord[2]),
            "clase": cls["clase"], "evidencia": cls["evidencia"],
            "motivo": cls["motivo"], "firma": firma,
            "score_fractura": cls["score_fractura"],
            "score_contacto": cls["score_contacto"],
        })
    return salida


# ─── 8.4b · PICOS QUE SON EL PLANO DEL ABANICO, NO GEOLOGÍA ───────────────────
# UN ABANICO DE TIROS ES UN PLANO. Si los picos del DI se reparten a lo largo
# de los tiros de un mismo abanico, cualquier subconjunto suyo sale "plano" por
# construcción, sin que exista estructura alguna. Con los datos reales de Punta
# del Cobre esto no es teórico: 19 de 31 grupos planares resultaron ser el
# abanico, incluidos los tres mayores —590, 533 y 478 picos—, con 0,5°, 0,0° y
# 0,5° entre su normal y la del abanico.
#
# LA AMBIGÜEDAD DE FONDO, que este criterio respeta en vez de esconder: dentro
# de UN SOLO abanico no se puede distinguir una estructura de su propio plano,
# porque todo lo que hay en el abanico está en el plano del abanico. La
# capacidad de discriminar viene de cruzar VARIOS abanicos.
#
# Un pico marcado NO SE BORRA. Se marca con su motivo y los reportes entregan
# las cifras con y sin él, para que la comparación sea visible.

# Radio de agrupamiento: el burden de la operación. Dos picos más cerca que
# esto son candidatos a pertenecer a la misma superficie.
ABANICO_EPS_M = 2.5
ABANICO_MIN_PICOS = 3
# ¿Son coplanares los TIROS involucrados? Razón entre el tercer y el segundo
# valor singular del ajuste a sus trazados: bajo esto, el conjunto de tiros es
# un plano —o sea, un abanico—.
ABANICO_PLANARIDAD_TIROS = 0.15
# Distancia máxima de un pico al plano de los tiros para considerarlo
# CONTENIDO en él. Es el criterio principal, y es robusto: no exige que el
# grupo de picos sea planar por sí mismo. Un arco de picos casi rectilíneo
# —lo que produce un abanico angosto— no tiene normal bien definida, pero sí
# se puede medir si está dentro del plano del abanico o no.
ABANICO_TOL_PLANO_M = 0.75
# ...pero un abanico REAL no es un plano perfecto: la desviación de
# perforación le da espesor propio, y sobre 35 m de tiro ese espesor son
# metros, no centímetros. Exigir que los picos estén más cerca del plano que
# los propios tiros es exigir un imposible, y deja escapar grupos que sí son
# el abanico. Por eso la tolerancia efectiva es la mayor entre el piso
# absoluto de arriba y el espesor medido del abanico, multiplicado por este
# factor. Se auto-calibra: en otra faena, con otra desviación de perforación,
# el criterio se adapta solo en vez de necesitar un número nuevo.
ABANICO_FACTOR_DISPERSION = 1.0
# Ángulo máximo entre la normal del grupo de picos y la normal del plano de
# los tiros. Criterio SECUNDARIO: solo se aplica cuando el grupo es lo bastante
# planar como para tener normal bien definida.
ABANICO_ANG_MAX_GRAD = 20.0


def _plano_de(P: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float, float]:
    """
    Ajuste de plano por SVD. Devuelve (centro, normal, s3/s2, s2/s1).
    s3/s2 chico = los puntos caen en un plano. s2/s1 chico = caen en una recta,
    que en un solo tiro es el tiro mismo y no informa de nada.
    """
    c = P.mean(axis=0)
    _, S, Vt = np.linalg.svd(P - c, full_matrices=False)
    if S[0] < 1e-12:
        return c, np.array([0.0, 0.0, 1.0]), 1.0, 1.0
    return c, Vt[2], float(S[2] / max(S[1], 1e-12)), float(S[1] / max(S[0], 1e-12))


def marcar_picos_de_abanico(picos: List[Dict], eps_m: Optional[float] = None,
                            min_picos: Optional[int] = None,
                            planaridad_tiros: Optional[float] = None,
                            ang_max_grad: Optional[float] = None,
                            tol_plano_m: Optional[float] = None,
                            factor_dispersion: Optional[float] = None) -> Dict:
    """
    (8.4b) Marca en sitio los picos cuyo agrupamiento se explica por la
    geometría de perforación. Escribe `plano_abanico` y `motivo_abanico` en
    cada pico y devuelve el resumen por grupo.

    Un grupo se atribuye al abanico solo si se cumplen LAS DOS condiciones:
    que los tiros involucrados sean coplanares —o sea, que efectivamente
    formen un abanico— y que el plano de los picos sea ESE mismo plano. Con
    una sola de las dos no alcanza: tiros coplanares pueden estar cortados por
    una estructura transversal real, y un grupo plano entre tiros dispersos es
    justamente lo que buscamos.
    """
    eps_m = get_param("abanico.eps_m") if eps_m is None else eps_m
    min_picos = get_param("abanico.min_picos") if min_picos is None else min_picos
    planaridad_tiros = (get_param("abanico.planaridad_tiros")
                        if planaridad_tiros is None else planaridad_tiros)
    ang_max_grad = (get_param("abanico.ang_max_grad")
                    if ang_max_grad is None else ang_max_grad)
    tol_plano_m = get_param("abanico.tol_plano_m") if tol_plano_m is None else tol_plano_m
    factor_dispersion = (get_param("abanico.factor_dispersion")
                         if factor_dispersion is None else factor_dispersion)
    for p in picos:
        p["plano_abanico"] = False
        p["motivo_abanico"] = None
    if len(picos) < min_picos:
        return {"n_marcados": 0, "n_grupos": 0, "grupos": [],
                "config": {"eps_m": eps_m, "min_picos": min_picos,
                           "planaridad_tiros": planaridad_tiros,
                           "ang_max_grad": ang_max_grad,
                           "tol_plano_m": tol_plano_m,
                           "factor_dispersion": factor_dispersion}}
    X = np.array([[p["este"], p["norte"], p["cota"]] for p in picos],
                 dtype=np.float64)
    etiquetas = DBSCAN(eps=eps_m, min_samples=2).fit_predict(X)
    resumen, n_marcados = [], 0
    for g in sorted(set(etiquetas.tolist())):
        if g < 0:
            continue                      # picos aislados: no forman plano
        idx = np.where(etiquetas == g)[0]
        if len(idx) < min_picos:
            continue
        _, normal, r32, r21 = _plano_de(X[idx])
        pozos = sorted({picos[i]["pozo"] for i in idx})
        if len(pozos) < 2:
            continue    # grupo dentro de un solo tiro: no habla de ninguna superficie
        planes = sorted({picos[i].get("plan_id") for i in idx if picos[i].get("plan_id")})
        # Plano de los TIROS, ajustado a sus trazados y no a los picos.
        trazas = []
        for wn in pozos:
            w = wells.get(wn)
            if not w or not w.points:
                continue
            paso = max(1, len(w.points) // 20)
            trazas.extend((q.este, q.norte, q.cota) for q in w.points[::paso])
        if len(trazas) < 3:
            continue
        T = np.array(trazas)
        centro_ab, normal_ab, r32_ab, _ = _plano_de(T)
        ang = float(np.degrees(np.arccos(
            min(1.0, abs(float(np.dot(normal, normal_ab)))))))
        # ¿Están los picos DENTRO del plano de los tiros? Criterio principal.
        dist = float(np.abs((X[idx] - centro_ab) @ normal_ab).max())
        # Espesor propio del abanico: cuánto se apartan del plano los mismos
        # tiros que lo definen. Es la vara con la que hay que medir a los picos.
        disp_tiros = float(np.percentile(np.abs((T - centro_ab) @ normal_ab), 95))
        tol_efectiva = max(tol_plano_m, factor_dispersion * disp_tiros)
        # El grupo solo tiene normal utilizable si es planar y no degenerado en
        # una recta; si no la tiene, el criterio angular no se aplica.
        normal_util = (r32 < 0.25) and (r21 >= 0.15)
        es_abanico = (r32_ab < planaridad_tiros) and (dist <= tol_efectiva) \
            and (ang <= ang_max_grad if normal_util else True)
        if es_abanico:
            motivo = (f"Grupo de {len(idx)} pico(s) en {len(pozos)} tiro(s) "
                      f"coplanares (planaridad {r32_ab:.3f}); los picos caen a "
                      f"{dist:.2f} m o menos del plano del abanico, dentro de "
                      f"la tolerancia de {tol_efectiva:.2f} m que fija el "
                      f"espesor propio del abanico ({disp_tiros:.2f} m)"
                      + (f" y su propio plano forma {ang:.1f}° con él"
                         if normal_util else " (grupo sin normal utilizable)")
                      + ". Es la geometría de perforación, no una superficie "
                        "geológica.")
            for i in idx:
                picos[i]["plano_abanico"] = True
                picos[i]["motivo_abanico"] = motivo
            n_marcados += len(idx)
        resumen.append({"n_picos": int(len(idx)), "n_pozos": len(pozos),
                        "n_abanicos": len(planes),
                        "planaridad_picos": round(r32, 4),
                        "planaridad_tiros": round(r32_ab, 4),
                        "angulo_con_abanico_grad": round(ang, 2),
                        "normal_utilizable": bool(normal_util),
                        "dist_al_plano_m": round(dist, 3),
                        "espesor_abanico_m": round(disp_tiros, 3),
                        "tolerancia_efectiva_m": round(tol_efectiva, 3),
                        "es_abanico": bool(es_abanico)})
    return {"n_marcados": n_marcados, "n_grupos": len(resumen), "grupos": resumen,
            "config": {"eps_m": eps_m, "min_picos": min_picos,
                       "planaridad_tiros": planaridad_tiros,
                       "ang_max_grad": ang_max_grad, "tol_plano_m": tol_plano_m,
                       "factor_dispersion": factor_dispersion},
            "criterio": ("Un grupo se atribuye al abanico solo si los tiros "
                         "involucrados son coplanares Y el plano de los picos "
                         "es ese mismo plano. Dentro de un solo abanico la "
                         "estructura y el plano del abanico son indistinguibles: "
                         "discriminar exige cruzar varios abanicos.")}


def discriminate_all(min_gap_m: float = 0.5,
                     eps_m: Optional[float] = None,
                     min_picos: Optional[int] = None,
                     planaridad_tiros: Optional[float] = None,
                     ang_max_grad: Optional[float] = None,
                     tol_plano_m: Optional[float] = None,
                     factor_dispersion: Optional[float] = None) -> Dict:
    """(8.4) Discriminación sobre todos los pozos cargados, con sus conteos."""
    picos, por_pozo = [], {}
    for wn, w in wells.items():
        pk = discriminate_peaks(w, min_gap_m=min_gap_m)
        if not pk:
            continue
        picos.extend(pk)
        c = {k: 0 for k in DISC_CLASES}
        for p in pk:
            c[p["clase"]] += 1
        por_pozo[wn] = c
    if not picos:
        return {"status": "sin_datos",
                "motivo": ("Ningún pozo tiene picos de DI sobre el umbral "
                           f"{di_threshold:g}: no hay eventos que clasificar."),
                "conteo": {k: 0 for k in DISC_CLASES}}
    abanico = marcar_picos_de_abanico(
        picos, eps_m=eps_m, min_picos=min_picos,
        planaridad_tiros=planaridad_tiros, ang_max_grad=ang_max_grad,
        tol_plano_m=tol_plano_m, factor_dispersion=factor_dispersion)
    conteo = {k: 0 for k in DISC_CLASES}
    conteo_sin_ab = {k: 0 for k in DISC_CLASES}
    for p in picos:
        conteo[p["clase"]] += 1
        if not p["plano_abanico"]:
            conteo_sin_ab[p["clase"]] += 1
    return {"status": "ok", "picos": picos, "por_pozo": por_pozo,
            "conteo": conteo, "n_picos": len(picos),
            "n_plano_abanico": abanico["n_marcados"],
            "conteo_sin_abanico": conteo_sin_ab,
            "abanico": abanico,
            "config": {"ventana_m": DISC_VENTANA_M, "base_m": DISC_BASE_M,
                       "caida_rel": DISC_CAIDA_REL, "var_factor": DISC_VAR_FACTOR,
                       "di_umbral": di_threshold}}


# ─── 8.5 · ETIQUETAS DE CONTRASTE DESDE LOS SONDAJES ──────────────────────────
# Fractura ← estructuras LOGUEADAS por el geólogo en la tabla de estructuras.
# Contacto ← contactos DERIVADOS de los límites de la tabla de litología, que
# genera P2 (derive_contacts) y marca con tipo="contacto_derivado". La
# distinción de procedencia se mantiene: una es observación directa y la otra
# es una derivación, y no pesan igual.

def _drillhole_discontinuities() -> List[Dict]:
    """Discontinuidades de sondaje con su punto UTM, ya etiquetadas por clase."""
    out = []
    for hid, dh in drillholes.items():
        if not dh.trace:
            continue
        for s in dh.structures:
            d = s.get("from")
            if d is None:
                continue
            tipo = s.get("tipo")
            clase = "contacto" if tipo == "contacto_derivado" else "fractura"
            e, n, z = trace_interp(dh.trace, float(d))
            if not np.isfinite(e):
                continue
            out.append({"sondaje": hid, "prof": float(d), "clase": clase,
                        "procedencia": ("contacto derivado de la tabla de litología"
                                        if clase == "contacto" else
                                        "estructura logueada por el geólogo"),
                        "codigo": s.get("codigo"),
                        "pt": np.array([e, n, z], dtype=np.float64)})
    return out


def label_peaks_from_drillholes(radio_m: Optional[float] = None,
                                min_gap_m: float = 0.5) -> Dict:
    """
    (8.5) Aparea cada pico clasificado con la discontinuidad de sondaje más
    cercana dentro de `radio_m`. Los picos sin etiqueta cercana NO se
    descartan en silencio: se cuentan y se reportan como cobertura.
    """
    radio_m = get_param("disc.radio_etiqueta_m") if radio_m is None else radio_m
    etiquetas = _drillhole_discontinuities()
    disc = discriminate_all(min_gap_m=min_gap_m)
    if disc["status"] != "ok":
        return {"status": "sin_picos", "motivo": disc.get("motivo"),
                "n_etiquetas": len(etiquetas)}
    if not etiquetas:
        return {"status": "sin_etiquetas",
                "motivo": ("No hay discontinuidades de sondaje cargadas: sin "
                           "estructuras logueadas ni contactos derivados no hay "
                           "contra qué contrastar."),
                "n_picos": disc["n_picos"], "n_etiquetas": 0}
    P = np.array([e["pt"] for e in etiquetas])
    pares, sin_etq = [], 0
    for pk in disc["picos"]:
        q = np.array([pk["este"], pk["norte"], pk["cota"]], dtype=np.float64)
        d = np.linalg.norm(P - q, axis=1)
        i = int(np.argmin(d))
        if d[i] > radio_m:
            sin_etq += 1
            continue
        pares.append({**{k: pk[k] for k in ("pozo", "largo", "di", "clase",
                                            "evidencia", "motivo")},
                      "plano_abanico": bool(pk.get("plano_abanico")),
                      "etiqueta": etiquetas[i]["clase"],
                      "sondaje": etiquetas[i]["sondaje"],
                      "procedencia_etiqueta": etiquetas[i]["procedencia"],
                      "distancia_m": round(float(d[i]), 3)})
    if not pares:
        return {"status": "sin_etiquetas",
                "motivo": (f"Ninguno de los {disc['n_picos']} pico(s) tiene una "
                           f"discontinuidad de sondaje a menos de {radio_m:g} m. "
                           "Los sondajes de exploración y los tiros de producción "
                           "no están en el mismo lugar: sin cercanía la "
                           "correspondencia no es creíble."),
                "n_picos": disc["n_picos"], "n_etiquetas": len(etiquetas),
                "picos_sin_etiqueta": sin_etq}
    return {"status": "ok", "pares": pares, "radio_m": radio_m,
            "n_picos": disc["n_picos"], "n_etiquetas": len(etiquetas),
            "picos_sin_etiqueta": sin_etq, "conteo_clases": disc["conteo"],
            "n_plano_abanico": disc.get("n_plano_abanico", 0)}


def _matriz_discriminador(pares: List[Dict], radio_m: float,
                          picos_sin_etiqueta: int) -> Dict:
    """
    (8.6a) Matriz de confusión y veredicto sobre una lista de pares
    pico↔etiqueta. Se extrae aparte porque el reporte la calcula DOS veces:
    con todos los picos y descontando los que son plano de abanico.
    """
    etq = ("fractura", "contacto")
    matriz = {e: {c: 0 for c in DISC_CLASES} for e in etq}
    for p in pares:
        if p["etiqueta"] in matriz:
            matriz[p["etiqueta"]][p["clase"]] += 1
    aciertos = sum(matriz[e][e] for e in etq)
    evaluables = sum(matriz[e][c] for e in etq for c in ("fractura", "contacto"))
    indet = sum(matriz[e]["indeterminado"] for e in etq)
    por_clase = {}
    for e in etq:
        n_e = sum(matriz[e].values())
        por_clase[e] = {"n": n_e,
                        "acierto": round(matriz[e][e] / n_e, 4) if n_e else None,
                        "indeterminados": matriz[e]["indeterminado"]}
    # Veredicto contra el azar. Con dos clases, acertar la mitad no es acertar:
    # es el resultado de tirar una moneda, y decirlo es parte del reporte.
    tasa = aciertos / evaluables if evaluables else None
    base = 0.5
    if evaluables < 30:
        veredicto = (f"NO CONCLUYENTE: solo {evaluables} evento(s) con clase "
                     "definida y etiqueta cercana. Sin muestra no hay veredicto.")
    elif tasa is not None and tasa <= base + 0.05:
        veredicto = (f"NO DISCRIMINA: {tasa*100:.1f}% de acierto sobre "
                     f"{evaluables} evento(s), contra el {base*100:.0f}% que da "
                     "elegir al azar entre dos clases. Las firmas físicas, tal "
                     "como están definidas, no separan fractura de contacto en "
                     "estos datos.")
    elif tasa is not None and tasa < 0.70:
        veredicto = (f"DISCRIMINA DÉBILMENTE: {tasa*100:.1f}% sobre {evaluables} "
                     f"evento(s), por encima del {base*100:.0f}% del azar pero "
                     "lejos de un criterio operacional.")
    else:
        veredicto = (f"DISCRIMINA: {tasa*100:.1f}% de acierto sobre {evaluables} "
                     "evento(s) con clase definida.")
    interp = (
        f"{aciertos} de {evaluables} evento(s) con clase definida coinciden con la "
        f"etiqueta de sondaje; {indet} quedaron indeterminados y no cuentan ni a "
        f"favor ni en contra. {veredicto} "
        + (f"{picos_sin_etiqueta} pico(s) del MWD no tienen ninguna "
           f"discontinuidad de sondaje a menos de {radio_m:g} m: el contraste "
           "mide solo la vecindad de los sondajes, no el caserón entero."
           if picos_sin_etiqueta else
           "Todos los picos del MWD encontraron etiqueta cercana.")
        + (f" ATENCIÓN: con radio {radio_m:g} m la etiqueta puede provenir de un "
           "volumen de roca distinto del que perforó el tiro; ampliar el radio "
           "sube el número de pares a costa de la credibilidad de cada uno."
           if radio_m > 5.0 else ""))
    return {"matriz": matriz, "por_clase": por_clase, "aciertos": aciertos,
            "n_evaluables": evaluables,
            "tasa_acierto": round(tasa, 4) if tasa is not None else None,
            "tasa_azar": base, "veredicto": veredicto,
            "n_indeterminados": indet, "n_pares": len(pares),
            "interpretacion": interp}


def discriminator_report(radio_m: Optional[float] = None,
                         min_gap_m: float = 0.5) -> Dict:
    """
    (8.6) Matriz de confusión del discriminador contra las etiquetas de
    sondaje, con la cobertura declarada: cuántos picos quedaron sin etiqueta y
    con qué radio se apareó. Sin pares no hay matriz — se declara y punto.

    Se entrega DOS veces: con todos los picos, y descontando los que el
    criterio del abanico atribuye a la geometría de perforación. Las dos
    cifras van juntas para que la comparación sea visible; ninguna sustituye
    a la otra en silencio.
    """
    radio_m = get_param("disc.radio_etiqueta_m") if radio_m is None else radio_m
    lab = label_peaks_from_drillholes(radio_m=radio_m, min_gap_m=min_gap_m)
    if lab["status"] != "ok":
        return {"status": lab["status"], "motivo": lab.get("motivo"),
                "matriz": None, "radio_m": radio_m,
                "n_plano_abanico": lab.get("n_plano_abanico", 0),
                "sin_abanico": {"status": lab["status"],
                                "motivo": lab.get("motivo"), "n_pares": 0},
                "cobertura": {"n_picos": lab.get("n_picos"),
                              "n_etiquetas": lab.get("n_etiquetas"),
                              "picos_sin_etiqueta": lab.get("picos_sin_etiqueta")}}
    pares = lab["pares"]
    completo = _matriz_discriminador(pares, radio_m, lab["picos_sin_etiqueta"])

    limpios = [p for p in pares if not p.get("plano_abanico")]
    descartados = len(pares) - len(limpios)
    if limpios:
        sin_ab = _matriz_discriminador(limpios, radio_m, lab["picos_sin_etiqueta"])
        sin_ab["status"] = "ok"
        sin_ab["n_pares_descartados_por_abanico"] = descartados
        d = ((sin_ab["tasa_acierto"] or 0) - (completo["tasa_acierto"] or 0)) \
            if completo["tasa_acierto"] is not None and sin_ab["tasa_acierto"] is not None \
            else None
        sin_ab["delta_tasa_acierto"] = round(d, 4) if d is not None else None
        t_new = sin_ab["tasa_acierto"]
        base = sin_ab["tasa_azar"]
        if d is None:
            cierre = ""
        elif t_new is not None and t_new <= base + 0.05:
            # Pasar de azar a azar no es mejorar. Que el filtro quite ruido real
            # no lo convierte en rescate del discriminador, y decir "mejora" acá
            # sería vender una subida que no cruza ninguna línea.
            cierre = (" Sigue EN EL AZAR: el filtro quita picos que son geometría "
                      "de perforación, pero no rescata al discriminador — el "
                      "problema no era solo el abanico.")
        elif d > 0.02:
            cierre = (" El filtro mejora el contraste y lo saca del azar: parte "
                      "del error venía de picos que son geometría de perforación.")
        else:
            cierre = (" El filtro no cambia el contraste: los picos de abanico no "
                      "eran lo que confundía al discriminador.")
        sin_ab["lectura"] = (
            f"Descontando {descartados} par(es) cuyo pico se atribuye al plano del "
            f"abanico, la tasa de acierto pasa de "
            f"{(completo['tasa_acierto'] or 0)*100:.1f}% a "
            f"{(t_new or 0)*100:.1f}%." + cierre)
    else:
        sin_ab = {"status": "sin_datos", "n_pares": 0,
                  "n_pares_descartados_por_abanico": descartados,
                  "motivo": ("Todos los pares apareados tienen su pico atribuido "
                             "al plano del abanico: sin ellos no queda contraste.")}
    return {"status": "ok", **completo,
            "radio_m": radio_m,
            "n_plano_abanico": lab.get("n_plano_abanico", 0),
            "sin_abanico": sin_ab,
            "cobertura": {"n_picos": lab["n_picos"], "n_etiquetas": lab["n_etiquetas"],
                          "picos_sin_etiqueta": lab["picos_sin_etiqueta"]},
            "procedencias": sorted({p["procedencia_etiqueta"] for p in pares})}


def export_discriminator_csv(rep: Optional[Dict] = None,
                             radio_m: Optional[float] = None) -> str:
    """(8.7) Picos clasificados con su firma, como CSV."""
    disc = discriminate_all()
    if disc["status"] != "ok":
        return f"# {disc.get('motivo', 'sin datos')}\n"
    filas = []
    for p in disc["picos"]:
        f = p["firma"] or {}
        filas.append({"pozo": p["pozo"], "caseron": p["caseron"], "largo_m": p["largo"],
                      "este": p["este"], "norte": p["norte"], "cota": p["cota"],
                      "di": p["di"], "clase": p["clase"],
                      "delta_pd_rel": f.get("delta_pd_rel"),
                      "delta_pp_rel": f.get("delta_pp_rel"),
                      "delta_vel_rel": f.get("delta_vel_rel"),
                      "cv_pp_rel": f.get("cv_pp_rel"), "cv_pr_rel": f.get("cv_pr_rel"),
                      "cv_vel_rel": f.get("cv_vel_rel"),
                      "evidencia": " · ".join(p["evidencia"]),
                      "motivo": p["motivo"] or ""})
    rep = rep if rep is not None else discriminator_report(radio_m=radio_m)
    cab = ["Discriminador fractura/contacto sobre los picos del DI "
           f"(ventana {di_config['window']}, umbral {di_threshold:g}).",
           "Fractura: el dámper cae, la percusión cae, la velocidad aumenta.",
           "Contacto: el dámper NO cae, la percusión se desestabiliza, la rotación "
           "varía fuerte, la velocidad pierde su patrón.",
           "Sin firma clara el evento queda INDETERMINADO; no se le asigna clase.",
           f"conteo: {disc['conteo']}"]
    if rep.get("status") == "ok":
        cab.append(f"contraste contra sondajes: {rep['interpretacion']}")
    else:
        cab.append(f"contraste contra sondajes: {rep.get('motivo')}")
    cab.append(f"generado: {time.strftime('%Y-%m-%d %H:%M')}")
    return "\n".join("# " + l for l in cab) + "\n" + pd.DataFrame(filas).to_csv(index=False)


# ─── 8.8 · RQD_MWD POR DEFINICIÓN DE DEERE ────────────────────────────────────
# Porcentaje del metraje en tramos continuos de 10 cm o más SIN discontinuidad.
# Es la misma definición del RQD de testigo, aplicada al perfil de DI en vez de
# a la caja de sondaje: donde el DI supera el umbral hay discontinuidad, y el
# tramo continuo entre dos de ellas solo suma si alcanza los 10 cm.
#
# Es un indicador AGREGADO por pozo y por caserón, orientado a tronadura. NO
# reemplaza al DI: el DI sigue siendo la variable de trabajo punto a punto en
# todo el resto del pipeline.

RQD_TRAMO_MIN_M = 0.10


def rqd_mwd_well(well) -> Optional[Dict]:
    """
    (8.8) RQD_MWD de un pozo. Devuelve None si el pozo no tiene DI calculado o
    no tiene largo útil — None es "no evaluable", y el agregado lo declara en
    vez de contarlo como cero.
    """
    pts = sorted([p for p in well.points
                  if p.entrenable and p.di is not None and np.isfinite(p.di)],
                 key=lambda p: p.largo)
    if len(pts) < 2:
        return None
    largo_total = pts[-1].largo - pts[0].largo
    if largo_total <= 0:
        return None
    # Un tramo continuo va del primer al último punto SIN discontinuidad de la
    # racha. Un punto aislado entre dos discontinuidades mide cero y por
    # definición de Deere no suma.
    tramos, ini, fin = [], None, None
    for p in pts:
        if p.di > di_threshold:
            if ini is not None:
                tramos.append(fin - ini)
                ini = fin = None
        else:
            if ini is None:
                ini = p.largo
            fin = p.largo
    if ini is not None:
        tramos.append(fin - ini)
    buenos = [t for t in tramos if t >= RQD_TRAMO_MIN_M]
    rqd = 100.0 * sum(buenos) / largo_total
    return {"pozo": well.well_name, "caseron": getattr(well, "caseron", None),
            "rqd_mwd": round(min(rqd, 100.0), 2),
            "largo_m": round(largo_total, 3),
            "n_tramos": len(tramos), "n_tramos_validos": len(buenos),
            "n_tramos_descartados": len(tramos) - len(buenos),
            "metraje_valido_m": round(sum(buenos), 3),
            "tramo_min_m": RQD_TRAMO_MIN_M}


def rqd_mwd_report() -> Dict:
    """
    (8.9) RQD_MWD por pozo y agregado por caserón. El agregado del caserón se
    pondera por metraje, no por pozo: un tiro corto no pesa igual que uno de
    35 m.
    """
    pozos, no_evaluables = [], []
    for wn, w in wells.items():
        r = rqd_mwd_well(w)
        if r is None:
            no_evaluables.append(wn)
        else:
            pozos.append(r)
    if not pozos:
        return {"status": "sin_datos",
                "motivo": ("Ningún pozo tiene DI calculado sobre un largo útil: "
                           "correr compute_di() antes."),
                "pozos": [], "caserones": {}, "no_evaluables": no_evaluables}
    caserones: Dict[str, Dict] = {}
    for r in pozos:
        c = r["caseron"] or "—"
        d = caserones.setdefault(c, {"n_pozos": 0, "largo_m": 0.0, "valido_m": 0.0})
        d["n_pozos"] += 1
        d["largo_m"] += r["largo_m"]
        d["valido_m"] += r["metraje_valido_m"]
    for c, d in caserones.items():
        d["rqd_mwd"] = round(100.0 * d["valido_m"] / d["largo_m"], 2) if d["largo_m"] else None
        d["largo_m"] = round(d["largo_m"], 1)
        d["valido_m"] = round(d["valido_m"], 1)
    return {"status": "ok", "pozos": pozos, "caserones": caserones,
            "no_evaluables": no_evaluables,
            "tramo_min_m": RQD_TRAMO_MIN_M,
            "definicion": ("RQD de Deere: porcentaje del metraje en tramos "
                           f"continuos de {RQD_TRAMO_MIN_M*100:.0f} cm o más sin "
                           "discontinuidad, con la discontinuidad detectada por "
                           f"DI > {di_threshold:g}."),
            "uso": ("Indicador AGREGADO por pozo y por caserón, orientado a "
                    "tronadura. No reemplaza al DI, que sigue siendo la variable "
                    "de trabajo punto a punto en el resto del pipeline.")}


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  PASO 2 — RQD DE SONDAJE PROPAGADO AL MWD, CON SU PROCEDENCIA           ║
# ║                                                                          ║
# ║  La idea es decirle a cada tramo de MWD "tu RQD es este, porque lo dice  ║
# ║  el sondaje que tienes al lado". El problema medido es que el "al lado"  ║
# ║  casi no existe: sobre los tres caserones cargados, la distancia MEDIANA ║
# ║  de un punto MWD al intervalo de RQD más cercano son 26,1 m. Dentro de   ║
# ║  2 m hay 0,4% de los puntos; dentro de 5 m, 4,1%; dentro de 10 m, 14,5%. ║
# ║                                                                          ║
# ║  Por eso los tres campos viajan SIEMPRE juntos: valor, sondaje de origen ║
# ║  y distancia. Una etiqueta traída de 26 m no puede circular como si      ║
# ║  fuera una medición hecha en este mismo punto.                           ║
# ║                                                                          ║
# ║  El RQD propagado NO es predictor del modelo, igual que el RMR. Es la    ║
# ║  vara contra la cual se calibra el DI, y nada más.                       ║
# ╚══════════════════════════════════════════════════════════════════════════╝

RQD_RADIO_MAX_M = 10.0
# Mínimo de puntos MWD que un intervalo de sondaje necesita cerca para que su
# RQD_MWD sea algo más que ruido de dos registros sueltos.
RQD_MIN_PUNTOS_INTERVALO = 30


def _intervalos_rqd_sondaje() -> List[Dict]:
    """Tramos de la tabla geomec con RQD, llevados a UTM por el desurvey."""
    out = []
    for hid, dh in drillholes.items():
        if not dh.trace:
            continue
        for r in dh.geomec:
            if r.get("rqd") is None or r.get("from") is None or r.get("to") is None:
                continue
            a = trace_interp(dh.trace, float(r["from"]))
            b = trace_interp(dh.trace, float(r["to"]))
            if not np.isfinite(a[0]) or not np.isfinite(b[0]):
                continue
            c = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, (a[2] + b[2]) / 2.0)
            out.append({"sondaje": hid, "desde": float(r["from"]),
                        "hasta": float(r["to"]), "rqd": float(r["rqd"]),
                        "largo_m": float(r["to"] - r["from"]),
                        "centro": np.array(c, dtype=np.float64),
                        "a": np.array(a, dtype=np.float64),
                        "b": np.array(b, dtype=np.float64)})
    return out


def propagate_drillhole_rqd(radio_m: Optional[float] = None) -> Dict:
    """
    (2.1) Asigna a cada punto MWD el RQD del intervalo de sondaje más cercano
    dentro de `radio_m`, junto con el sondaje de origen y la distancia.

    Fuera del radio NO se etiqueta: el punto queda con los tres campos en None
    y se cuenta entre los sin etiqueta. Rellenarlo con el intervalo más
    cercano a cualquier distancia sería exactamente el default silencioso que
    el proyecto prohíbe.
    """
    radio_m = get_param("rqd.radio_max_m") if radio_m is None else radio_m
    for w in wells.values():
        for p in w.points:
            p.rqd_sondaje = None
            p.rqd_sondaje_origen = None
            p.rqd_sondaje_dist_m = None
    intervalos = _intervalos_rqd_sondaje()
    if not intervalos:
        return {"status": "sin_datos",
                "motivo": ("Ningún sondaje cargado tiene RQD en su tabla geomec: "
                           "sin esa columna no hay nada que propagar."),
                "n_etiquetados": 0, "n_sin_etiqueta": 0,
                "n_intervalos": 0, "radio_m": radio_m}
    P = np.array([iv["centro"] for iv in intervalos])
    n_etq, n_sin, dists = 0, 0, []
    por_caseron: Dict[str, Dict] = {}
    for wn, w in wells.items():
        cas = getattr(w, "caseron", None) or "—"
        d_cas = por_caseron.setdefault(cas, {"etiquetados": 0, "sin_etiqueta": 0})
        if not w.points:
            continue
        Q = np.array([[p.este, p.norte, p.cota] for p in w.points])
        # (n_puntos, n_intervalos): con centenares de intervalos y miles de
        # puntos por pozo la matriz cabe holgada, y evita un árbol por pozo.
        D = np.linalg.norm(Q[:, None, :] - P[None, :, :], axis=2)
        idx = np.argmin(D, axis=1)
        dmin = D[np.arange(len(Q)), idx]
        for i, p in enumerate(w.points):
            if dmin[i] > radio_m:
                n_sin += 1; d_cas["sin_etiqueta"] += 1; continue
            iv = intervalos[int(idx[i])]
            p.rqd_sondaje = iv["rqd"]
            p.rqd_sondaje_origen = iv["sondaje"]
            p.rqd_sondaje_dist_m = round(float(dmin[i]), 3)
            n_etq += 1; d_cas["etiquetados"] += 1
            dists.append(float(dmin[i]))
    d_arr = np.array(dists) if dists else np.array([])
    return {
        "status": "ok", "n_etiquetados": n_etq, "n_sin_etiqueta": n_sin,
        "n_intervalos": len(intervalos),
        "n_sondajes": len({iv["sondaje"] for iv in intervalos}),
        "radio_m": radio_m,
        "por_caseron": por_caseron,
        "distancia_m": ({"mediana": round(float(np.median(d_arr)), 2),
                         "p90": round(float(np.percentile(d_arr, 90)), 2),
                         "max": round(float(d_arr.max()), 2)} if d_arr.size else None),
        "advertencia": (
            f"El RQD viaja con su sondaje de origen y su distancia. De los "
            f"{n_etq + n_sin} punto(s) MWD, {n_sin} quedaron SIN etiqueta por estar "
            f"a más de {radio_m:g} m de todo intervalo con RQD. Los etiquetados "
            + (f"están a {np.median(d_arr):.1f} m de mediana: "
               if d_arr.size else "")
            + "la etiqueta describe la roca del sondaje, no necesariamente la que "
              "perforó el tiro. Usarla como si fuera una medición en el mismo "
              "punto es el error que la distancia existe para impedir."),
        "no_es_predictor": ("El RQD propagado NO entra al modelo de "
                            "caracterización, igual que el RMR. Es la vara "
                            "contra la que se calibra el DI."),
    }


def rqd_calibration_pairs(radio_m: Optional[float] = None,
                          variante: Optional[str] = None,
                          umbral: Optional[float] = None,
                          min_puntos: Optional[int] = None) -> Dict:
    """
    (2.2) Pares de calibración: por cada intervalo de sondaje con RQD, UN solo
    punto MWD —el más cercano al centro medido— y el RQD_MWD del tramo de ESE
    pozo con el mismo largo del intervalo.

    UNO A UNO, decisión del autor: "asignas el RQD de cada centro medido al
    MWD más cercano, solo a 1, y con esos poquitos que tengan alcance buscamos
    los pesos". Promediar varios pozos vecinos mezclaba roca que el sondaje
    nunca vio y diluía justo la variación que se quiere seguir. Agregar o
    quitar sondajes mejora la calibración; esta primera aproximación ya sirve.

    MISMO SOPORTE. El tramo de MWD que se mide tiene el LARGO DEL INTERVALO,
    centrado en el punto más cercano: comparar el DI puntual —un valor cada
    2 cm— contra el RQD de 1 a 3 m de testigo es comparar cosas distintas.

    `radio_m` deja de ser un radio de vecindad y pasa a ser el ALCANCE máximo:
    si el punto más cercano está más lejos que eso, el intervalo no tiene par.
    """
    radio_m = get_param("rqd.radio_max_m") if radio_m is None else radio_m
    nombre_var = variante or DI_VARIANTE_CONVENCION
    v = di_variantes.get(nombre_var)
    if v is None:
        raise KeyError(f'No existe una variante de DI llamada "{nombre_var}".')
    thr = float(umbral if umbral is not None else v["threshold"])

    intervalos = _intervalos_rqd_sondaje()
    if not intervalos:
        return {"status": "sin_datos", "pares": [],
                "motivo": "Ningún sondaje cargado tiene RQD en su tabla geomec.",
                "variante": nombre_var}

    pts, meta = [], []
    for wn, w in wells.items():
        perfil = w.di_variantes.get(nombre_var) if variante is not None else None
        for i, p in enumerate(w.points):
            if not p.entrenable:
                continue
            if variante is not None:
                if perfil is None or i >= len(perfil) or not np.isfinite(perfil[i]):
                    continue
            elif p.di is None or not np.isfinite(p.di):
                continue
            pts.append((p.este, p.norte, p.cota))
            meta.append((wn, i))
    if not pts:
        return {"status": "sin_datos", "pares": [],
                "motivo": (f'Ningún punto MWD tiene DI calculado para la variante '
                           f'"{nombre_var}".'),
                "variante": nombre_var}
    P = np.array(pts)
    pares, sin_par = [], 0
    for iv in intervalos:
        d = np.linalg.norm(P - iv["centro"], axis=1)
        k = int(np.argmin(d))
        if d[k] > radio_m:
            sin_par += 1; continue
        wn, i = meta[k]
        w = wells[wn]
        largo_centro = w.points[i].largo
        media = max(iv["largo_m"], 0.2) / 2.0
        tramo = _tramo_di_de_pozo(w, nombre_var if variante is not None else None,
                                  largo_centro, media)
        if tramo is None:
            sin_par += 1; continue
        largos, di_vals = tramo
        v_rqd = _rqd_deere_np(largos, di_vals, thr)
        if v_rqd is None:
            sin_par += 1; continue
        pares.append({"sondaje": iv["sondaje"], "desde": iv["desde"],
                      "hasta": iv["hasta"], "rqd_sondaje": iv["rqd"],
                      "rqd_mwd": round(float(v_rqd), 2),
                      "pozo": wn, "largo_mwd_m": round(float(largo_centro), 3),
                      "distancia_m": round(float(d[k]), 3),
                      "n_puntos_mwd": int(largos.size), "n_pozos": 1})
    if not pares:
        return {"status": "sin_soporte", "pares": [], "variante": nombre_var,
                "motivo": (f"Ningún intervalo de sondaje tiene un punto MWD a menos "
                           f"de {radio_m:g} m con tramo suficiente para medir."),
                "n_intervalos": len(intervalos), "intervalos_sin_par": sin_par}
    dist = np.array([p["distancia_m"] for p in pares])
    return {"status": "ok", "pares": pares, "variante": nombre_var,
            "umbral": thr, "radio_m": radio_m,
            "n_intervalos": len(intervalos), "intervalos_sin_par": sin_par,
            "agrupado_por": "sondaje",
            "n_sondajes": len({p["sondaje"] for p in pares}),
            "distancia_m": {"mediana": round(float(np.median(dist)), 2),
                            "p90": round(float(np.percentile(dist, 90)), 2),
                            "max": round(float(dist.max()), 2)},
            "nota_soporte": ("UNO A UNO: cada intervalo de sondaje se aparea con "
                             "el punto MWD más cercano a su centro, y el RQD_MWD "
                             "se mide sobre el tramo de ESE pozo con el mismo "
                             "largo del intervalo."),
            "validacion": ("La unidad de validación es el SONDAJE: dejar-uno-fuera "
                           "por sondaje, no por intervalo. Dos intervalos del mismo "
                           "sondaje no son observaciones independientes.")}


def _tramo_di_de_pozo(well, variante: Optional[str], largo_centro: float,
                      media_m: float):
    """
    (largos, di) del tramo de un pozo centrado en `largo_centro`, de media
    longitud `media_m`, ordenado. None si no alcanza para medir nada.
    """
    perfil = well.di_variantes.get(variante) if variante else None
    largos, valores = [], []
    for i, p in enumerate(well.points):
        if not p.entrenable or abs(p.largo - largo_centro) > media_m:
            continue
        if variante:
            if perfil is None or i >= len(perfil) or not np.isfinite(perfil[i]):
                continue
            valores.append(float(perfil[i]))
        else:
            if p.di is None or not np.isfinite(p.di):
                continue
            valores.append(float(p.di))
        largos.append(p.largo)
    if len(largos) < 2:
        return None
    a = np.array(largos, dtype=np.float64)
    b = np.array(valores, dtype=np.float64)
    o = np.argsort(a)
    return a[o], b[o]


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  PASO 3 — CALIBRAR LOS PESOS DEL DI CONTRA EL RQD DE LOS SONDAJES       ║
# ║                                                                          ║
# ║  EL ENCUADRE, corregido por el autor: Fernández busca los pesos de su    ║
# ║  DI con `movvar` de MATLAB —varianza móvil, la misma construcción que    ║
# ║  usa di_profile()—. Calibrar los pesos NO es una desviación del método:  ║
# ║  ES el método. Los pesos 0,35 / 0,25 / 0,20 / 0,20 son el resultado de   ║
# ║  la calibración de Fernández sobre SUS datos; buscar los de Punta del    ║
# ║  Cobre es aplicar el mismo procedimiento a estos.                        ║
# ║                                                                          ║
# ║  Por eso el resultado es una VARIANTE con nombre propio y la de          ║
# ║  convención queda intacta: son dos resultados legítimos del mismo        ║
# ║  procedimiento sobre datos distintos, y tienen que poder compararse.     ║
# ║                                                                          ║
# ║  LA VALIDACIÓN ES POR SONDAJE. Dos intervalos del mismo sondaje no son   ║
# ║  observaciones independientes: comparten roca, campaña y criterio de     ║
# ║  logueo. Ajustar sobre todos y reportar el ajuste sería reportar         ║
# ║  memorización. El rho de ajuste y el de validación viajan SIEMPRE        ║
# ║  juntos, y el veredicto mira el de validación.                           ║
# ╚══════════════════════════════════════════════════════════════════════════╝

# Búsqueda sobre el símplex de pesos por muestreo de Dirichlet. La métrica es
# una correlación de RANGOS, que no es diferenciable: un optimizador de
# gradiente no sirve, y con cinco pesos el muestreo cubre el espacio de sobra.
CAL_N_MUESTRAS = 400
CAL_SEMILLA = 42
CAL_MIN_SONDAJES = 2
# TODAS las presiones entran como candidatas, incluida la de avance (AP), que
# la convención de Fernández no usa. Decisión del autor: qué presión queda
# fuera lo decide la CALIBRACIÓN, con un peso cercano a cero, no un descarte
# previo. ROP no entra: es una velocidad, no una presión.
CAL_PARAMS = ("pp", "pr", "pd", "pf", "pa")


def _z2_por_param(points, window: int, params) -> Optional[Dict[str, np.ndarray]]:
    """
    El z² de la varianza móvil de cada variable, que es la única parte cara de
    di_profile y NO depende de los pesos:

        DI = sqrt( Σ_k  w_k_normalizado · z_k² )

    Precalcularlo una vez por pozo convierte cada evaluación de pesos en una
    suma ponderada. Sin esto, la búsqueda recalcula el perfil completo por
    cada combinación y la calibración deja de ser practicable.
    """
    half = window // 2
    n = len(points)
    if n < window:
        return None
    out = {}
    for k in params:
        arr = np.array([getattr(p, k) for p in points], dtype=np.float64)
        mv = _moving_variance(arr, half)
        std = mv.std() or 1e-9
        out[k] = ((mv - mv.mean()) / std) ** 2
    return out


def _di_desde_z2(z2: Dict[str, np.ndarray], pesos: Dict[str, float]) -> np.ndarray:
    """DI a partir del z² precalculado. Idéntico a di_profile por construcción."""
    total_w = sum(pesos.get(k, 0.0) for k in z2) or 1.0
    total = None
    for k, z in z2.items():
        aporte = (pesos.get(k, 0.0) / total_w) * z
        total = aporte if total is None else total + aporte
    return np.sqrt(total)


def _rqd_deere_np(largos: np.ndarray, di: np.ndarray, umbral: float) -> Optional[float]:
    """
    Regla de Deere vectorizada sobre arrays YA ORDENADOS por largo. Idéntica a
    _rqd_deere; existe porque la calibración la evalúa cientos de miles de
    veces y construir listas de tuplas y reordenarlas en cada evaluación es lo
    que volvía impracticable el radio grande.
    """
    n = largos.size
    if n < 2:
        return None
    total = float(largos[-1] - largos[0])
    if total <= 0:
        return None
    ok = di <= umbral
    if not ok.any():
        return 0.0
    d = np.diff(ok.astype(np.int8))
    ini = np.flatnonzero(d == 1) + 1
    fin = np.flatnonzero(d == -1)
    if ok[0]:
        ini = np.concatenate(([0], ini))
    if ok[-1]:
        fin = np.concatenate((fin, [n - 1]))
    tramos = largos[fin] - largos[ini]
    buenos = tramos[tramos >= RQD_TRAMO_MIN_M]
    return 100.0 * float(buenos.sum()) / total


def _rho_de_pesos(pesos: Dict[str, float], window: int, umbral: float,
                  pozos_rel: List[str], intervalos: List[Dict],
                  radio_m: float, min_puntos: int,
                  sondajes_filtro: Optional[set] = None,
                  z2_cache: Optional[Dict[str, Dict[str, np.ndarray]]] = None
                  ) -> Tuple[Optional[float], int]:
    """
    rho de Spearman entre el RQD_MWD que producen estos pesos y el RQD de los
    sondajes, sobre los intervalos pedidos. Devuelve (rho, n_pares).

    Solo recalcula el perfil de DI en los pozos que aportan pares: recorrer los
    619 pozos por cada combinación de pesos haría la búsqueda inviable, y los
    demás no cambian ningún par.
    """
    perfiles = {}
    for wn in pozos_rel:
        if z2_cache is not None:
            z2 = z2_cache.get(wn)
            if z2:
                perfiles[wn] = _di_desde_z2(z2, pesos)
            continue
        w = wells.get(wn)
        if w is None or len(w.points) < window:
            continue
        perfil = di_profile(w.points, window, sorted(pesos), pesos)
        if perfil is not None:
            perfiles[wn] = perfil
    if not perfiles:
        return None, 0
    a, b = [], []
    for iv in intervalos:
        if sondajes_filtro is not None and iv["sondaje"] not in sondajes_filtro:
            continue
        valores = []
        for wn, (idxs, largos) in iv["vecinos"].items():
            perfil = perfiles.get(wn)
            if perfil is None or idxs.size < 2:
                continue
            v = _rqd_deere_np(largos, perfil[idxs], umbral)
            if v is not None:
                valores.append(v)
        if not valores:
            continue
        a.append(float(np.mean(valores)))
        b.append(iv["rqd"])
    if len(a) < 5:
        return None, len(a)
    return spearman_rho(a, b), len(a)


def _preparar_intervalos_calibracion(radio_m: float, min_puntos: int):
    """
    Intervalos de RQD con sus vecinos MWD ya indexados por pozo. Se calcula UNA
    vez y se reutiliza en cada evaluación de pesos: es lo que vuelve viable la
    búsqueda.
    """
    intervalos = _intervalos_rqd_sondaje()
    if not intervalos:
        return [], []
    pts, meta = [], []
    for wn, w in wells.items():
        for i, p in enumerate(w.points):
            if p.entrenable:
                pts.append((p.este, p.norte, p.cota)); meta.append((wn, i))
    if not pts:
        return [], []
    P = np.array(pts)
    listos, pozos_rel = [], set()
    for iv in intervalos:
        # UNO A UNO: el punto MWD más cercano al centro medido, y nada más.
        d = np.linalg.norm(P - iv["centro"], axis=1)
        k = int(np.argmin(d))
        if d[k] > radio_m:
            continue
        wn, i = meta[k]
        w = wells[wn]
        largo_centro = w.points[i].largo
        media = max(iv["largo_m"], 0.2) / 2.0
        # Índices y largos del tramo, ordenados UNA vez: dentro de la búsqueda
        # solo cambian los valores de DI, nunca el orden ni la pertenencia.
        idxs = [j for j, p in enumerate(w.points)
                if p.entrenable and abs(p.largo - largo_centro) <= media]
        if len(idxs) < 2:
            continue
        arr = np.array(idxs, dtype=np.int64)
        largos = np.array([w.points[j].largo for j in arr], dtype=np.float64)
        orden = np.argsort(largos)
        listos.append({**iv, "vecinos": {wn: (arr[orden], largos[orden])},
                       "distancia_m": float(d[k])})
        pozos_rel.add(wn)
    return listos, sorted(pozos_rel)


def calibrate_di_weights(radio_m: Optional[float] = None,
                         min_puntos: Optional[int] = None,
                         params: Tuple[str, ...] = CAL_PARAMS,
                         window: Optional[int] = None,
                         umbral: Optional[float] = None,
                         n_muestras: int = CAL_N_MUESTRAS,
                         seed: int = CAL_SEMILLA,
                         nombre_variante: str = "calibrada_RQD",
                         registrar: bool = True) -> Dict:
    """
    (3.1) Busca los pesos del DI que hacen que el RQD_MWD y el RQD de los
    sondajes hablen el mismo idioma, y valida dejando-un-sondaje-fuera.

    El resultado se registra como VARIANTE. La de convención no se toca.
    """
    radio_m = get_param("rqd.radio_max_m") if radio_m is None else radio_m
    min_puntos = (get_param("rqd.min_puntos_intervalo")
                  if min_puntos is None else min_puntos)
    conv = di_variantes.get(DI_VARIANTE_CONVENCION) or {}
    window = int(conv.get("window", 14)) if window is None else int(window)
    umbral = float(conv.get("threshold", 1.5)) if umbral is None else float(umbral)

    intervalos, pozos_rel = _preparar_intervalos_calibracion(radio_m, min_puntos)
    if len(intervalos) < 5:
        return {"status": "sin_datos",
                "motivo": (f"Solo {len(intervalos)} intervalo(s) de sondaje tienen "
                           f"un punto MWD a menos de {radio_m:g} m. Con menos de "
                           "cinco pares no hay correlación que ajustar."),
                "n_intervalos": len(intervalos), "radio_m": radio_m}
    sondajes = sorted({iv["sondaje"] for iv in intervalos})
    if len(sondajes) < CAL_MIN_SONDAJES:
        return {"status": "sin_validacion",
                "motivo": (f"Los pares provienen de {len(sondajes)} sondaje(s). La "
                           "validación es dejando-un-SONDAJE-fuera y necesita al "
                           f"menos {CAL_MIN_SONDAJES}. Con uno solo se puede ajustar "
                           "pero no comprobar nada, y una variante sin validar no "
                           "se registra."),
                "n_sondajes": len(sondajes), "sondajes": sondajes,
                "n_intervalos": len(intervalos), "radio_m": radio_m}

    # El z² de cada variable se calcula UNA vez por pozo: es lo único caro y no
    # depende de los pesos.
    z2_cache = {}
    for wn in pozos_rel:
        w = wells.get(wn)
        if w is None:
            continue
        z2 = _z2_por_param(w.points, window, params)
        if z2 is not None:
            z2_cache[wn] = z2

    rng = np.random.default_rng(seed)
    # Muestreo de Dirichlet sobre el símplex: cubre el espacio de pesos sin
    # privilegiar ninguna esquina. Se incluye la combinación de CONVENCIÓN como
    # candidata, para que el óptimo nunca pueda ser peor que ella por azar.
    cand = [dict(zip(params, rng.dirichlet(np.ones(len(params)))))
            for _ in range(int(n_muestras))]
    pesos_conv = {k: conv.get("weights", {}).get(k, 0.0) for k in params}
    if sum(pesos_conv.values()) > 0:
        tot = sum(pesos_conv.values())
        cand.insert(0, {k: v / tot for k, v in pesos_conv.items()})

    def _mejor(filtro):
        mejor_w, mejor_rho, mejor_n = None, None, 0
        for w in cand:
            rho, n = _rho_de_pesos(w, window, umbral, pozos_rel, intervalos,
                                   radio_m, min_puntos, filtro, z2_cache)
            if rho is None or not np.isfinite(rho):
                continue
            if mejor_rho is None or rho > mejor_rho:
                mejor_w, mejor_rho, mejor_n = w, rho, n
        return mejor_w, mejor_rho, mejor_n

    pesos, rho_ajuste, n_pares = _mejor(None)
    if pesos is None:
        return {"status": "sin_datos",
                "motivo": ("Ninguna combinación de pesos produjo pares suficientes "
                           "para calcular una correlación."),
                "n_intervalos": len(intervalos), "radio_m": radio_m}

    rho_conv, _ = _rho_de_pesos(
        {k: v for k, v in conv.get("weights", {}).items() if k in params} or
        {k: 1.0 / len(params) for k in params},
        window, umbral, pozos_rel, intervalos, radio_m, min_puntos, None, z2_cache)

    # Validación dejando-un-sondaje-fuera: se ajusta sin ese sondaje y se mide
    # SOBRE él. Es la única forma de saber si los pesos describen la roca o
    # memorizaron esta campaña de sondajes.
    pliegues = []
    for s in sondajes:
        resto = set(sondajes) - {s}
        w_fit, rho_fit, _ = _mejor(resto)
        if w_fit is None:
            pliegues.append({"sondaje": s, "rho": None,
                             "motivo": "sin pares al dejar este sondaje fuera"})
            continue
        rho_out, n_out = _rho_de_pesos(w_fit, window, umbral, pozos_rel,
                                       intervalos, radio_m, min_puntos, {s},
                                       z2_cache)
        pliegues.append({"sondaje": s, "rho": rho_out, "n_pares": n_out,
                         "rho_ajuste_pliegue": rho_fit,
                         "pesos_pliegue": {k: round(v, 4) for k, v in w_fit.items()}})
    validos = [p["rho"] for p in pliegues if p.get("rho") is not None
               and np.isfinite(p["rho"])]
    rho_val = float(np.mean(validos)) if validos else None

    if rho_val is None:
        veredicto = ("NO VALIDABLE: ningún pliegue dejando-un-sondaje-fuera produjo "
                     "pares suficientes para medir. El ajuste existe pero no hay "
                     "con qué comprobarlo.")
    elif rho_val <= 0.1:
        veredicto = (f"NO GENERALIZA: rho de ajuste {rho_ajuste:+.3f} contra rho de "
                     f"VALIDACIÓN {rho_val:+.3f}. Los pesos describen los sondajes "
                     "con los que se ajustaron y no transfieren al que se dejó "
                     "fuera. Con esta cantidad de sondajes es el resultado "
                     "esperable, y es un resultado: dice que hacen falta más "
                     "sondajes con RQD, no otros pesos.")
    elif rho_val < 0.4:
        veredicto = (f"GENERALIZA DÉBILMENTE: ajuste {rho_ajuste:+.3f}, validación "
                     f"{rho_val:+.3f}. Hay señal que sobrevive al sondaje dejado "
                     "fuera, pero no alcanza para usar el DI calibrado como "
                     "estimador de RQD.")
    else:
        veredicto = (f"GENERALIZA: ajuste {rho_ajuste:+.3f}, validación "
                     f"{rho_val:+.3f}. Los pesos transfieren al sondaje que no "
                     "participó del ajuste.")

    dists = [iv.get("distancia_m") for iv in intervalos
             if iv.get("distancia_m") is not None]
    fuente = (f"Calibrado contra el RQD de {len(sondajes)} sondaje(s) de {ACTIVE_SITE} "
              f"({n_pares} par(es), uno a uno, alcance {radio_m:g} m"
              + (f", distancia mediana {np.median(dists):.1f} m" if dists else "")
              + f"). Presiones candidatas: {', '.join(params)}. Mismo procedimiento que "
              "Fernández et al. 2023, que busca los pesos de su DI con varianza "
              "móvil (movvar): esta variante es ese procedimiento aplicado a los "
              "datos de este sitio, no una desviación del método. "
              f"rho ajuste {rho_ajuste:+.3f} · rho validación "
              + (f"{rho_val:+.3f}" if rho_val is not None else "no medible")
              + f" (dejando-un-sondaje-fuera, {len(pliegues)} pliegues). "
              f"Semilla {seed}, {len(cand)} combinaciones evaluadas.")

    if registrar:
        if nombre_variante in di_variantes:
            delete_di_variant(nombre_variante)
        create_di_variant(nombre_variante, weights=pesos, window=window,
                          threshold=umbral, fuente=fuente,
                          notas=veredicto)
    return {
        "status": "ok", "pesos": {k: round(v, 4) for k, v in pesos.items()},
        "pesos_convencion": conv.get("weights"),
        "rho_ajuste": round(rho_ajuste, 4) if rho_ajuste is not None else None,
        "rho_convencion": round(rho_conv, 4) if rho_conv is not None else None,
        "rho_validacion": round(rho_val, 4) if rho_val is not None else None,
        "veredicto": veredicto,
        "n_pares": n_pares, "n_intervalos": len(intervalos),
        "n_sondajes": len(sondajes), "sondajes": sondajes,
        "radio_m": radio_m, "min_puntos": min_puntos,
        "params_candidatos": list(params),
        "distancia_mediana_m": (round(float(np.median(dists)), 2) if dists else None),
        "window": window, "umbral": umbral,
        "semilla": seed, "n_combinaciones": len(cand),
        "variante": nombre_variante if registrar else None,
        "validacion": {"unidad": "sondaje", "n_pliegues": len(pliegues),
                       "pliegues": pliegues,
                       "nota": ("Dos intervalos del mismo sondaje no son "
                                "observaciones independientes: comparten roca, "
                                "campaña y criterio de logueo. Por eso el pliegue "
                                "es el sondaje y no el intervalo.")},
        "encuadre": ("Fernández busca los pesos de su DI con movvar; calibrar es "
                     "su método, no una desviación. La variante de convención "
                     "queda intacta para poder comparar."),
    }


def di_quality_indicator(variante: Optional[str] = None,
                         radio_m: Optional[float] = None) -> Dict:
    """
    (8.11) ¿Qué tan bien describe el DI al macizo?

    EL ENCUADRE, del autor: lo único verídico es el TESTIGO. El RQD de sondaje
    no es un instrumento de validación independiente que se pueda contrastar
    por caserón contra un promedio de Excel — es el patrón que AJUSTA los
    pesos para que el MWD calcule RQD con precisión, y es ese cálculo
    extrapolado el que después vale en todo el caserón.

    Así que el indicador no pregunta "¿coinciden dos fuentes?" sino "¿cuánto
    se aparta el RQD que calcula el MWD del que midió el testigo?", en puntos
    de RQD, sobre los pares que existan. Es la vara honesta: si el error
    medio son 12 puntos de RQD, eso es lo que el modelo puede prometer.
    """
    pares = rqd_calibration_pairs(radio_m=radio_m, variante=variante)
    if pares.get("status") != "ok":
        return {"status": pares.get("status"), "motivo": pares.get("motivo"),
                "variante": pares.get("variante")}
    a = np.array([p["rqd_mwd"] for p in pares["pares"]], dtype=np.float64)
    b = np.array([p["rqd_sondaje"] for p in pares["pares"]], dtype=np.float64)
    err = a - b
    rho = spearman_rho(a.tolist(), b.tolist())
    mae = float(np.abs(err).mean())
    rmse = float(np.sqrt((err ** 2).mean()))
    sesgo = float(err.mean())
    n = int(a.size)
    if n < 10:
        veredicto = (f"NO CONCLUYENTE: {n} par(es). Hacen falta más sondajes con "
                     "RQD para poder decir nada del error.")
    elif mae <= 10.0 and rho is not None and rho >= 0.4:
        veredicto = (f"DESCRIBE BIEN: el RQD calculado desde el MWD se aparta "
                     f"{mae:.1f} puntos en promedio del que midió el testigo, y "
                     f"los ordena igual (rho {rho:+.2f}).")
    elif rho is not None and rho >= 0.4:
        veredicto = (f"ORDENA BIEN, MIDE MAL: rho {rho:+.2f} —el DI reconoce "
                     f"dónde la roca está peor— pero se aparta {mae:.1f} puntos "
                     "de RQD en promedio. Sirve para ranquear sectores, no para "
                     "entregar un RQD.")
    else:
        veredicto = (f"NO DESCRIBE: error medio {mae:.1f} puntos de RQD y rho "
                     f"{rho if rho is None else f'{rho:+.2f}'}. Con los pesos "
                     "vigentes el DI no reproduce el RQD del testigo.")
    return {
        "status": "ok", "variante": pares["variante"], "n_pares": n,
        "n_sondajes": pares["n_sondajes"], "radio_m": pares["radio_m"],
        "rho": round(rho, 4) if rho is not None else None,
        "mae_rqd": round(mae, 2), "rmse_rqd": round(rmse, 2),
        "sesgo_rqd": round(sesgo, 2),
        "distancia_m": pares.get("distancia_m"),
        "veredicto": veredicto,
        "encuadre": ("El testigo es el patrón, no un contraste independiente: "
                     "ajusta los pesos para que el MWD calcule RQD, y ese "
                     "cálculo extrapolado es el que vale en el resto del "
                     "caserón. El indicador mide el apartamiento en puntos de "
                     "RQD, que es lo que el modelo puede prometer."),
        "sesgo_lectura": (f"El MWD calcula {abs(sesgo):.1f} puntos de RQD "
                          + ("por encima" if sesgo > 0 else "por debajo")
                          + " del testigo en promedio."),
    }


def export_rqd_mwd_csv(rep: Optional[Dict] = None) -> str:
    """(8.10) RQD_MWD por pozo y por caserón como CSV."""
    rep = rep if rep is not None else rqd_mwd_report()
    if rep.get("status") != "ok":
        return f"# {rep.get('motivo', 'sin datos')}\n"
    filas = [{"nivel": "pozo", "clave": r["pozo"], "caseron": r["caseron"],
              "rqd_mwd": r["rqd_mwd"], "largo_m": r["largo_m"],
              "n_tramos_validos": r["n_tramos_validos"],
              "n_tramos_descartados": r["n_tramos_descartados"]}
             for r in rep["pozos"]]
    for c, d in rep["caserones"].items():
        filas.append({"nivel": "caseron", "clave": c, "caseron": c,
                      "rqd_mwd": d["rqd_mwd"], "largo_m": d["largo_m"],
                      "n_tramos_validos": None, "n_tramos_descartados": None})
    cab = "\n".join("# " + l for l in [
        rep["definicion"], rep["uso"],
        f"pozos no evaluables: {len(rep['no_evaluables'])}",
        f"generado: {time.strftime('%Y-%m-%d %H:%M')}"])
    return cab + "\n" + pd.DataFrame(filas).to_csv(index=False)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  SESIÓN 9 — MODELO DE BLOQUES POR IDW ANISOTRÓPICO                      ║
# ║                                                                          ║
# ║  Es el entregable central del alcance que fijó el autor: una malla de   ║
# ║  puntos con UCS aproximadamente cierto y un valor de discontinuidad     ║
# ║  por sector. Lo demás del pipeline existe para llegar acá.              ║
# ║                                                                          ║
# ║  MÁSCARA DE SOPORTE. Un bloque sin dato cercano queda VACÍO. Nunca      ║
# ║  interpolado desde lejos: un modelo que rellena todo miente justo en    ║
# ║  los bordes, que es donde se planifica la tronadura.                    ║
# ║                                                                          ║
# ║  ANISOTROPÍA. El yacimiento es estratiforme: la litología continúa      ║
# ║  lateralmente y cambia con la cota. La búsqueda es más larga en         ║
# ║  horizontal que en vertical. Es la misma física por la que la cota está ║
# ║  prohibida como predictora — acá entra como GEOMETRÍA de interpolación, ║
# ║  no como variable del modelo.                                           ║
# ║                                                                          ║
# ║  CONFIANZA. Incorpora la calidad de la etiqueta reutilizando            ║
# ║  pi_factor() del registro de atributos: un dominio anclado en un ensayo ║
# ║  del sitio y otro anclado en literatura NO pueden salir con la misma    ║
# ║  confianza, y el registro ya codifica esa jerarquía.                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝

# Bloque de 2,5 m: coherente con el burden y el espaciamiento de la operación.
# No es una resolución elegida por comodidad numérica — un bloque más fino que
# la malla de perforación promete un detalle que el dato no tiene.
BLOQUE_M = 2.5
IDW_POTENCIA = 2.0
# Radios de búsqueda. El horizontal cubre tres bloques; el vertical, uno. La
# asimetría ES el modelo geológico: estratiforme.
IDW_RADIO_H_M = 7.5
IDW_RADIO_V_M = 2.5
# Factores de la métrica anisotrópica (X=Este, Y=Norte, Z=Cota). Un metro de
# separación vertical cuenta como tres metros de separación horizontal.
IDW_ANISOTROPIA = (1.0, 1.0, 3.0)
IDW_MIN_MUESTRAS = 3
# Holgura alrededor del espacio EFECTIVAMENTE PERFORADO. El modelo existe para
# la tronadura que viene, así que su dominio es el volumen de los tiros; la
# holgura la extiende lo justo para que sirva de soporte a dilución,
# estabilidad y fortificación, sin inventar macizo lejos del dato.
#
# No es lo mismo que el radio de búsqueda: dentro de la holgura un bloque
# PUEDE quedar vacío por falta de muestras cercanas, y eso se cuenta. Fuera de
# la holgura el bloque no es "vacío", simplemente NO PERTENECE al modelo, y
# contarlo hundía la cobertura a cifras sin significado — un caserón cuyos
# pozos se reparten en 900 m tiene un encajonado casi todo aire.
HOLGURA_MODELO_M = 15.0
# Para no interpolar desde un solo pozo cuando hay muchos puntos alineados: el
# soporte se cuenta por POZOS distintos, no por registros MWD.
IDW_MIN_POZOS = 1

BLOQUE_LAYER_PREFIX = "MB_UCS_"

# Bandas de resistencia de la clasificación ISRM (Brown 1981, tabla de
# resistencia de la roca intacta). Criterio TRAZABLE — nunca percentiles de la
# propia muestra, que es exactamente lo que el proyecto prohíbe. R0 y R1 se
# agrupan porque por debajo de 5 MPa el MWD de un equipo de producción no
# distingue: el pozo se derrumba antes.
BANDAS_RESISTENCIA = (
    (0.0, 5.0, "R0_R1_muy_baja"),
    (5.0, 25.0, "R2_baja"),
    (25.0, 50.0, "R3_media"),
    (50.0, 100.0, "R4_alta"),
    (100.0, 250.0, "R5_muy_alta"),
    (250.0, 450.0, "R6_extrema"),
)
BANDAS_RESISTENCIA_FUENTE = ("Clasificación ISRM de resistencia de la roca "
                             "intacta (Brown, 1981). Criterio trazable, no "
                             "percentiles de la muestra.")


def banda_resistencia(ucs: Optional[float]) -> Optional[str]:
    """Banda ISRM de un UCS. None fuera de los límites físicos: no se inventa."""
    if ucs is None or not np.isfinite(ucs): return None
    lo_f, hi_f = UCS_CONFIG["physical_min"], UCS_CONFIG["physical_max"]
    if ucs < lo_f or ucs > hi_f: return None
    for lo, hi, nombre in BANDAS_RESISTENCIA:
        if lo <= ucs < hi or (hi >= hi_f and ucs == hi):
            return nombre
    return None


def _calidad_factor(lito: Optional[str]) -> Tuple[float, Optional[int]]:
    """
    Factor de confianza por calidad del ancla, en (0, 1]. Es el inverso del
    pi_factor del atributo: donde el intervalo de predicción se ensancha, la
    confianza del bloque baja en la misma proporción. Sin atributo registrado
    el factor es el peor posible, no el mejor: un dominio desconocido no puede
    heredar la confianza de uno con ensayo.
    """
    a = attr_registry.get(lito or "")
    if a is None:
        return 1.0 / max(QUALITY_PI_FACTOR[4], 1.0), None
    f = a.pi_factor()
    if f is None:
        return 1.0 / max(QUALITY_PI_FACTOR[4], 1.0), a.calidad
    return 1.0 / max(f, 1.0), a.calidad


def _muestras_bloques(fuente: str = "ucs_matriz") -> Dict:
    """
    Muestras para interpolar: coordenadas UTM, UCS predicho, DI y litología.
    `fuente` elige entre "ucs_matriz" (UCS de la matriz rocosa, sin
    discontinuidades) y "ucs_ml" (predicción cruda). Los puntos sin UCS no se
    rellenan con nada: quedan fuera y se cuentan.
    """
    P, ucs, di, lito, pozo, caseron = [], [], [], [], [], []
    sin_ucs = 0
    for wn, w in wells.items():
        for p in w.points:
            if not p.entrenable: continue
            v = getattr(p, fuente, None)
            if v is None: v = p.ucs_ml
            if v is None or not np.isfinite(v):
                sin_ucs += 1; continue
            if v < UCS_CONFIG["physical_min"] or v > UCS_CONFIG["physical_max"]:
                sin_ucs += 1; continue
            P.append((p.este, p.norte, p.cota))
            ucs.append(float(v))
            di.append(float(p.di) if p.di is not None and np.isfinite(p.di) else np.nan)
            lito.append(p.lito or p.dominio)
            pozo.append(wn)
            caseron.append(getattr(w, "caseron", None) or "—")
    return {"P": np.array(P, dtype=np.float64) if P else np.zeros((0, 3)),
            "ucs": np.array(ucs), "di": np.array(di),
            "lito": lito, "pozo": pozo, "caseron": caseron, "sin_ucs": sin_ucs}


def interpolate_block_model(bloque_m: Optional[float] = None,
                            potencia: Optional[float] = None,
                            radio_h_m: Optional[float] = None,
                            radio_v_m: Optional[float] = None,
                            anisotropia: Optional[Tuple[float, float, float]] = None,
                            min_muestras: Optional[int] = None,
                            min_pozos: int = IDW_MIN_POZOS,
                            fuente: str = "ucs_matriz",
                            agrupar_por_caseron: bool = True,
                            holgura_m: Optional[float] = None) -> Dict:
    """
    (9.1) Interpola UCS y DI a un modelo de bloques con IDW anisotrópico y
    máscara de soporte.

    El DOMINIO del modelo es el espacio perforado más `holgura_m`. Un bloque
    más lejos que eso de todo tiro no es un bloque vacío: está FUERA, y no
    entra en la cobertura. Dentro del dominio, un bloque recibe valor solo si
    en el elipsoide de búsqueda (radio_h_m en planta, radio_v_m en cota) hay
    al menos `min_muestras` registros de al menos `min_pozos` pozo(s). Si no
    los hay queda VACÍO y se cuenta — nunca se estira la búsqueda para
    llenarlo.
    """
    # Los parámetros se resuelven EN CADA LLAMADA contra el perfil de faena.
    # Fijarlos como valor por defecto de la firma los congelaría al importar el
    # módulo, y cambiar el perfil desde la aplicación no serviría de nada.
    bloque_m = get_param("bloques.tamano_m") if bloque_m is None else bloque_m
    potencia = get_param("bloques.potencia_idw") if potencia is None else potencia
    radio_h_m = get_param("bloques.radio_h_m") if radio_h_m is None else radio_h_m
    radio_v_m = get_param("bloques.radio_v_m") if radio_v_m is None else radio_v_m
    min_muestras = get_param("bloques.min_muestras") if min_muestras is None else min_muestras
    holgura_m = get_param("bloques.holgura_m") if holgura_m is None else holgura_m
    if anisotropia is None:
        anisotropia = (1.0, 1.0, float(get_param("bloques.anisotropia_z")))
    m = _muestras_bloques(fuente)
    P = m["P"]
    if P.shape[0] == 0:
        return {"status": "sin_datos",
                "motivo": ("Ningún punto MWD tiene UCS predicho dentro de los "
                           f"límites físicos ({UCS_CONFIG['physical_min']:g}-"
                           f"{UCS_CONFIG['physical_max']:g} MPa): "
                           "correr el entrenamiento y la predicción antes de "
                           "interpolar."),
                "bloques": [], "n_vacios": 0,
                "terminologia": TERMINOLOGIA_C}

    ax, ay, az = anisotropia
    bloques, n_vacios, n_fuera = [], 0, 0
    pozos_arr = np.array(m["pozo"])
    caseron_arr = np.array(m["caseron"])
    por_caseron: Dict[str, Dict] = {}

    # Un encajonado ÚNICO sobre caserones separados por kilómetros contaría
    # como "vacío" el aire entre ellos y volvería el porcentaje de cobertura
    # una cifra sin significado. Cada caserón se encajona por separado; los
    # bloques nunca cruzan de uno a otro porque las muestras tampoco.
    grupos = ({c: np.where(caseron_arr == c)[0] for c in sorted(set(m["caseron"]))}
              if agrupar_por_caseron else {"todos": np.arange(P.shape[0])})

    for nombre_cas, gidx in grupos.items():
      if gidx.size == 0:
        continue
      Pg = P[gidx]
      n_bloques_antes, n_vacios_antes, n_fuera_antes = len(bloques), n_vacios, n_fuera
      # El encajonado sale del espacio perforado más la holgura, y es un
      # prisma recto: no complica el recorrido y el planificador lo entiende.
      lo = Pg.min(axis=0) - holgura_m
      hi = Pg.max(axis=0) + holgura_m
      ejes = [np.arange(lo[k] + bloque_m / 2.0, hi[k] + bloque_m / 2.0, bloque_m)
              for k in range(3)]
      # Índice espacial: celda de lado radio_h_m sobre el plano, para no evaluar
      # el millón de muestras contra cada bloque.
      celda = max(radio_h_m, 1e-6)
      ij = np.floor(Pg[:, :2] / celda).astype(np.int64)
      cubos: Dict[Tuple[int, int], list] = {}
      for idx, (i, j) in enumerate(map(tuple, ij)):
          cubos.setdefault((i, j), []).append(gidx[idx])

      for x in ejes[0]:
          ci = int(np.floor(x / celda))
          for y in ejes[1]:
              cj = int(np.floor(y / celda))
              vecinos = []
              # La holgura puede superar el lado de la celda del índice: se
              # barre el vecindario necesario para no perder tiros de borde.
              rad_celdas = int(np.ceil(max(radio_h_m, holgura_m) / celda))
              for di_ in range(-rad_celdas, rad_celdas + 1):
                  for dj_ in range(-rad_celdas, rad_celdas + 1):
                      vecinos.extend(cubos.get((ci + di_, cj + dj_), ()))
              if not vecinos:
                  n_fuera += len(ejes[2]); continue
              vec = np.array(vecinos)
              sub_all = P[vec]
              dh_all = np.hypot(sub_all[:, 0] - x, sub_all[:, 1] - y)
              # Dominio: ¿hay algún tiro dentro de la holgura, en planta?
              en_dom = dh_all <= holgura_m
              if not en_dom.any():
                  n_fuera += len(ejes[2]); continue
              sub_dom, dh_dom = sub_all[en_dom], dh_all[en_dom]
              en_h = dh_all <= radio_h_m
              vec, sub, dh = vec[en_h], sub_all[en_h], dh_all[en_h]
              for z in ejes[2]:
                  # Fuera del dominio en cota: el bloque no pertenece al modelo.
                  if not np.any((dh_dom <= holgura_m)
                                & (np.abs(sub_dom[:, 2] - z) <= holgura_m)):
                      n_fuera += 1; continue
                  if sub.shape[0] == 0:
                      n_vacios += 1; continue
                  dv = np.abs(sub[:, 2] - z)
                  sel = dv <= radio_v_m
                  n_sel = int(sel.sum())
                  if n_sel < min_muestras:
                      n_vacios += 1; continue
                  idxs = vec[sel]
                  if len({pozos_arr[i] for i in idxs}) < min_pozos:
                      n_vacios += 1; continue
                  # Distancia anisotrópica: la separación vertical se multiplica
                  # por az antes de entrar al peso.
                  d = np.sqrt((ax * (sub[sel, 0] - x)) ** 2
                              + (ay * (sub[sel, 1] - y)) ** 2
                              + (az * (sub[sel, 2] - z)) ** 2)
                  d = np.maximum(d, 1e-6)
                  wgt = 1.0 / d ** potencia
                  sw = wgt.sum()
                  ucs_b = float((m["ucs"][idxs] * wgt).sum() / sw)
                  di_vals = m["di"][idxs]
                  fin = np.isfinite(di_vals)
                  di_b = (float((di_vals[fin] * wgt[fin]).sum() / wgt[fin].sum())
                          if fin.any() else None)
                  # Litología del bloque: la de mayor peso acumulado, no la más
                  # frecuente — un pozo con muchos registros lejanos no debe
                  # ganarle a uno cercano.
                  peso_lito: Dict[str, float] = {}
                  for k, i in enumerate(idxs):
                      lt = m["lito"][i]
                      if lt: peso_lito[lt] = peso_lito.get(lt, 0.0) + float(wgt[k])
                  lito_b = max(peso_lito, key=peso_lito.get) if peso_lito else None
                  f_cal, calidad = _calidad_factor(lito_b)
                  dmin = float(np.sqrt((sub[sel, 0] - x) ** 2 + (sub[sel, 1] - y) ** 2
                                       + (sub[sel, 2] - z) ** 2).min())
                  # Confianza = calidad de la etiqueta × proximidad × soporte.
                  # Los tres factores viven en [0, 1] y se declaran por separado
                  # en el reporte para que el número no sea una caja negra.
                  f_prox = float(max(0.0, 1.0 - dmin / max(radio_h_m, 1e-9)))
                  f_sop = float(min(1.0, n_sel / max(4.0 * min_muestras, 1.0)))
                  conf = round(f_cal * f_prox * f_sop, 4)
                  bloques.append({
                      "x": round(float(x), 3), "y": round(float(y), 3),
                      "z": round(float(z), 3), "tamano_m": bloque_m,
                      "caseron": nombre_cas,
                      "ucs": round(min(max(ucs_b, UCS_CONFIG["physical_min"]),
                                       UCS_CONFIG["physical_max"]), 2),
                      "di": round(di_b, 4) if di_b is not None else None,
                      "confianza": conf, "lito": lito_b, "calidad_etiqueta": calidad,
                      "banda": banda_resistencia(ucs_b),
                      "n_muestras": n_sel, "dist_min_m": round(dmin, 3),
                      "f_calidad": round(f_cal, 4), "f_proximidad": round(f_prox, 4),
                      "f_soporte": round(f_sop, 4),
                  })
      n_con = len(bloques) - n_bloques_antes
      n_vac = n_vacios - n_vacios_antes
      n_fue = n_fuera - n_fuera_antes
      por_caseron[nombre_cas] = {
          "n_bloques": n_con, "n_vacios": n_vac, "n_fuera_del_dominio": n_fue,
          "n_muestras": int(gidx.size),
          # Cobertura SOBRE EL DOMINIO —espacio perforado más holgura—, no
          # sobre el encajonado: es la fracción del volumen que va a tronarse
          # y que el modelo alcanza a describir.
          "cobertura": round(n_con / max(n_con + n_vac, 1), 4),
          "encajonado_m": [round(float(hi[k] - lo[k]), 1) for k in range(3)]}
    if not bloques:
        return {"status": "sin_soporte",
                "motivo": (f"Ningún bloque de {bloque_m:g} m reúne {min_muestras} "
                           f"muestra(s) dentro del elipsoide de búsqueda "
                           f"({radio_h_m:g} m en planta, {radio_v_m:g} m en cota). "
                           "Los bloques quedan VACÍOS antes que interpolados desde "
                           "lejos."),
                "bloques": [], "n_vacios": n_vacios,
                "terminologia": TERMINOLOGIA_C}
    return {
        "status": "ok", "bloques": bloques, "n_bloques": len(bloques),
        "n_vacios": n_vacios,
        "motivo_vacios": (f"{n_vacios} bloque(s) quedaron VACÍOS por no reunir "
                          f"{min_muestras} muestra(s) dentro del elipsoide de "
                          f"búsqueda ({radio_h_m:g} m en planta, {radio_v_m:g} m en "
                          "cota). No se interpolan desde más lejos: un bloque sin "
                          "soporte es información, no un hueco a rellenar. El "
                          "encajonado se calcula POR CASERÓN: un encajonado único "
                          "sobre caserones separados por kilómetros contaría el "
                          "aire entre ellos y volvería la cobertura una cifra sin "
                          "significado."
                          if agrupar_por_caseron else
                          f"{n_vacios} bloque(s) quedaron VACÍOS por no reunir "
                          f"{min_muestras} muestra(s) dentro del elipsoide de "
                          f"búsqueda ({radio_h_m:g} m en planta, {radio_v_m:g} m en "
                          "cota). ATENCIÓN: encajonado ÚNICO sobre todos los "
                          "caserones — el aire entre caserones cuenta como vacío."),
        "por_caseron": por_caseron, "agrupado_por_caseron": agrupar_por_caseron,
        "bloque_m": bloque_m, "potencia": potencia,
        "radio_h_m": radio_h_m, "radio_v_m": radio_v_m,
        "anisotropia": list(anisotropia), "min_muestras": min_muestras,
        "fuente_ucs": fuente, "puntos_sin_ucs": m["sin_ucs"],
        "n_muestras": int(P.shape[0]),
        "limites_ucs": [UCS_CONFIG["physical_min"], UCS_CONFIG["physical_max"]],
        "bandas_fuente": BANDAS_RESISTENCIA_FUENTE,
        "definicion_confianza": (
            "Confianza = f_calidad × f_proximidad × f_soporte, los tres en [0, 1]. "
            "f_calidad es el inverso del pi_factor del atributo: incorpora la "
            "CALIDAD de la etiqueta, de modo que un dominio anclado en un ensayo "
            "del sitio y otro anclado en literatura no pueden salir con la misma "
            "confianza. f_proximidad decae con la distancia al dato más cercano. "
            "f_soporte crece con el número de muestras dentro del elipsoide."),
        "anisotropia_motivo": (
            "El yacimiento es estratiforme: la litología continúa lateralmente y "
            "cambia con la cota. Por eso la búsqueda es más larga en horizontal "
            "que en vertical. La cota entra acá como GEOMETRÍA de interpolación, "
            "nunca como variable predictora del modelo."),
        "terminologia": TERMINOLOGIA_C,
    }


def export_block_model_csv(rep: Optional[Dict] = None) -> str:
    """(9.2) Modelo de bloques como CSV: X, Y, Z, tamaño, UCS, DI, confianza."""
    rep = rep if rep is not None else interpolate_block_model()
    if rep.get("status") != "ok":
        return f"# {rep.get('motivo', 'sin datos')}\n"
    cols = ["x", "y", "z", "tamano_m", "caseron", "ucs", "di", "confianza",
            "banda", "lito", "calidad_etiqueta", "n_muestras", "dist_min_m",
            "f_calidad", "f_proximidad", "f_soporte"]
    df = pd.DataFrame(rep["bloques"])[cols]
    cab = "\n".join("# " + l for l in [
        f"{rep['terminologia']}.",
        f"Bloque {rep['bloque_m']:g} m · IDW potencia {rep['potencia']:g} · "
        f"anisotropía {rep['anisotropia']} · radio {rep['radio_h_m']:g} m planta / "
        f"{rep['radio_v_m']:g} m cota.",
        rep["anisotropia_motivo"],
        rep["definicion_confianza"],
        rep["motivo_vacios"],
        f"UCS acotado a los límites físicos {rep['limites_ucs']} MPa.",
        f"bandas: {rep['bandas_fuente']}",
        f"generado: {time.strftime('%Y-%m-%d %H:%M')}"])
    return cab + "\n" + df.to_csv(index=False)


def export_block_model_dxf(rep: Optional[Dict] = None,
                           path: str = "modelo_bloques.dxf",
                           geometria: str = "caja") -> str:
    """
    (9.3) Modelo de bloques como DXF, con una CAPA POR BANDA de resistencia
    para que se pueda prender y apagar por banda en el visor de la mina.

    `geometria`: "caja" dibuja cada bloque como un cubo de 3DFACE (lo que el
    planificador espera ver); "punto" deja solo el centro, mucho más liviano
    para modelos grandes.
    """
    rep = rep if rep is not None else interpolate_block_model()
    if rep.get("status") != "ok":
        raise ValueError(rep.get("motivo", "sin datos para exportar"))
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    # Capa por banda, más una para lo que no clasifica: nada queda sin capa.
    for _, _, nombre in BANDAS_RESISTENCIA:
        doc.layers.add(BLOQUE_LAYER_PREFIX + nombre)
    doc.layers.add(BLOQUE_LAYER_PREFIX + "sin_banda")
    for b in rep["bloques"]:
        capa = BLOQUE_LAYER_PREFIX + (b["banda"] or "sin_banda")
        x, y, z, s = b["x"], b["y"], b["z"], b["tamano_m"] / 2.0
        if geometria == "punto":
            msp.add_point((x, y, z), dxfattribs={"layer": capa})
            continue
        v = [(x - s, y - s, z - s), (x + s, y - s, z - s),
             (x + s, y + s, z - s), (x - s, y + s, z - s),
             (x - s, y - s, z + s), (x + s, y - s, z + s),
             (x + s, y + s, z + s), (x - s, y + s, z + s)]
        for cara in ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
                     (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            msp.add_3dface([v[i] for i in cara], dxfattribs={"layer": capa})
    doc.header["$PROJECTNAME"] = TERMINOLOGIA_C
    doc.saveas(path)
    return path


def block_model_summary(rep: Optional[Dict] = None) -> Dict:
    """(9.4) Resumen por banda y por litología, para la tabla del capítulo."""
    rep = rep if rep is not None else interpolate_block_model()
    if rep.get("status") != "ok":
        return {"status": rep.get("status"), "motivo": rep.get("motivo")}
    por_banda: Dict[str, Dict] = {}
    for b in rep["bloques"]:
        k = b["banda"] or "sin_banda"
        d = por_banda.setdefault(k, {"n": 0, "ucs": [], "di": [], "conf": []})
        d["n"] += 1
        d["ucs"].append(b["ucs"])
        if b["di"] is not None: d["di"].append(b["di"])
        d["conf"].append(b["confianza"])
    resumen = {k: {"n_bloques": v["n"],
                   "volumen_m3": round(v["n"] * rep["bloque_m"] ** 3, 1),
                   "ucs_mediana": round(float(np.median(v["ucs"])), 2),
                   "di_mediana": round(float(np.median(v["di"])), 4) if v["di"] else None,
                   "confianza_mediana": round(float(np.median(v["conf"])), 4)}
               for k, v in sorted(por_banda.items())}
    # La cobertura GLOBAL sobre un encajonado que abarca varios caserones no
    # significa nada: un caserón compacto y bien perforado y un nivel de 900 m
    # de largo con pozos dispersos se promedian en una cifra que no describe a
    # ninguno de los dos. Se entrega por caserón, y la global va acompañada de
    # esa advertencia.
    por_cas = rep.get("por_caseron") or {}
    return {"status": "ok", "por_banda": resumen,
            "n_bloques": rep["n_bloques"], "n_vacios": rep["n_vacios"],
            "por_caseron": {c: {"n_bloques": d["n_bloques"], "n_vacios": d["n_vacios"],
                                "cobertura": d["cobertura"],
                                "volumen_m3": round(d["n_bloques"] * rep["bloque_m"] ** 3, 1)}
                            for c, d in por_cas.items()},
            "cobertura": round(rep["n_bloques"] / max(rep["n_bloques"] + rep["n_vacios"], 1), 4),
            "cobertura_advertencia": (
                "La cobertura global mezcla caserones de tamaño y densidad de "
                "perforación distintos: leer la de cada caserón, no el promedio."
                if len(por_cas) > 1 else None),
            "terminologia": TERMINOLOGIA_C}


def export_se_ucs_coherence_csv(rep: Optional[Dict] = None) -> str:
    """Coherencia SE↔UCS como CSV, con el veredicto y las advertencias arriba."""
    rep = rep if rep is not None else se_ucs_coherence_report()
    if rep.get("status") != "ok":
        return f"# {rep.get('motivo', 'sin datos')}\n"
    filas = [{"dominio": d["dominio"], "ucs_lab_MPa": d["ucs_lab"],
              "se_mediana": d["se_mediana"], "se_cv": d["se_cv"],
              "rop_mediana": d["rop_mediana"], "pp_mediana": d["pp_mediana"],
              "n_puntos_roca_intacta": d["n"]}
             for d in rep["dominios"]]
    cab = "\n".join("# " + l for l in [
        "Coherencia energía específica ↔ UCS de laboratorio, sobre ROCA INTACTA.",
        rep["veredicto"],
        f"rho_spearman={rep['rho_spearman']} · monotona={rep['monotona']}",
        rep["di_nota"], rep["advertencia_pp"],
        f"generado: {time.strftime('%Y-%m-%d %H:%M')}"])
    return cab + "\n" + pd.DataFrame(filas).to_csv(index=False)


def export_concordance_csv(full: Optional[Dict] = None) -> str:
    """(C.7) Reporte de concordancia como CSV plano, con el encuadre arriba."""
    full = full if full is not None else concordance_full_report()
    filas = []
    c3 = full.get("c3", {})
    if c3.get("status") == "ok":
        for b in c3["bins"]:
            filas.append({"seccion": "C.3 concordancia vs distancia",
                          "clave": f"{b['d_min']}-{b['d_max']} m",
                          "valor": b["concordancia"], "n": b["n"]})
        filas.append({"seccion": "C.3 concordancia vs distancia", "clave": "pendiente",
                      "valor": c3["pendiente"], "n": c3["n"]})
    c4 = full.get("c4", {})
    if c4.get("status") == "ok":
        filas.append({"seccion": "C.4 desacuerdo", "clave": "cerca del borde",
                      "valor": c4["cerca_del_borde"], "n": c4["n_medidos"]})
        filas.append({"seccion": "C.4 desacuerdo", "clave": "interior macizo",
                      "valor": c4["interior_macizo"], "n": c4["n_medidos"]})
    c5 = full.get("c5", {})
    if c5.get("status") == "ok":
        for k in ("media", "mediana", "desviacion", "sesgo"):
            filas.append({"seccion": "C.5 desfase de contactos", "clave": k,
                          "valor": c5[k], "n": c5["n"]})
    c6 = full.get("c6", {})
    if c6.get("status") == "ok":
        filas.append({"seccion": "C.6 confusión", "clave": "concordancia global",
                      "valor": c6["concordancia_global"], "n": c6["n"]})
        for u, v in c6["por_unidad"].items():
            filas.append({"seccion": "C.6 confusión", "clave": f"concordancia {u}",
                          "valor": v["concordancia"], "n": v["n"]})
    cab = "\n".join("# " + l for l in [
        full["encuadre"], f"fuente de contraste: {full.get('fuente')}",
        f"generado: {time.strftime('%Y-%m-%d %H:%M')}"])
    df = pd.DataFrame(filas or [{"seccion": "—", "clave": "sin datos", "valor": "", "n": 0}])
    return cab + "\n" + df.to_csv(index=False)


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


# Tope de muestras de la COMPARACIÓN de modelos. KNN y MLP sobre 400.000
# registros tardan horas y no aportan nada que 60.000 no muestre; el modelo de
# producción (train_rf) NO usa este tope, entrena con todo. El submuestreo se
# hace por POZOS COMPLETOS, nunca por filas sueltas: sacar filas de un pozo
# rompería la validación agrupada, que es justamente lo que la comparación
# tiene que preservar para ser metodológicamente comparable. Y se DECLARA en
# el reporte — un número obtenido sobre una fracción de los datos que no dice
# que lo es, miente.
COMPARISON_MAX_N = 60000
COMPARISON_SEED = 42


def _submuestrear_por_pozo(X, y, groups, max_n, seed=COMPARISON_SEED):
    """
    Sortea POZOS enteros hasta acercarse a `max_n` registros. Devuelve
    (X, y, groups, nota) — nota es None si no hizo falta submuestrear.
    """
    if len(X) <= max_n:
        return X, y, groups, None
    rng = np.random.default_rng(seed)
    pozos = np.array(sorted(set(groups.tolist())))
    rng.shuffle(pozos)
    elegidos, n = [], 0
    for p in pozos:
        k = int((groups == p).sum())
        if n + k > max_n and elegidos:
            break
        elegidos.append(p); n += k
    mask = np.isin(groups, elegidos)
    nota = (f"SUBMUESTREADO: {int(mask.sum()):,} de {len(X):,} registro(s), "
            f"{len(elegidos)} de {len(pozos)} pozo(s), sorteados por POZO COMPLETO "
            f"con semilla {seed} para no romper la validación agrupada. El modelo "
            "de producción entrena con todos los datos; este tope aplica solo a la "
            "comparación.").replace(",", ".")
    return X[mask], y[mask], groups[mask], nota


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
    X, y_s, groups_s, nota_sub = _submuestrear_por_pozo(X, y, groups, COMPARISON_MAX_N)
    y, groups = y_s, groups_s
    n_grupos = len(set(groups.tolist()))
    k = min(5, n_grupos)
    gkf = GroupKFold(n_splits=k)
    rows = []
    for name in COMPARISON_MODELS:
        try:
            model = _make_comparison_model(name)
            cv = cross_validate(model, X, y, cv=gkf, groups=groups,
                                scoring=("r2", "neg_root_mean_squared_error"),
                                n_jobs=1)
            r2 = cv["test_r2"]
            rmse = -cv["test_neg_root_mean_squared_error"]
            rows.append({"modelo": name, "r2_mean": round(float(r2.mean()), 3),
                        "r2_std": round(float(r2.std()), 3),
                        "rmse_mean": round(float(rmse.mean()), 1),
                        "rmse_std": round(float(rmse.std()), 1), "error": None})
        except Exception as e:
            rows.append({"modelo": name, "r2_mean": None, "r2_std": None,
                        "rmse_mean": None, "rmse_std": None, "error": str(e)})
    # El modelo de producción entrena sobre TODOS los registros y con otros
    # hiperparámetros. Si su R² de CV difiere del que sale acá, la diferencia
    # es del submuestreo o de la configuración, y el lector tiene que poder
    # verlo sin ir a buscarlo: se pone al lado, no se elige uno de los dos.
    r2_prod = (rf_stats or {}).get("cv_r2_mean")
    mejor = max((r for r in rows if r["r2_mean"] is not None),
                key=lambda r: r["r2_mean"], default=None)
    nota_prod = None
    if r2_prod is not None and mejor is not None:
        nota_prod = (f"El modelo de producción (train_rf) reporta R² de CV "
                     f"{r2_prod:+.3f} sobre todos los registros; el mejor de "
                     f"esta comparación es "
                     f"{mejor['modelo']} con {mejor['r2_mean']:+.3f}. La diferencia "
                     "viene del tamaño de muestra y de los hiperparámetros, que no "
                     "son los mismos: son dos mediciones distintas y se reportan "
                     "las dos.")
    return {"status": "ok", "with_se": with_se, "n_samples": len(X),
            "n_grupos": n_grupos, "k_splits": k, "rows": rows,
            "nota_submuestreo": nota_sub, "tope_muestras": COMPARISON_MAX_N,
            "r2_produccion": r2_prod, "nota_produccion": nota_prod}


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

# ─── VALIDACIÓN INDEPENDIENTE DI ↔ RQD (T5) ────────────────────────────────────
# El RQD del Excel geomecánico proviene de mapeo/sondajes: es INDEPENDIENTE del
# MWD. Hipótesis: el DI medio por caserón anticorrelaciona con el RQD (más
# discontinuidades detectadas por MWD → roca más fracturada → menor RQD). Es la
# única validación externa del DI disponible en la mina.
DI_RQD_MIN_PUNTOS = 100

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

def run_cross_ml(ucs_min=None, ucs_max=None):
    classify_all_wells_cached()
    build_domain_index()
    stats = train_rf(ucs_min, ucs_max)
    if "error" not in stats:
        predict_all_wells()
        wz_state['step4']['model_trained'] = True
    return stats

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


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CARPETA-REPOSITORIO Y GUARDADO A DISCO                                 ║
# ║                                                                          ║
# ║  Subir archivo por archivo no escala: un caserón trae 477 XML. Se apunta ║
# ║  a una carpeta del computador y el programa la recorre.                  ║
# ║                                                                          ║
# ║  Y el proyecto se guarda a una RUTA, no por descarga del navegador: el   ║
# ║  .gwz de tres caserones pesa decenas de MB y esa descarga falla sin      ║
# ║  decir nada en Colab. El guardado siempre funcionó; el transporte no.    ║
# ╚══════════════════════════════════════════════════════════════════════════╝

# Carpetas cuyo nombre NO es un caserón: son organización, no sitio.
_REPO_CARPETAS_GENERICAS = {
    "xml", "xmls", "capas", "dxf", "litologia", "litología", "estructura",
    "estructuras", "sondaje", "sondajes", "datos", "data", "notas", "docs",
    "mwd", "dq", "mw",
}


def explorar_repositorio(raiz: str) -> Dict:
    """
    Recorre una carpeta-repositorio y clasifica lo que encuentra: DXF, DQ, MW
    y CSV de sondaje, más el caserón que se deduce de la carpeta contenedora.

    Lo que NO se reconoce se NOMBRA. Un archivo que el programa ignora en
    silencio es indistinguible de un archivo que no llegó, y en una carga de
    2.000 archivos esa diferencia importa.
    """
    if not raiz or not os.path.isdir(raiz):
        return {"status": "error",
                "motivo": f"No existe la carpeta «{raiz}» o no es un directorio.",
                "raiz": raiz}
    out = {"status": "ok", "raiz": raiz, "dxf": [], "dq": [], "mw": [],
           "sondajes": [], "no_reconocidos": [], "por_caseron": {}}

    # El caserón se busca por PATRÓN dentro de la ruta, no por posición: en un
    # repositorio real viene embebido en nombres como "Capas PCC_1541" o en el
    # propio archivo (MWPCS_1043_...), y un criterio posicional devuelve la
    # carpeta contenedora ("reales", "test_data") en vez del caserón.
    patron = get_param("repo.patron_caseron")
    try:
        rx = re.compile(patron) if patron else None
    except re.error as e:
        return {"status": "error", "raiz": raiz,
                "motivo": (f"El patrón de caserón «{patron}» no es una expresión "
                           f"regular válida: {e}")}

    def caseron_de(rel: str) -> Optional[str]:
        if rx is not None:
            m = rx.search(rel)
            if m:
                return m.group(0)
        # Sin patrón que calce, el primer tramo que no sea de organización.
        for parte in rel.split(os.sep)[:-1]:
            if _norm_txt(parte) not in _REPO_CARPETAS_GENERICAS:
                return parte
        return None

    for dirpath, _dirs, files in os.walk(raiz):
        for f in sorted(files):
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, raiz)
            low = f.lower()
            if low.startswith("."):
                continue
            if low.endswith(".dxf"):
                tipo = "dxf"
            elif low.endswith(".xml"):
                tipo = "dq" if is_dq(f) else "mw"
            elif low.endswith(".csv") and guess_drillhole_kind(f):
                tipo = "sondajes"
            else:
                out["no_reconocidos"].append(rel)
                continue
            out[tipo].append(full)
            cas = caseron_de(rel)
            if cas:
                d = out["por_caseron"].setdefault(
                    cas, {"dxf": [], "dq": [], "mw": [], "sondajes": []})
                d[tipo].append(full)
    out["n_total"] = sum(len(out[k]) for k in ("dxf", "dq", "mw", "sondajes"))
    out["patron_caseron"] = patron
    out["criterio_caseron"] = (
        f"El caserón se busca con el patrón «{patron}» en la ruta completa del "
        "archivo, incluido su nombre: en un repositorio real viene embebido en "
        "carpetas como «Capas PCC_1541» o en el propio archivo. Si el patrón no "
        "calza, se usa el primer tramo que no sea una carpeta de organización "
        "(xml, capas, litología, estructuras, sondajes…).")
    out["motivo_no_reconocidos"] = (
        f"{len(out['no_reconocidos'])} archivo(s) no son DXF, ni XML de MWD o DQ, "
        "ni CSV de sondaje reconocible por su nombre. Se listan porque un "
        "archivo ignorado en silencio es indistinguible de uno que no llegó."
        if out["no_reconocidos"] else None)
    return out


def guardar_proyecto_en(path: str) -> Dict:
    """
    Guarda el proyecto en una RUTA del disco y declara qué guardó y cuánto
    pesa. Crea la carpeta si falta. Los errores se devuelven, no se lanzan:
    el llamador es una interfaz que tiene que mostrarlos.
    """
    try:
        carpeta = os.path.dirname(os.path.abspath(path))
        if carpeta:
            os.makedirs(carpeta, exist_ok=True)
        save_project(path)
        n_bytes = os.path.getsize(path)
        return {"status": "ok", "ruta": os.path.abspath(path),
                "tamano_bytes": int(n_bytes),
                "tamano_MB": round(n_bytes / 1e6, 3),
                "n_pozos": len(wells),
                "n_puntos": sum(len(w.points) for w in wells.values()),
                "n_mallas": len(layers), "n_sondajes": len(drillholes),
                "nota": ("Guardado a disco, sin pasar por la descarga del "
                         "navegador: con proyectos de decenas de MB esa "
                         "descarga falla sin avisar.")}
    except Exception as e:
        return {"status": "error",
                "motivo": f"No se pudo guardar en «{path}»: {type(e).__name__}: {e}"}


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
                "caseron": lay.caseron,
                "lito_alias": lay.lito_alias,
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
        "di_config": di_config,
        "di_threshold": di_threshold,
        # Las variantes del DI y CUÁL está corriendo: sin esto, un proyecto
        # calculado con una variante se reabre diciendo "convención".
        "di_variantes": {k: v for k, v in di_variantes.items()
                         if not v.get("solo_lectura")},
        "di_variante_activa": di_variante_activa,
        "group_interval_m": group_interval_m,
        "ucs_range": ucs_range,
        "global_center": global_center,
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
    # di_threshold ya no se escribe acá: lo fija activar_di(), que es la única
    # puerta por la que se cambia el DI vigente.
    global group_interval_m, global_center, inicio_cut_m
    with _zipfile.ZipFile(path, "r") as zf:
        proj = json.loads(zf.read("project.json"))
        npz_data = np.load(_io.BytesIO(zf.read("triangles.npz")), allow_pickle=False)

    # Limpiar estado global
    wells.clear(); layers.clear(); domains.clear()
    domain_groups.clear(); clean_filters.clear()
    parse_warnings.clear()
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
            bbox_min=np.array(lm["bbox_min"]), bbox_max=np.array(lm["bbox_max"]), folder=lm.get("folder","Litología"),
            caseron=lm.get("caseron"), lito_alias=lm.get("lito_alias"),
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
    # Variantes del DI y cuál corría. Se restauran ANTES de fijar el vigente:
    # activar una variante que todavía no está registrada sería un KeyError.
    seed_di_variants(force=True)
    for nom, v in (proj.get("di_variantes") or {}).items():
        if nom == DI_VARIANTE_CONVENCION or v.get("solo_lectura"):
            continue          # la convención se siembra, no se lee del archivo
        try:
            create_di_variant(nom, weights=v.get("weights") or {},
                              window=v.get("window"), threshold=v.get("threshold"),
                              fuente=v.get("fuente", ""), notas=v.get("notas", ""))
        except (ValueError, TypeError) as e:
            parse_warnings.append(
                f'Variante de DI "{nom}" del proyecto no se pudo restaurar: {e}')
    activa = proj.get("di_variante_activa")
    if activa in di_variantes:
        activar_di(activa)
    elif activa:
        parse_warnings.append(
            f'El proyecto corría con la variante de DI "{activa}", que no se pudo '
            "restaurar. Se activó la convención de Fernández et al. 2023: los DI "
            "guardados en los puntos NO corresponden a ella.")
        activar_di(DI_VARIANTE_CONVENCION)
    else:
        # Proyecto anterior a las variantes: trae di_config/di_threshold sueltos
        # y no se sabe de qué variante salieron. Se declara.
        cfg = proj.get("di_config") or {}
        thr = proj.get("di_threshold", DI_DEFAULTS["threshold"])
        try:
            nom = aplicar_di_config(
                window=int(cfg.get("window", DI_DEFAULTS["window"])),
                threshold=float(thr),
                weights=cfg.get("weights") or DI_DEFAULTS["weights"],
                nombre="proyecto_cargado",
                fuente="Configuración suelta de un proyecto guardado antes de "
                       "que existieran las variantes del DI.")
            if nom != DI_VARIANTE_CONVENCION:
                parse_warnings.append(
                    f'El proyecto traía una configuración de DI distinta de la '
                    f'convención; se registró como variante "{nom}".')
        except (ValueError, TypeError) as e:
            parse_warnings.append(
                f"La configuración de DI del proyecto no es válida ({e}). Se "
                "activó la convención de Fernández et al. 2023.")
            activar_di(DI_VARIANTE_CONVENCION)
    group_interval_m = proj.get("group_interval_m", group_interval_m)
    ucs_range.update(proj.get("ucs_range", {}))
    global_center = proj.get("global_center")
    parse_warnings.extend(proj.get("parse_warnings", []))
    wz_state.update(proj.get("wz_state", {}))
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
        # 2. Figuras HTML standalone
        def _html(fig):
            return fig.to_html(full_html=True, include_plotlyjs="cdn")

        # Visor 3D coloreado por dominio
        try:
            fig3d = build_3d_figure(color_by="grupo")
            zf.writestr("visor_3d_dominios.html", _html(fig3d))
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
        # La UCS de una malla es la de su ATRIBUTO: la capa ya no la lleva.
        _lito = layer_role_ids(layer).get("litologia")
        _a = attr_registry.get(_lito or "")
        _u = _a.ucs_ancla(modo=get_param("ucs.estadistica_ml")) if _a else None
        ucs_txt = f"UCS={_u:g} MPa ({_lito})" if _u is not None else "sin banda de UCS"
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
    # ── Sondajes con testigo ────────────────────────────────────────────────
    # Van en la misma vista que el MWD y las mallas: es la única forma de ver
    # si un sondaje pasa cerca de los tiros que dice describir, y esa cercanía
    # es justo lo que decide si su RQD sirve para calibrar. Se dibujan como
    # líneas gruesas, distintas del MWD, y cada uno declara en su hover su
    # estado y sus métricas.
    n_sondajes_dibujados = 0
    for hid, dh in drillholes.items():
        if not dh.trace or len(dh.trace) < 2:
            continue
        if f"DH::{hid}" in hidden_wells:
            continue
        col = ("#2ecc71" if dh.estado == "intersecta" else
               "#f1c40f" if dh.estado == "cercano" else "#7f8c8d")
        sel = dh.seleccionado()
        detalle = [f"<b>{hid}</b>",
                   f"estado: {dh.estado or 'sin cruce'}",
                   f"seleccionado: {'sí' if sel else 'no'}"]
        if dh.metros_dentro:
            detalle.append(f"metros dentro de malla: {dh.metros_dentro:.1f}")
        if dh.n_estructuras:
            detalle.append(f"estructuras: {dh.n_estructuras}")
        if dh.rqd_mediana is not None:
            detalle.append(f"RQD mediana: {dh.rqd_mediana:.0f}")
        if dh.banda:
            detalle.append(f"banda: {dh.banda}")
        texto = "<br>".join(detalle)
        fig.add_trace(go.Scatter3d(
            x=[t[1] for t in dh.trace], y=[t[2] for t in dh.trace],
            z=[t[3] for t in dh.trace],
            mode="lines", name=f"🗿 {hid}",
            line=dict(color=col, width=6 if sel else 3),
            opacity=1.0 if sel else 0.45,
            hoverinfo="text", text=[texto] * len(dh.trace),
            showlegend=True, legendgroup="sondajes",
            visible=True))
        # El collar, para poder ubicarlo aunque la traza quede tapada.
        fig.add_trace(go.Scatter3d(
            x=[dh.trace[0][1]], y=[dh.trace[0][2]], z=[dh.trace[0][3]],
            mode="markers", name=f"collar {hid}",
            marker=dict(size=4, color=col, symbol="diamond"),
            hoverinfo="text", text=[f"collar {hid}"],
            showlegend=False, legendgroup="sondajes", visible=True))
        n_sondajes_dibujados += 1

    # (E.4) El conteo real se declara SIEMPRE, se haya recortado la vista o
    # no — omitirlo cuando "por suerte" cabe entero sería el mismo default
    # silencioso que el proyecto prohíbe en todo lo demás: el usuario nunca
    # debería tener que adivinar si está viendo el 100% o una muestra.
    titulo_conteo = (f"Mostrando {n_dibujados:,} de {n_total_pts:,} puntos MWD"
                     .replace(",", "."))
    if n_sondajes_dibujados:
        titulo_conteo += f" · {n_sondajes_dibujados} sondaje(s)"
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


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  SESIÓN 10 — KIT DE RESULTADOS DEL CAPÍTULO 5                           ║
# ║                                                                          ║
# ║  Lo que se pega en la memoria. Tres reglas:                             ║
# ║                                                                          ║
# ║  NOMENCLATURA CONSISTENTE. Cada archivo se llama por su identificador,  ║
# ║  y el identificador no depende del orden de generación ni de qué datos  ║
# ║  había cargados.                                                        ║
# ║                                                                          ║
# ║  NUMERACIÓN ESTABLE. Los identificadores están DECLARADOS abajo, no     ║
# ║  derivados. Correr el kit dos veces da los mismos números, y una tabla  ║
# ║  que no se pudo generar no le cede su número a la siguiente.            ║
# ║                                                                          ║
# ║  NADA FALTA EN SILENCIO. Un ítem que no se pudo generar aparece en el   ║
# ║  índice con su estado y su motivo. Un índice donde el ítem simplemente  ║
# ║  no está es peor que uno que dice "faltó, y por esto".                  ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class KitSinDatos(Exception):
    """El ítem no se puede generar con los datos vigentes. Lleva el motivo."""


def _kit_csv_de_reporte(rep: Dict, filas_fn, contexto: List[str]) -> str:
    """Serializa un reporte-diccionario a CSV con su encuadre arriba."""
    filas = filas_fn(rep)
    if not filas:
        raise KitSinDatos(rep.get("motivo") or "El reporte no produjo filas.")
    cab = "\n".join("# " + l for l in contexto + [
        f"generado: {time.strftime('%Y-%m-%d %H:%M')}"])
    return cab + "\n" + pd.DataFrame(filas).to_csv(index=False)


def _kit_traslape() -> str:
    rep = ucs_band_overlap_report()
    filas = []
    for criterio, pares in rep.items():
        for p in pares:
            filas.append({"criterio": criterio, **p})
    if not filas:
        raise KitSinDatos("Ningún par de atributos tiene banda de UCS comparable: "
                          "sin dos bandas no hay traslape que medir.")
    cab = "\n".join("# " + l for l in [
        "Matriz de traslape de bandas de UCS, con AMBOS criterios.",
        "confianza = banda declarada del registro (el rango con el que se "
        "entrena). dispersion = rango observado en los ensayos. Son conceptos "
        "distintos y por eso se reportan por separado, nunca fusionados.",
        f"generado: {time.strftime('%Y-%m-%d %H:%M')}"])
    return cab + "\n" + pd.DataFrame(filas).to_csv(index=False)


def _kit_composicion() -> str:
    rep = training_composition_report()
    if not rep or rep.get("error"):
        raise KitSinDatos(rep.get("error") if rep else "Sin conjunto de entrenamiento.")
    return _kit_csv_de_reporte(
        rep, lambda r: r.get("funnel") or [],
        ["Composición del conjunto de entrenamiento: embudo etapa por etapa.",
         "Cada etapa declara cuántos puntos quedan y cuántos perdió. Un modelo "
         "que entrena con el 5% de los datos no es el mismo modelo: la etapa que "
         "más descartó es la que hay que mirar primero.",
         f"total: {rep.get('n_total')} → final: {rep.get('n_final')}"])


def _kit_correlacion() -> str:
    rep = correlation_matrix_report()
    if not rep or rep.get("error"):
        raise KitSinDatos((rep or {}).get("error") or "Sin datos para correlacionar.")
    if rep.get("status") != "ok":
        raise KitSinDatos(rep.get("motivo") or "Sin datos para correlacionar.")
    m = rep.get("matrix")
    etiquetas = rep.get("features")
    if not m or not etiquetas:
        raise KitSinDatos("El reporte de correlación no trae matriz.")
    df = pd.DataFrame(m, index=etiquetas, columns=etiquetas)
    cab = "\n".join("# " + l for l in [
        "Matriz de correlación entre variables MWD.",
        f"umbral de multicolinealidad declarado: {MULTICOLLINEARITY_THRESHOLD}",
        f"generado: {time.strftime('%Y-%m-%d %H:%M')}"])
    return cab + "\n" + df.to_csv()


def _kit_comparacion_modelos() -> str:
    con = model_comparison_report(with_se=True)
    sin = model_comparison_report(with_se=False)
    filas = []
    for etiqueta, rep in (("con SE", con), ("sin SE", sin)):
        if not rep or rep.get("error"):
            continue
        for r in (rep.get("rows") or []):
            filas.append({"conjunto": etiqueta, **r})
    if not filas:
        raise KitSinDatos((con or {}).get("motivo") or (con or {}).get("error")
                          or "No hay conjunto de entrenamiento con el que comparar.")
    nota_sub = (con or {}).get("nota_submuestreo")
    nota_prod = (con or {}).get("nota_produccion")
    cab = "\n".join("# " + l for l in [
        f"Comparación de los cinco modelos: {', '.join(COMPARISON_MODELS)}.",
        "MLP entra como CONTROL de complejidad, no como candidato de producción.",
        "Se reporta con SE y sin SE porque SE es función de las demás variables.",
        "validación: GroupKFold por pozo."]
        + ([nota_sub] if nota_sub else [])
        + ([nota_prod] if nota_prod else [])
        + [f"generado: {time.strftime('%Y-%m-%d %H:%M')}"])
    return cab + "\n" + pd.DataFrame(filas).to_csv(index=False)


def _kit_justificacion() -> str:
    rep = variable_justification_report()
    filas = []
    imp = rep.get("importancia")
    if imp:
        for k, v in (imp.items() if isinstance(imp, dict) else imp):
            filas.append({"seccion": "importancia de variables", "clave": k, "valor": v})
    for nombre, key in (("comparación con SE", "comparacion_con_se"),
                        ("comparación sin SE", "comparacion_sin_se")):
        sub = rep.get(key) or {}
        for r in (sub.get("rows") or []):
            filas.append({"seccion": nombre, "clave": r.get("modelo"),
                          "valor": r.get("r2_mean")})
    abl = rep.get("ablacion_cota") or {}
    for k, v in abl.items():
        if isinstance(v, (int, float)):
            filas.append({"seccion": "ablación de cota", "clave": k, "valor": v})
    if not filas:
        raise KitSinDatos("Sin modelo entrenado no hay importancias, comparación "
                          "ni ablación que reportar.")
    cab = "\n".join("# " + l for l in [
        "Reporte de justificación de variables (P3-3.9).",
        "Las coordenadas (X, Y, Z, cota) NO son predictoras: el yacimiento es "
        "estratiforme y la cota es proxy directo de litología. Solo aparecen "
        "como ablación explícita.",
        f"generado: {time.strftime('%Y-%m-%d %H:%M')}"])
    return cab + "\n" + pd.DataFrame(filas).to_csv(index=False)


def _kit_ablacion_cota() -> str:
    rep = cota_ablation_report()
    if not rep or rep.get("error"):
        raise KitSinDatos((rep or {}).get("error") or "Sin datos para la ablación.")
    # Los cuatro R² vienen como tupla (valor, motivo_si_falló): se abren para
    # que la tabla traiga el número Y el motivo cuando no lo hay.
    filas = []
    for k in ("dentro_caseron_sin_cota", "dentro_caseron_con_cota",
              "loco_sin_cota", "loco_con_cota"):
        v = rep.get(k)
        if isinstance(v, (list, tuple)) and len(v) == 2:
            filas.append({"clave": f"R2_{k}", "valor": v[0],
                          "detalle": v[1] if v[0] is None else ""})
    r2_ds = (rep.get("dentro_caseron_sin_cota") or (None,))[0]
    r2_dc = (rep.get("dentro_caseron_con_cota") or (None,))[0]
    r2_ls = (rep.get("loco_sin_cota") or (None,))[0]
    r2_lc = (rep.get("loco_con_cota") or (None,))[0]
    if None not in (r2_ds, r2_dc, r2_ls, r2_lc):
        filas.append({"clave": "delta_dentro_por_agregar_cota",
                      "valor": round(r2_dc - r2_ds, 4),
                      "detalle": "cuánto SUBE el R² dentro del caserón al agregar cota"})
        filas.append({"clave": "delta_loco_por_agregar_cota",
                      "valor": round(r2_lc - r2_ls, 4),
                      "detalle": "cuánto CAE el R² entre caserones al agregar cota"})
    for k, v in rep.items():
        if isinstance(v, (int, float, str, bool)) and k not in ("error",):
            filas.append({"clave": k, "valor": v, "detalle": ""})
    if rep.get("caserones"):
        filas.append({"clave": "caserones", "valor": ", ".join(rep["caserones"]),
                      "detalle": "grupos de la LOCO-CV"})
    if not filas:
        raise KitSinDatos("La ablación no produjo métricas.")
    cab = "\n".join("# " + l for l in [
        "Ablación de cota: cuánto cambia el modelo al AGREGAR la cota como "
        "predictora, dentro de un caserón y entre caserones (LOCO-CV).",
        "No es una configuración admisible: es la medición de por qué la "
        "prohibición existe. Si agregar cota sube el R² dentro del caserón y "
        "lo hunde entre caserones, la cota está memorizando el yacimiento.",
        f"generado: {time.strftime('%Y-%m-%d %H:%M')}"])
    return cab + "\n" + pd.DataFrame(filas).to_csv(index=False)


def _kit_resumen_bloques() -> str:
    rep = block_model_summary()
    if rep.get("status") != "ok":
        raise KitSinDatos(rep.get("motivo") or "Sin modelo de bloques.")
    filas = [{"nivel": "banda", "clave": k, **v} for k, v in rep["por_banda"].items()]
    for c, d in (rep.get("por_caseron") or {}).items():
        filas.append({"nivel": "caseron", "clave": c, "n_bloques": d["n_bloques"],
                      "volumen_m3": d["volumen_m3"],
                      "confianza_mediana": None, "ucs_mediana": None,
                      "di_mediana": None, "cobertura": d["cobertura"],
                      "n_vacios": d["n_vacios"]})
    cab = "\n".join("# " + l for l in [
        f"{TERMINOLOGIA_C} — resumen del modelo de bloques por banda ISRM y por caserón.",
        f"bloques con valor: {rep['n_bloques']} · vacíos: {rep['n_vacios']}"]
        + ([rep["cobertura_advertencia"]] if rep.get("cobertura_advertencia") else
           [f"cobertura del encajonado: {rep['cobertura']*100:.1f}%"])
        + [f"generado: {time.strftime('%Y-%m-%d %H:%M')}"])
    return cab + "\n" + pd.DataFrame(filas).to_csv(index=False)


def _kit_fig_3d():
    if not wells and not layers:
        raise KitSinDatos("Sin pozos ni mallas cargadas no hay vista 3D.")
    return build_3d_figure()


def _kit_fig_di():
    cand = [w for w in wells.values() if any(p.di is not None for p in w.points)]
    if not cand:
        raise KitSinDatos("Ningún pozo tiene DI calculado: correr compute_di().")
    # El pozo más largo con DI: es el perfil más legible como figura.
    w = max(cand, key=lambda w: len(w.points))
    return build_di_figure(w)


def _kit_fig_di_sensibilidad():
    cand = [w for w in wells.values() if len(w.points) >= max(DI_SENSITIVITY_WINDOWS)]
    if not cand:
        raise KitSinDatos("Ningún pozo alcanza el largo mínimo para recalcular el "
                          f"DI con las ventanas {DI_SENSITIVITY_WINDOWS}.")
    w = max(cand, key=lambda w: len(w.points))
    return build_di_sensitivity_figure(di_sensitivity_analysis(w))


def _kit_indicador_di() -> str:
    """(Kit) Indicador de cuán bien el DI describe el macizo."""
    ind = di_quality_indicator()
    if ind.get("status") != "ok":
        raise KitSinDatos(ind.get("motivo") or "Sin pares testigo↔MWD.")
    filas = [{"clave": k, "valor": ind[k]} for k in
             ("variante", "n_pares", "n_sondajes", "radio_m", "rho",
              "mae_rqd", "rmse_rqd", "sesgo_rqd")]
    filas.append({"clave": "veredicto", "valor": ind["veredicto"]})
    cab = "\n".join("# " + l for l in [
        "¿Qué tan bien describe el DI al macizo?",
        ind["encuadre"], ind["sesgo_lectura"],
        f"generado: {time.strftime('%Y-%m-%d %H:%M')}"])
    return cab + "\n" + pd.DataFrame(filas).to_csv(index=False)


def _kit_csv_o_motivo(fn, motivo_vacio: str, encabezado: str = ""):
    """
    Envuelve un exportador ya existente. Los de la aplicación no son
    uniformes: unos devuelven el CSV como texto (con su encuadre en
    comentarios) y otros devuelven el DataFrame crudo, porque alimentan el
    botón de descarga de la UI. Acá se aceptan los dos y en ambos casos se
    distingue "vacío" —que se declara con su motivo— de "con filas".
    """
    def _gen():
        salida = fn()
        if isinstance(salida, pd.DataFrame):
            if salida.empty:
                raise KitSinDatos(motivo_vacio)
            cab = ("\n".join("# " + l for l in
                              [encabezado, f"generado: {time.strftime('%Y-%m-%d %H:%M')}"]
                              if l) + "\n") if encabezado else ""
            return cab + salida.to_csv(index=False)
        txt = salida or ""
        cuerpo = [l for l in txt.splitlines() if l and not l.startswith("#")]
        if len(cuerpo) <= 1:
            comentario = next((l[1:].strip() for l in txt.splitlines()
                               if l.startswith("#")), "")
            raise KitSinDatos(comentario or motivo_vacio)
        return txt
    return _gen


def _kit_dxf_bloques(path: str) -> str:
    rep = interpolate_block_model()
    if rep.get("status") != "ok":
        raise KitSinDatos(rep.get("motivo") or "Sin modelo de bloques.")
    return export_block_model_dxf(rep, path)


# ─── EL ÍNDICE DECLARADO ──────────────────────────────────────────────────────
# Los identificadores viven acá y solo acá. Agregar un ítem es añadir una fila
# con un identificador NUEVO; renumerar los existentes rompe las referencias
# del texto de la memoria y por eso no se hace.

KIT_CAP5: Tuple[Dict, ...] = (
    {"id": "T5.1", "seccion": "5.1 Vocabulario y bandas de UCS",
     "titulo": "Registro de vocabulario y bandas de UCS",
     "tipo": "tabla", "generador": "export_vocabulary_csv"},
    {"id": "T5.2", "seccion": "5.1 Vocabulario y bandas de UCS",
     "titulo": "Matriz de traslape de bandas de UCS (ambos criterios)",
     "tipo": "tabla", "generador": "_kit_traslape"},
    {"id": "T5.3", "seccion": "5.2 Datos y escala",
     "titulo": "Composición del conjunto de entrenamiento",
     "tipo": "tabla", "generador": "_kit_composicion"},
    {"id": "F5.1", "seccion": "5.2 Datos y escala",
     "titulo": "Vista 3D de pozos y mallas",
     "tipo": "figura", "generador": "_kit_fig_3d"},
    {"id": "F5.2", "seccion": "5.3 Índice de discontinuidad",
     "titulo": "Perfil de DI de un pozo representativo",
     "tipo": "figura", "generador": "_kit_fig_di"},
    {"id": "F5.3", "seccion": "5.3 Índice de discontinuidad",
     "titulo": "Sensibilidad de la ventana del DI",
     "tipo": "figura", "generador": "_kit_fig_di_sensibilidad"},
    {"id": "T5.4", "seccion": "5.3 Índice de discontinuidad",
     "titulo": "Qué tan bien describe el DI al macizo",
     "tipo": "tabla", "generador": "_kit_indicador_di"},
    {"id": "T5.5", "seccion": "5.4 Modelo de caracterización",
     "titulo": "Matriz de correlación entre variables MWD",
     "tipo": "tabla", "generador": "_kit_correlacion"},
    {"id": "T5.6", "seccion": "5.4 Modelo de caracterización",
     "titulo": "Comparación de los cinco modelos",
     "tipo": "tabla", "generador": "_kit_comparacion_modelos"},
    {"id": "T5.7", "seccion": "5.4 Modelo de caracterización",
     "titulo": "Reporte de justificación de variables",
     "tipo": "tabla", "generador": "_kit_justificacion"},
    {"id": "T5.8", "seccion": "5.4 Modelo de caracterización",
     "titulo": "Ablación de cota dentro y entre caserones",
     "tipo": "tabla", "generador": "_kit_ablacion_cota"},
    {"id": "T5.9", "seccion": "5.4 Modelo de caracterización",
     "titulo": "Validación por pozo (GroupKFold)",
     "tipo": "tabla", "generador": "export_validation_csv"},
    {"id": "T5.10", "seccion": "5.5 Concordancia con el modelo geológico",
     "titulo": "Diagnósticos de concordancia (C.3 a C.7)",
     "tipo": "tabla", "generador": "export_concordance_csv"},
    {"id": "T5.11", "seccion": "5.6 Coherencia energía específica contra UCS",
     "titulo": "Coherencia SE contra UCS por dominio",
     "tipo": "tabla", "generador": "export_se_ucs_coherence_csv"},
    {"id": "T5.12", "seccion": "5.7 Respuesta a la presión de percusión",
     "titulo": "Curvas de respuesta a PP por dominio",
     "tipo": "tabla", "generador": "export_pp_curves_csv"},
    {"id": "T5.13", "seccion": "5.8 Discriminación de discontinuidades",
     "titulo": "Discriminador fractura contra contacto",
     "tipo": "tabla", "generador": "export_discriminator_csv"},
    {"id": "T5.14", "seccion": "5.8 Discriminación de discontinuidades",
     "titulo": "RQD_MWD por pozo y por caserón",
     "tipo": "tabla", "generador": "export_rqd_mwd_csv"},
    {"id": "T5.15", "seccion": "5.9 Modelo de bloques",
     "titulo": "Modelo de bloques: X, Y, Z, tamaño, UCS, DI, confianza",
     "tipo": "tabla", "generador": "export_block_model_csv"},
    {"id": "T5.16", "seccion": "5.9 Modelo de bloques",
     "titulo": "Resumen del modelo de bloques por banda ISRM",
     "tipo": "tabla", "generador": "_kit_resumen_bloques"},
    {"id": "T5.17", "seccion": "5.9 Modelo de bloques",
     "titulo": "Predicciones punto a punto",
     "tipo": "tabla", "generador": "export_predictions_csv"},
    {"id": "D5.1", "seccion": "5.9 Modelo de bloques",
     "titulo": "Modelo de bloques en DXF con capas por banda",
     "tipo": "dxf", "generador": "_kit_dxf_bloques"},
)

KIT_EXT = {"tabla": ".csv", "csv": ".csv", "dxf": ".dxf"}
# Tamaño sobre el cual el índice avisa: un archivo más grande que esto no se
# adjunta a un correo ni se pega en un documento.
KIT_AVISO_MB = 20.0
KIT_INDICE_CSV = "INDICE_capitulo5.csv"
KIT_INDICE_MD = "INDICE_capitulo5.md"

# Exportadores que ya devuelven CSV y cuyo "vacío" hay que interpretar.
_KIT_CSV_DIRECTOS = {
    "export_vocabulary_csv": "El registro de vocabulario está vacío.",
    "export_validation_csv": ("No se corrió la validación multipozo de posición "
                              "de mallas: sin resultados no hay detalle por pozo."),
    "export_concordance_csv": "Sin contraste disponible no hay concordancia.",
    "export_se_ucs_coherence_csv": "Sin dominios con UCS de laboratorio.",
    "export_pp_curves_csv": "Sin puntos con dominio para construir curvas.",
    "export_discriminator_csv": "Sin picos de DI que clasificar.",
    "export_rqd_mwd_csv": "Sin pozos con DI calculado.",
    "export_block_model_csv": "Sin modelo de bloques.",
    "export_predictions_csv": ("Sin puntos MWD cargados no hay predicciones que "
                               "exportar."),
}

# Encuadre para los exportadores que devuelven el DataFrame crudo y por lo
# tanto no traen encabezado propio.
_KIT_ENCABEZADOS = {
    "export_validation_csv": ("Validación multipozo de la posición de cada malla: "
                              "offset entre el cruce pozo-malla y el pico de DI "
                              "más cercano."),
    "export_predictions_csv": ("Predicciones punto a punto. ucs_matriz es la UCS "
                               "de la matriz rocosa SIN discontinuidades; ucs_ml "
                               "es la predicción cruda, con su intervalo p10-p90."),
}


def _kit_slug(texto: str) -> str:
    s = _norm_txt(texto).replace(" ", "_")
    return re.sub(r"[^a-z0-9_]+", "", s)[:60].strip("_")


def _kit_nombre(item: Dict, ext: str) -> str:
    return f"{item['id'].replace('.', '_')}_{_kit_slug(item['titulo'])}{ext}"


def build_chapter5_kit(outdir: str, fmt_figura: str = "auto") -> Dict:
    """
    (10.1) Genera el kit completo del Capítulo 5 en `outdir` y devuelve el
    índice: cada ítem con su identificador, su sección, su archivo y su
    estado.

    Todo ítem declarado en KIT_CAP5 aparece en el índice. Los que no se
    pueden generar salen con estado "sin_datos" y su motivo, y NO dejan
    archivo a medias en el disco.

    `fmt_figura`: "auto" intenta PNG y cae a HTML si falta el motor de
    imagen; "html" o "png" fuerzan uno. La caída se declara en el índice —
    nunca es silenciosa.
    """
    os.makedirs(outdir, exist_ok=True)
    items = []
    for it in KIT_CAP5:
        registro = {"id": it["id"], "seccion": it["seccion"], "titulo": it["titulo"],
                    "tipo": it["tipo"], "archivo": None, "estado": "sin_datos",
                    "motivo": None, "nota": None, "tamano_MB": None}
        gen = globals().get(it["generador"])
        if gen is None:
            registro["motivo"] = (f"El generador '{it['generador']}' no existe en "
                                  "este build.")
            items.append(registro); continue
        try:
            if it["tipo"] == "dxf":
                nombre = _kit_nombre(it, ".dxf")
                gen(os.path.join(outdir, nombre))
                registro.update(archivo=nombre, estado="ok")
            elif it["tipo"] == "figura":
                fig = gen()
                nombre_png = _kit_nombre(it, ".png")
                nombre_html = _kit_nombre(it, ".html")
                escrito = None
                if fmt_figura in ("auto", "png"):
                    try:
                        fig.write_image(os.path.join(outdir, nombre_png),
                                        width=1400, height=900, scale=2)
                        escrito = nombre_png
                    except Exception as e:
                        if fmt_figura == "png":
                            raise
                        registro["nota"] = (f"PNG no disponible ({type(e).__name__}); "
                                            "se exportó HTML interactivo. Instalar "
                                            "kaleido para obtener PNG.")
                if escrito is None:
                    fig.write_html(os.path.join(outdir, nombre_html),
                                   include_plotlyjs="cdn")
                    escrito = nombre_html
                registro.update(archivo=escrito, estado="ok")
            else:
                if it["generador"] in _KIT_CSV_DIRECTOS:
                    texto = _kit_csv_o_motivo(
                        gen, _KIT_CSV_DIRECTOS[it["generador"]],
                        _KIT_ENCABEZADOS.get(it["generador"], ""))()
                else:
                    texto = gen()
                nombre = _kit_nombre(it, KIT_EXT.get(it["tipo"], ".csv"))
                with open(os.path.join(outdir, nombre), "w", encoding="utf-8") as fh:
                    fh.write(texto)
                registro.update(archivo=nombre, estado="ok")
        except KitSinDatos as e:
            registro["motivo"] = str(e)
        except Exception as e:
            registro["estado"] = "error"
            registro["motivo"] = f"{type(e).__name__}: {e}"
        if registro["archivo"]:
            mb = os.path.getsize(os.path.join(outdir, registro["archivo"])) / 1e6
            registro["tamano_MB"] = round(mb, 2)
            # Una figura de decenas de MB no se puede mandar por correo ni
            # pegar en un documento. Se genera igual, pero se avisa.
            if mb > KIT_AVISO_MB:
                if it["tipo"] == "figura":
                    aviso = (f"{mb:.0f} MB: pesado para adjuntar. Un HTML interactivo "
                             "embebe toda la geometría de las mallas. Instalar "
                             "kaleido produce el PNG, mucho más liviano, sin "
                             "cambiar la figura.")
                else:
                    aviso = (f"{mb:.0f} MB: pesado para adjuntar. Es la tabla "
                             "completa, un registro por punto MWD; para el texto "
                             "de la memoria van los resúmenes, no esta.")
                registro["nota"] = (registro["nota"] + " " + aviso
                                    if registro["nota"] else aviso)
        items.append(registro)

    rep = {
        "items": items,
        "n_generados": sum(1 for i in items if i["estado"] == "ok"),
        "n_fallidos": sum(1 for i in items if i["estado"] != "ok"),
        "outdir": outdir,
        "generado": time.strftime("%Y-%m-%d %H:%M"),
        "procedencia": training_provenance(),
        "terminologia": TERMINOLOGIA_C,
        "indice_csv": KIT_INDICE_CSV, "indice_md": KIT_INDICE_MD,
    }
    with open(os.path.join(outdir, KIT_INDICE_CSV), "w", encoding="utf-8") as fh:
        fh.write(export_kit_index_csv(rep))
    with open(os.path.join(outdir, KIT_INDICE_MD), "w", encoding="utf-8") as fh:
        fh.write(export_kit_index_md(rep))
    return rep


def export_kit_index_csv(rep: Dict) -> str:
    """(10.2) Índice del kit como CSV: archivo → sección del capítulo."""
    df = pd.DataFrame([{k: i[k] for k in
                        ("id", "seccion", "titulo", "tipo", "archivo", "estado",
                         "tamano_MB", "motivo", "nota")}
                       for i in rep["items"]])
    cab = "\n".join("# " + l for l in [
        f"Kit del Capítulo 5 — {rep['terminologia']}.",
        f"generados: {rep['n_generados']} · no generados: {rep['n_fallidos']} "
        f"de {len(rep['items'])} ítem(s) declarados.",
        "Todo ítem declarado aparece acá, generado o no. Un ítem sin archivo "
        "trae su motivo: nada falta en silencio.",
        f"generado: {rep['generado']}"])
    return cab + "\n" + df.to_csv(index=False)


def export_kit_index_md(rep: Dict) -> str:
    """(10.3) Índice del kit como Markdown, para pegar en el texto."""
    L = [f"# Kit de resultados — Capítulo 5", "",
         f"*{rep['terminologia']}.*", "",
         f"Generado {rep['generado']}. "
         f"{rep['n_generados']} de {len(rep['items'])} ítem(s) producidos; "
         f"{rep['n_fallidos']} no se pudieron generar y se listan igual, con su "
         "motivo.", ""]
    prov = rep.get("procedencia") or {}
    if prov:
        L += ["## Procedencia", ""]
        for k, v in prov.items():
            L.append(f"- **{k}**: {v}")
        L.append("")
    seccion_actual = None
    for i in rep["items"]:
        if i["seccion"] != seccion_actual:
            seccion_actual = i["seccion"]
            L += ["", f"## {seccion_actual}", "",
                  "| Id | Título | Tipo | Archivo | Estado |",
                  "|---|---|---|---|---|"]
        archivo = f"`{i['archivo']}`" if i["archivo"] else "—"
        estado = "✅" if i["estado"] == "ok" else f"⚠ {i['estado']}"
        L.append(f"| {i['id']} | {i['titulo']} | {i['tipo']} | {archivo} | {estado} |")
    faltantes = [i for i in rep["items"] if i["estado"] != "ok"]
    if faltantes:
        L += ["", "## Ítems no generados", ""]
        for i in faltantes:
            L.append(f"- **{i['id']}** {i['titulo']} — {i['motivo']}")
    notas = [i for i in rep["items"] if i.get("nota")]
    if notas:
        L += ["", "## Notas de formato", ""]
        for i in notas:
            L.append(f"- **{i['id']}** — {i['nota']}")
    return "\n".join(L) + "\n"


# Campos por los que se puede ordenar la lista de sondajes. Vive acá, antes
# del layout, porque la cabecera del modal de sondajes lo usa al construirse.
_DH_SORT_FIELDS = [
    ("holeid", "Hole ID"), ("banda", "Banda"), ("estado", "Estado"),
    ("metros_dentro", "Metros dentro"), ("n_estructuras", "N° estructuras"),
    ("rqd_mediana", "RQD mediana"), ("rmr_mediana", "RMR mediana"),
    ("dist_min_m", "Distancia mín."),
]

# ─── APP DASH ─────────────────────────────────────────────────────────────────
# (P1) Sembrar el registro de vocabulario ANTES de construir el layout: el
# contador de pendientes y el panel de vocabulario lo leen al renderizar.
seed_attribute_registry()
seed_di_variants()
seed_param_registry()
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
        # (Corrección) Los controles de orden viven ACÁ, en la cabecera
        # estática, y no dentro del cuerpo del modal. Estando dentro del
        # cuerpo no existían mientras el modal estaba cerrado, y el callback
        # que ABRE el modal los pedía como Input: Dash no puede disparar un
        # callback cuyos Input no existen en el layout, así que el botón
        # mostraba "6/11 sondajes" y no abría nada.
        html.Div([
            dbc.Row([
                dbc.Col([html.Small("Ordenar por",
                                    style={"color": "#888", "display": "block"}),
                         dcc.Dropdown(id="dh-sort-field",
                                      options=[{"label": l, "value": k}
                                               for k, l in _DH_SORT_FIELDS],
                                      value="holeid", clearable=False,
                                      style={"fontSize": "10px"})], width=8),
                dbc.Col([html.Small("Orden",
                                    style={"color": "#888", "display": "block"}),
                         dbc.Checklist(id="dh-sort-desc",
                                       options=[{"label": " desc", "value": 1}],
                                       value=[], switch=True,
                                       style={"fontSize": "10px"})], width=4),
            ], className="g-2"),
        ], style={"padding": "0 16px 8px"}),
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
            # (CRUD) Baja del atributo. delete_attribute() se niega si está en
            # uso o si tiene subunidades; el aviso vuelve al toast.
            dbc.Button("🗑 Eliminar", id={"type": "attr-del-btn", "attr": a.id},
                       size="sm", color="danger", outline=True,
                       style={"fontSize": "10px", "marginLeft": "6px"}),
        ], className="mt-1"),
        html.Small(a.notas, style={"color": "#666", "fontSize": "9px", "display": "block",
                                   "marginTop": "3px"}) if a.notas else None,
    ], style={"background": "transparent", "borderBottom": "1px solid #222", "padding": "8px 10px"})


def _attr_alta_form():
    """
    (CRUD) Alta de un atributo canónico sin tocar el código. El registro se
    siembra con la Tabla 3.2 de Karzulovic —cinco unidades de MPC—, pero
    Pucobre opera tres faenas con litologías distintas: sin esto, llevar la
    plataforma a otra faena exige un programador.

    Los campos de banda de UCS se ofrecen siempre, pero el backend RECHAZA
    la banda si el rol no la lleva (A.1): la validación vive en
    create_attribute, no en el componente.
    """
    unidades_opts = [{"label": f"{a.id} — {a.nombre_oficial}", "value": a.id}
                     for a in sorted(attr_registry.values(), key=lambda x: x.id)
                     if a.nivel == "unidad"]
    fila = lambda lbl, comp, w: dbc.Col(
        [html.Small(lbl, style={"color": "#888", "fontSize": "9px", "display": "block"}), comp],
        width=w)
    inp = lambda f, **kw: dbc.Input(id={"type": "nuevo-attr", "field": f}, size="sm",
                                    style={"fontSize": "10px"}, **kw)
    return [
        dbc.Row([
            fila("Id (código de la malla)", inp("id", placeholder="Ka"), 3),
            fila("Nombre oficial", inp("nombre_oficial", placeholder="Calizas Fm. Abundancia"), 5),
            fila("Rol", dcc.Dropdown(id={"type": "nuevo-attr", "field": "rol"},
                                     options=[{"label": r, "value": r} for r in ATTR_ROLES],
                                     value="litologia", clearable=False,
                                     style={"fontSize": "10px"}), 4),
        ], className="g-1"),
        dbc.Row([
            fila("Nivel", dcc.Dropdown(id={"type": "nuevo-attr", "field": "nivel"},
                                       options=[{"label": "unidad", "value": "unidad"},
                                                {"label": "subunidad", "value": "subunidad"}],
                                       value="unidad", clearable=False,
                                       style={"fontSize": "10px"}), 3),
            fila("Padre (solo subunidad)",
                 dcc.Dropdown(id={"type": "nuevo-attr", "field": "padre"},
                              options=unidades_opts, placeholder="—",
                              style={"fontSize": "10px"}), 5),
            fila("Calidad del ancla",
                 dcc.Dropdown(id={"type": "nuevo-attr", "field": "calidad"},
                              options=[{"label": f"{k} · {v}", "value": k}
                                       for k, v in QUALITY_LABELS.items()],
                              value=0, clearable=False, style={"fontSize": "10px"}), 4),
        ], className="g-1 mt-1"),
        dbc.Row([
            fila("UCS mín [MPa]", inp("ucs_min", type="number"), 2),
            fila("UCS máx [MPa]", inp("ucs_max", type="number"), 2),
            fila("UCS media [MPa]", inp("ucs_media", type="number"), 2),
            fila("mi", inp("mi", type="number"), 2),
            fila("γ [t/m³]", inp("densidad", type="number"), 2),
        ], className="g-1 mt-1"),
        dbc.Row([
            fila("Fuente (de dónde sale la banda)",
                 inp("fuente", placeholder="informe, tabla, campaña de ensayo…"), 12),
        ], className="g-1 mt-1"),
        html.Div([
            dbc.Button("➕ Registrar atributo", id="btn-nuevo-attr", size="sm",
                       color="success", outline=True, style={"fontSize": "10px"}),
            html.Small("  La banda de UCS solo aplica al rol litología; los límites "
                       "físicos [0, 450] MPa se rechazan, no se truncan.",
                       style={"color": "#666", "fontSize": "9px"}),
        ], className="mt-2"),
        html.Div(id="nuevo-attr-msg", className="mt-1"),
    ]


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
        card("➕ Registrar litología o estructura nueva", _attr_alta_form()),

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
              Input("btn-nuevo-attr", "n_clicks"),
              State({"type": "nuevo-attr", "field": ALL}, "value"),
              State({"type": "nuevo-attr", "field": ALL}, "id"),
              State("refresh", "data"), prevent_initial_call=True)
def on_attr_create(n, values, ids, ref):
    """
    (CRUD) Alta de un atributo canónico desde la interfaz. Toda la validación
    vive en create_attribute(), no aquí: el motivo del rechazo se muestra tal
    cual lo declara el backend, para que el usuario sepa QUÉ corregir en vez
    de recibir un "no se pudo".
    """
    if not n: return no_update, no_update, no_update
    campos = {i["field"]: v for v, i in zip(values, ids)}
    aid = (campos.pop("id", "") or "").strip()
    nombre = (campos.pop("nombre_oficial", "") or "").strip()
    rol = campos.pop("rol", "litologia") or "litologia"
    nivel = campos.pop("nivel", "unidad") or "unidad"
    padre = campos.pop("padre", None) or None
    # Los campos vacíos se omiten en vez de mandarse como "" o 0: un vacío es
    # "no informado", no "cero".
    limpios = {k: v for k, v in campos.items() if v is not None and v != ""}
    try:
        a = create_attribute(aid, nombre, rol=rol, nivel=nivel, padre=padre, **limpios)
    except (ValueError, KeyError, TypeError) as e:
        return no_update, f"🚫 No se registró: {e}", True
    build_domain_index()
    ancla = a.ucs_ancla()
    detalle = (f"UCS ancla {ancla:g} MPa · PI ×{a.pi_factor():.2f}"
               if ancla is not None and a.pi_factor() is not None
               else ("sin banda de UCS — bloqueará el entrenamiento hasta asignarla"
                     if a.usa_banda_ucs() else f"rol {rol}: no lleva banda de UCS"))
    return ref + 1, f"✅ «{aid}» ({nombre}) registrado · {detalle}.", True


@app.callback(Output("refresh", "data", allow_duplicate=True),
              Output("toast", "children", allow_duplicate=True),
              Output("toast", "is_open", allow_duplicate=True),
              Input({"type": "attr-del-btn", "attr": ALL}, "n_clicks"),
              State("refresh", "data"), prevent_initial_call=True)
def on_attr_delete(clicks, ref):
    """
    (CRUD) Baja de un atributo. El primer clic INTENTA la baja segura; si el
    atributo está en uso, delete_attribute se niega y explica por qué. La
    baja forzada no se ofrece desde aquí: perder el dominio de miles de
    puntos clasificados no puede ser un clic accidental en una lista.
    """
    trig = callback_context.triggered_id
    if not isinstance(trig, dict) or not any(c for c in clicks if c):
        return no_update, no_update, no_update
    aid = trig["attr"]
    try:
        uso = delete_attribute(aid)
    except ValueError as e:
        return no_update, f"🚫 {e}", True
    except KeyError as e:
        return no_update, f"🚫 {e}", True
    build_domain_index()
    extra = f" · alias arrastrados: {', '.join(uso['alias'])}" if uso["alias"] else ""
    return ref + 1, f"🗑 «{aid}» eliminado del registro{extra}.", True


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
        card(f"Pozos ({len(holes)})", [
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
    Input({"type":"vis-caseron","index":ALL},"value"),
    Input({"type":"vis-layer","index":ALL},"value"),
    Input({"type":"vis-well","index":ALL},"value"),
    Input({"type":"vis-dh","index":ALL},"value"),
    State({"type":"vis-caseron","index":ALL},"id"),
    State({"type":"vis-layer","index":ALL},"id"),
    State({"type":"vis-well","index":ALL},"id"),
    State({"type":"vis-dh","index":ALL},"id"),
)
def render_viewport(_, color_by, cas_vals, layer_vis_vals, well_vis_vals, dh_vals,
                    cas_ids, layer_ids, well_ids, dh_ids):
    """
    Único callback que toca la figura 3D. Se dispara solo cuando cambian datos
    (refresh), el color, o los checkboxes de visibilidad — nunca al navegar
    entre pasos del wizard. uirevision="viewport" (fijo) preserva cámara.

    El interruptor de CASERÓN manda sobre todo lo suyo; con el caserón
    encendido manda la casilla individual. La traducción vive en
    resolver_ocultos(), que es lo que se puede probar sin levantar Dash.
    """
    caserones_apagados = {cid["index"] for cid, v in zip(cas_ids, cas_vals) if not v}
    mallas_apagadas = {lid["index"] for lid, v in zip(layer_ids, layer_vis_vals) if not v}
    pozos_apagados = {wid["index"] for wid, v in zip(well_ids, well_vis_vals) if not v}
    sondajes_apagados = {did["index"] for did, v in zip(dh_ids, dh_vals) if not v}
    hidden_layers, hidden_wells = resolver_ocultos(
        caserones_apagados, mallas_apagadas, pozos_apagados, sondajes_apagados)
    return build_3d_figure(color_by, hidden_layers, hidden_wells)

SIN_CASERON = "— sin caserón asignado —"


def _caseron_de_sondaje(dh) -> Optional[str]:
    """
    Caserón de un sondaje: el de la malla más cercana que tenga uno asignado.
    Un sondaje no declara caserón por sí mismo — pertenece al que describe.
    """
    if dh.malla_cercana and dh.malla_cercana in layers:
        return layers[dh.malla_cercana].caseron
    return None


def _abanico_de_pozo(well) -> str:
    """
    Abanico de un tiro. Sale del plan_id del DQ, que es justamente lo que
    identifica el abanico perforado: la agrupación es AUTOMÁTICA y no hay que
    etiquetar nada a mano.
    """
    return _plan_short(well.plan_id) if well.plan_id else "— sin plan —"


def resolver_ocultos(caserones_apagados: set, mallas_apagadas: set,
                     pozos_apagados: set, sondajes_apagados: set):
    """
    Traduce el estado de las casillas del árbol a los dos conjuntos que
    entiende build_3d_figure: mallas ocultas y "pozos" ocultos (los sondajes
    viajan ahí con prefijo DH:: para no chocar con un pozo del mismo nombre).

    Un caserón apagado apaga TODO lo suyo sin que haya que destildar cada
    elemento; con el caserón encendido, manda la casilla individual.
    """
    ocultos_l = set(mallas_apagadas)
    ocultos_w = set(pozos_apagados)
    for hid in sondajes_apagados:
        ocultos_w.add(f"DH::{hid}")
    if caserones_apagados:
        for name, lay in layers.items():
            if (lay.caseron or SIN_CASERON) in caserones_apagados:
                ocultos_l.add(name)
        for wn, w in wells.items():
            if (getattr(w, "caseron", None) or SIN_CASERON) in caserones_apagados:
                ocultos_w.add(wn)
        for hid, dh in drillholes.items():
            if (_caseron_de_sondaje(dh) or SIN_CASERON) in caserones_apagados:
                ocultos_w.add(f"DH::{hid}")
    return ocultos_l, ocultos_w


def _fila_malla(name, layer, i, caseron_opts, lito_opts):
    _lito = layer_role_ids(layer).get("litologia")
    _a = attr_registry.get(_lito or "")
    badge = (dbc.Badge(_lito, color="success", className="ms-1") if _a
             else dbc.Badge("sin atributo", color="secondary", className="ms-1"))
    hijos = [html.Div([
        dbc.Checkbox(id={"type": "vis-layer", "index": name}, value=True,
                     style={"display": "inline-block", "marginRight": "6px"}),
        html.Small([html.Span("●", style={"color": PALETTE[i % len(PALETTE)],
                                          "marginRight": "4px"}),
                    name, badge], style={"fontSize": "11px"}),
    ], style={"display": "flex", "alignItems": "center"})]
    if caseron_opts:
        hijos.append(dbc.Row([
            dbc.Col(dcc.Dropdown(id={"type": "caseron-sel", "index": name},
                                 options=caseron_opts, value=layer.caseron,
                                 placeholder="Caserón…", clearable=True,
                                 style={"fontSize": "10px"}), width=6),
            dbc.Col(dcc.Dropdown(id={"type": "lito-alias", "index": name},
                                 options=lito_opts, value=layer.lito_alias,
                                 placeholder="Litología (alias)…", clearable=True,
                                 style={"fontSize": "10px"}), width=6),
        ], className="g-1", style={"marginTop": "3px"}))
    return dbc.ListGroupItem(hijos, style={"padding": "4px 8px",
                                           "background": "transparent",
                                           "border": "none"})


def _fila_pozo(wn, well):
    badge = ""
    if well.origin == "fallback_hole": badge = " ⚠ collar por hermano"
    elif well.origin == "tolerancia":
        badge = f" ⚠ collar aproximado (err {well.asignacion_err_pct}%)"
    elif well.origin == "manual": badge = " ✎ DQ asignado a mano"
    return dbc.ListGroupItem([html.Div([
        dbc.Checkbox(id={"type": "vis-well", "index": wn}, value=True,
                     style={"display": "inline-block", "marginRight": "6px"}),
        html.Small([html.Span("○", style={"color": "#5DCAA5", "marginRight": "4px"}), wn,
                    html.Span(badge, style={"color": "#F39C12", "fontSize": "10px",
                                            "marginLeft": "4px"})],
                   style={"fontSize": "11px"}),
        dbc.Button("📊", id={"type": "open-well-report", "index": wn}, size="sm",
                   color="link", style={"fontSize": "12px", "padding": "0 0 0 8px",
                                        "marginLeft": "auto"}),
    ], style={"display": "flex", "alignItems": "center"})],
        style={"padding": "2px 8px", "background": "transparent", "border": "none"})


def _fila_sondaje(hid, dh):
    col = ("#2ecc71" if dh.estado == "intersecta" else
           "#f1c40f" if dh.estado == "cercano" else "#7f8c8d")
    extra = f" · {dh.estado}" if dh.estado else ""
    return dbc.ListGroupItem([html.Div([
        dbc.Checkbox(id={"type": "vis-dh", "index": hid}, value=True,
                     style={"display": "inline-block", "marginRight": "6px"}),
        html.Small([html.Span("▬", style={"color": col, "marginRight": "4px"}), hid,
                    html.Span(extra, style={"color": "#888", "fontSize": "10px"})],
                   style={"fontSize": "11px"}),
    ], style={"display": "flex", "alignItems": "center"})],
        style={"padding": "2px 8px", "background": "transparent", "border": "none"})


def _carpeta(titulo, hijos, item_id):
    """Carpeta plegable. Sin hijos no se dibuja: una carpeta vacía es ruido."""
    if not hijos:
        return None
    return dbc.AccordionItem(dbc.ListGroup(hijos, flush=True),
                             title=titulo, item_id=item_id)


def _layer_tree():
    """
    Árbol por CASERÓN. Antes era una lista plana: con 619 pozos y 23 mallas de
    tres caserones, encontrar un abanico ahí es imposible y apagar un caserón
    entero para mirar otro, también.

    Cada caserón es una carpeta que se prende y apaga completa, y dentro trae
    tiros —agrupados por ABANICO, automáticamente desde el plan_id del DQ—,
    litología, estructuras y sondajes.
    """
    caseron_opts = [{"label": c, "value": c}
                    for c in sorted({w.caseron for w in wells.values() if w.caseron})]
    lito_opts = [{"label": a.id, "value": a.id}
                 for a in attr_registry.values() if a.rol == "litologia"]

    # Reparto por caserón. Nada se pierde: lo que no tiene caserón asignado va
    # a su propia carpeta en vez de desaparecer del árbol.
    por_cas: Dict[str, Dict] = {}

    def bolsa(cas):
        return por_cas.setdefault(cas or SIN_CASERON,
                                  {"mallas": [], "pozos": [], "sondajes": []})

    for i, (name, layer) in enumerate(layers.items()):
        bolsa(layer.caseron)["mallas"].append((i, name, layer))
    for wn, w in wells.items():
        bolsa(getattr(w, "caseron", None))["pozos"].append((wn, w))
    for hid, dh in drillholes.items():
        bolsa(_caseron_de_sondaje(dh))["sondajes"].append((hid, dh))

    if not por_cas:
        return html.Small("Sin datos.", style={"color": "#444", "fontSize": "10px"})

    # El caserón sin asignar va último: es la excepción, no el encabezado.
    orden = sorted(por_cas, key=lambda c: (c == SIN_CASERON, c))
    items = []
    for cas in orden:
        d = por_cas[cas]
        litos = [_fila_malla(name, lay, i, caseron_opts, lito_opts)
                 for i, name, lay in d["mallas"] if lay.kind == "litologia"]
        estrs = [_fila_malla(name, lay, i, caseron_opts, lito_opts)
                 for i, name, lay in d["mallas"] if lay.kind != "litologia"]

        por_abanico: Dict[str, list] = {}
        for wn, w in d["pozos"]:
            por_abanico.setdefault(_abanico_de_pozo(w), []).append((wn, w))
        abanicos = [
            _carpeta(f"{ab} ({len(lst)})",
                     [_fila_pozo(wn, w) for wn, w in sorted(lst)],
                     f"{cas}::ab::{ab}")
            for ab, lst in sorted(por_abanico.items())]
        tiros = ([dbc.Accordion([a for a in abanicos if a], start_collapsed=True,
                                flush=True, always_open=True)]
                 if abanicos else [])

        sondajes = [_fila_sondaje(hid, dh) for hid, dh in sorted(d["sondajes"])]

        sub = [c for c in (
            _carpeta(f"Tiros ({len(d['pozos'])})", tiros, f"{cas}::tiros"),
            _carpeta(f"Litología ({len(litos)})", litos, f"{cas}::lito"),
            _carpeta(f"Estructuras ({len(estrs)})", estrs, f"{cas}::estr"),
            _carpeta(f"Sondajes ({len(sondajes)})", sondajes, f"{cas}::son"),
        ) if c is not None]

        cabecera = html.Div([
            dbc.Checkbox(id={"type": "vis-caseron", "index": cas}, value=True,
                         style={"display": "inline-block", "marginRight": "6px"}),
            html.Small(html.B(cas), style={"fontSize": "11px"}),
            html.Small(f"  {len(d['pozos'])} tiros · {len(d['mallas'])} mallas"
                       f" · {len(d['sondajes'])} sondajes",
                       style={"color": "#888", "fontSize": "10px", "marginLeft": "6px"}),
        ], style={"display": "flex", "alignItems": "center",
                  "padding": "4px 2px", "borderTop": "1px solid #222"})
        items.append(html.Div([
            cabecera,
            dbc.Accordion(sub, start_collapsed=True, flush=True, always_open=True),
        ]))
    return html.Div(items)


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

for btn_id, upload_id in [("btn-dxf","up-dxf"), ("btn-xml","up-xml"),
                          ("btn-drillhole","up-drillhole")]:
    app.clientside_callback(
        f"""function(n){{if(n){{var e=document.querySelector('#{upload_id} input[type=file]');if(e)e.click();}}return window.dash_clientside.no_update;}}""",
        Output(btn_id,"n_clicks"), Input(btn_id,"n_clicks"), prevent_initial_call=True,
    )

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
    suma = wpp + wpd + wpf + wpr
    aviso_suma = ""
    if abs(suma - 1.0) > 0.02:
        aviso_suma = (f" ⚠ los pesos ingresados suman {suma:.3f} (no 1,0); "
                      "se normalizaron a 1 para la variante.")
    # El panel NO escribe sobre la convención: resuelve a qué variante
    # corresponde lo ingresado y la activa. Si son los valores de Fernández,
    # vuelve a la convención sola.
    try:
        activa = aplicar_di_config(window=int(window_v), threshold=float(thresh_v),
                                   weights={"pp": wpp, "pd": wpd, "pf": wpf, "pr": wpr})
    except (ValueError, TypeError) as e:
        return no_update, f"🚫 {e}", True
    compute_di()
    wz_state['step3']['di_computed'] = True
    all_pts = list(all_points())
    n_di = sum(1 for p in all_pts if p.di is not None)
    n_disc = sum(1 for p in all_pts if p.di is not None and p.di > di_threshold)
    origen = ("convención Fernández et al. 2023" if activa == DI_VARIANTE_CONVENCION
              else f"VARIANTE «{activa}» (la convención queda intacta)")
    return (ref+1, f"✅ DI: {n_di} pts · {n_disc} discontinuidades · {origen}.{aviso_suma}",
            True)

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
    activar_di(DI_VARIANTE_CONVENCION)
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
    Input("btn-save-project","n_clicks"), Input("btn-kit-cap5","n_clicks"),
    prevent_initial_call=True,
)
def on_export_trigger(n_dom, n_pred, n_val, n_proj, n_kit):
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
        kind = "validacion" if trig.get("type") == "val-export-btn" else None
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
        html.H6("Paso 2 — Limpieza", className="mb-3"),
        # (Simplificación) La "calibración de unidades" y el entrenamiento
        # preliminar salieron de acá. Dependían de un Excel de promedios por
        # tiro cuyo propósito nunca fue el que el paso suponía: multiplicar el
        # MWD por un factor derivado de esos promedios no corrige unidades,
        # reescala el dato crudo contra un agregado que ya lo contiene.
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
    Card "¿Qué tan bien describe el DI al macizo?" del Paso 3.

    Antes esto era "Validación independiente DI ↔ RQD": el RQD del Excel
    geomecánico contra el DI medio POR CASERÓN. Ese contraste no era factible
    —un promedio de caserón contra otro promedio de caserón, con cinco
    caserones, no valida nada— y además tenía el encuadre al revés. El testigo
    no es un contraste independiente: es el PATRÓN que ajusta los pesos para
    que el MWD calcule RQD, y ese cálculo extrapolado es el que después vale
    en todo el caserón.

    Así que la pregunta ya no es "¿coinciden dos fuentes?" sino "¿cuánto se
    aparta, en puntos de RQD, lo que calcula el MWD de lo que midió el
    testigo?".
    """
    ind = di_quality_indicator()
    titulo = "¿Qué tan bien describe el DI al macizo?"
    if ind.get("status") != "ok":
        return card(titulo, [
            dbc.Alert(ind.get("motivo") or "Sin pares testigo↔MWD todavía.",
                      color="secondary", style={"fontSize": "11px", "padding": "6px 10px"}),
            html.Small("Hacen falta sondajes con RQD en su tabla geomec y el DI "
                       "calculado.", style={"color": "#666", "fontSize": "10px"}),
        ])
    color = ("success" if ind["mae_rqd"] <= 10 and (ind["rho"] or 0) >= 0.4
             else "warning" if (ind["rho"] or 0) >= 0.4 else "danger")
    return card(titulo, [
        html.Small(ind["encuadre"],
                   style={"color": "#aaa", "display": "block", "marginBottom": "6px"}),
        dbc.Row([
            dbc.Col(dbc.Badge(f"error medio {ind['mae_rqd']:.1f} pts de RQD",
                              color=color), width="auto"),
            dbc.Col(dbc.Badge(f"ρ = {ind['rho']:+.2f}" if ind["rho"] is not None
                              else "ρ n/d", color="info"), width="auto"),
            dbc.Col(dbc.Badge(f"n={ind['n_pares']} pares · {ind['n_sondajes']} sondaje(s)",
                              color="secondary"), width="auto"),
        ], className="g-1 mb-2"),
        dbc.Alert(ind["veredicto"], color=color,
                  style={"fontSize": "11px", "padding": "6px 10px"}),
        html.Small(ind["sesgo_lectura"], style={"color": "#888", "fontSize": "10px"}),
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
