"""
test_support.py — Soporte compartido de las suites (adenda A.8).

Un test que no puede correr porque falta su archivo de datos NO es un test
fallido: es un test omitido. La distinción importa. Con cinco rojos
permanentes en la suite, una regresión real se esconde entre ellos y nadie la
nota; la suite tiene que quedar verde para que un rojo signifique algo.

Los fixtures del canario (Metandesitas.dxf y los XML MGN_3025 P40/P41H5) no
están en el repositorio. Cuando falten, las suites que los necesitan se omiten
declarando qué falta y cómo reponerlo.

Funciona con y sin pytest: bajo pytest usa su mecanismo de skip nativo; en
ejecución directa (`python3 test_x.py`) usa la misma excepción y los runners
la reportan como omisión.
"""

import os

try:                                    # pragma: no cover - depende del entorno
    import pytest
    SkipTest = pytest.skip.Exception
    fixture = pytest.fixture
    HAVE_PYTEST = True
except ImportError:                     # pragma: no cover
    class SkipTest(Exception):
        """Se omite el test: falta un insumo, no hay un defecto."""
    def fixture(fn):
        return fn
    HAVE_PYTEST = False


# Cómo reponer los fixtures que no viven en el repositorio.
COMO_REPONER = (
    "Estos archivos no están versionados. Repón el directorio test_data/ con "
    "Metandesitas.dxf y los XML IREDES de MGN_3025 (DQ P40 y MW P41H5), o "
    "apunta las variables de entorno GEOMECH_DXF / GEOMECH_DQ / GEOMECH_MW / "
    "GEOMECH_XLSX a sus rutas."
)


def skip(reason: str):
    """Omite el test en curso con una razón visible."""
    raise SkipTest(reason)


def require_real_data(**paths):
    """
    Exige los archivos de datos reales nombrados. Si falta alguno, OMITE el
    test (no lo falla) declarando exactamente cuáles y cómo reponerlos.

        require_real_data(DXF=DXF_PATH, DQ=DQ_PATH, MW=MW_PATH)
    """
    faltan = [k for k, v in paths.items() if not v or not os.path.exists(str(v))]
    if faltan:
        skip(f"Faltan archivos de datos reales: {', '.join(sorted(faltan))}. "
             f"{COMO_REPONER}")


def skipped_banner(nombre: str, motivo: str) -> str:
    return f"⊘ {nombre} OMITIDO — {motivo}"
