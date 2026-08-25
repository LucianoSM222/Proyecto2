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
              "Lavas Inferiores. ATENCIÓN: Kpcli está en el registro con "
              "calidad 0 y SIN banda de UCS, así que sus puntos no pueden "
              "etiquetar y la litología bloquea el entrenamiento hasta que se "
              "le asigne banda o se la excluya explícitamente. " + _PROCEDENCIA),
}

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
