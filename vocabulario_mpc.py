"""
vocabulario_mpc.py — Asignaciones de vocabulario de las mallas DXF de Punta
del Cobre, confirmadas por el autor de la memoria.

Existe como archivo aparte y no como valores enterrados en el cargador para
que cada asignación quede TRAZABLE: qué texto de malla se mapeó a qué
atributo canónico, quién lo decidió y por qué. El registro de vocabulario es
lo que se publica como anexo de la memoria, y estas cuatro decisiones
determinan las etiquetas de UCS con las que entrena el modelo — una mal
asignada invalida el entrenamiento sin que ninguna métrica lo delate.

Aplicar con `aplicar_vocabulario_mpc()` DESPUÉS de sembrar el registro y
ANTES de cargar las mallas, para que resolve_or_note() las reconozca en vez
de mandarlas a la bandeja de pendientes.
"""

from typing import Dict, List

import geomech_wizard as gw

# Confirmado por Luciano San Martín (autor), sesión de carga de caserones.
_PROCEDENCIA = "confirmado por el autor en la carga de caserones reales"

# ── Litologías ───────────────────────────────────────────────────────────────
# texto de malla -> (atributo canónico, nota de la decisión)
LITOLOGIAS: Dict[str, tuple] = {
    "Kpcsb": ("Kpcsb_sedimentaria",
              "Resuelve la ambigüedad Marschik/Ortiz que el registro documenta: "
              "la malla entregada es la Brecha SEDIMENTARIA (subunidad, "
              "77,4-98,7 MPa), no la Brecha basal (unidad padre, sin banda). "
              + _PROCEDENCIA),
    "Kpcmix": ("Brecha_mixta",
               "Brecha mixta, 82,6-141,7 MPa (media 111,5, CV 0,212). " + _PROCEDENCIA),
    "Kpcs": ("Lutitas_normales",
             "La malla del Miembro Trinidad corresponde a la subunidad de "
             "Lutitas normales (126,0 MPa), no a la unidad padre, que no "
             "tiene banda propia. " + _PROCEDENCIA),
    "Lavas": ("Kpcli",
              "Lavas Inferiores. La asignación se corrobora con la "
              "estratigrafía: el informe geológico base sitúa Kpcli en la BASE "
              "de la columna (bajo el Albitófiro, base no expuesta) y Kpcls "
              "(Lavas Superiores) sobre el Miembro Trinidad; la malla Lavas.dxf "
              "de PCS_1043 tiene el Z medio MÁS BAJO de las seis mallas del "
              "caserón (320,4 m, contra Ka 413,6 · Kpcs 388,3 · Kpcsb 365,2 · "
              "Kpcmix 354,2), que es la posición de las Inferiores. "
              + _PROCEDENCIA),
}

# ── Bandas de UCS que NO vienen del registro prepoblado ─────────────────────
# El registro se siembra con la Tabla 3.2 de Karzulovic (2005), que solo
# caracteriza cinco unidades: Albitófiro, Brecha mixta, Brecha sedimentaria y
# las dos lutitas. El informe geológico base de Pucobre confirma que su anexo
# de ensayos cubre EXACTAMENTE esas cinco — ni las Lavas ni las Calizas de la
# Formación Abundancia tienen ensayo de laboratorio ahí.
#
# atributo -> (ucs_min, ucs_max, ucs_media, calidad, fuente)
BANDAS_UCS = {
    "Kpcli": (150.0, 230.0, 190.0, 3,
              "Rango aportado por el autor desde fuente propia (no está en el "
              "informe geológico base ni en la Tabla 3.2 de Karzulovic). "
              "Registrado con CALIDAD 3 (análogo del distrito) por no tener "
              "identificada la campaña de ensayo, el n de probetas ni la "
              "desviación: el intervalo de predicción se ensancha ×1,60 en "
              "consecuencia. Ajustar la calidad a 1 desde el panel de "
              "vocabulario en cuanto se identifique el informe de laboratorio."),
}


def aplicar_bandas_ucs(verbose: bool = True) -> List[tuple]:
    """
    Asigna las bandas de UCS que no trae el registro prepoblado. Cada una
    lleva calidad y fuente EXPLÍCITAS: una banda sin procedencia declarada
    es indistinguible de un número inventado, y el factor del intervalo de
    predicción depende de esa calidad.
    """
    puestas = []
    for attr_id, (lo, hi, media, calidad, fuente) in BANDAS_UCS.items():
        a = gw.attr_registry.get(attr_id)
        if a is None:
            continue
        a.ucs_min, a.ucs_max, a.ucs_media = lo, hi, media
        a.calidad = calidad
        a.fuente = fuente
        puestas.append((attr_id, lo, hi, media, calidad))
        if verbose:
            print(f"  {attr_id:10s} UCS {lo:g}-{hi:g} (media {media:g}) "
                  f"calidad {calidad} · PI ×{a.pi_factor():.2f}")
    return puestas

# ── Pendientes de resolver ───────────────────────────────────────────────────
# No se asignan a nada: sin atributo canónico van a la bandeja de pendientes,
# que es exactamente donde deben estar hasta que exista el dato.
PENDIENTES: Dict[str, str] = {
    "Ka": "Calizas. No corresponde a Kfa (Albitófiro) pese al parecido del "
          "código — la colisión Fk↔Kfa que el registro documenta es "
          "precisamente esta clase de trampa. A la espera del informe "
          "geológico base para registrar el atributo con su banda de UCS.",
}


def aplicar_vocabulario_mpc(verbose: bool = True) -> Dict[str, List]:
    """
    Registra los alias de malla confirmados. Devuelve un reporte con lo
    aplicado, lo que quedó pendiente, y las litologías que quedan SIN banda
    de UCS utilizable (que bloquearán el entrenamiento hasta resolverse).
    """
    aplicar_bandas_ucs(verbose=verbose)
    aplicados, faltantes, sin_banda = [], [], []
    for texto, (attr_id, nota) in LITOLOGIAS.items():
        a = gw.attr_registry.get(attr_id)
        if a is None:
            faltantes.append((texto, attr_id))
            continue
        gw.register_alias(texto, {"litologia": attr_id}, "dxf_layer")
        aplicados.append((texto, attr_id, a.ucs_ancla()))
        if not a.tiene_banda_ucs() or a.calidad == 0:
            sin_banda.append((texto, attr_id))
        if nota and nota not in (a.notas or ""):
            a.notas = ((a.notas or "") + "  " + nota).strip()
    if verbose:
        for texto, attr_id, ucs in aplicados:
            marca = "⚠ SIN BANDA" if any(t == texto for t, _ in sin_banda) else f"UCS={ucs}"
            print(f"  {texto:10s} -> {attr_id:22s} {marca}")
        for texto, motivo in PENDIENTES.items():
            print(f"  {texto:10s} -> PENDIENTE: {motivo.split('.')[0]}.")
    return {"aplicados": aplicados, "faltantes": faltantes,
            "sin_banda": sin_banda, "pendientes": list(PENDIENTES)}
