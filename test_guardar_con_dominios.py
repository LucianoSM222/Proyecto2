"""Guardar el proyecto DESPUÉS de agrupar dominios.

Cada grupo de `domain_groups` lleva en `pts` los MWDPoint que lo forman, y
`save_project` volcaba el grupo entero a JSON: guardar reventaba con
«Object of type MWDPoint is not JSON serializable» en cuanto existía un solo
dominio. El grupo se guarda sin `pts`; la pertenencia viaja en `p.grupo`.
"""
import os, tempfile
import geomech_wizard as gw


def test_guardar_tras_agrupar_dominios():
    gw.domain_groups.clear()
    p = gw.MWDPoint(largo=1.0, vel=1.0, pp=200.0, pa=60.0, pd=75.0, pr=45.0, pf=8.0, se=300.0, t=0.0)
    gw.domain_groups.append({"id": "G1", "lito": "Kpcli", "estructura": None, "ucsMean": 160.0,
                             "diMean": 0.6, "n": 1, "count": 1, "pts": [p]})
    ruta = os.path.join(tempfile.mkdtemp(), "p.gwz")
    try:
        gw.save_project(ruta)
        assert os.path.getsize(ruta) > 0
        assert "pts" in gw.domain_groups[0], "guardar no debe mutar el estado en memoria"
        gw.load_project(ruta)
        assert gw.domain_groups and gw.domain_groups[0]["id"] == "G1"
        assert "pts" not in gw.domain_groups[0]
    finally:
        gw.domain_groups.clear()
