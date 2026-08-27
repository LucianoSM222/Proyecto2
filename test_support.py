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

import os, glob, shutil

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

def permitir_fixture_de_granate(*claves_de_pozo):
    """
    El canario y sus tests derivados usan un pozo de MINA GRANATE (MGN_3025),
    que está a ~3.117 m del centroide de Punta del Cobre. El guardián de sitio
    lo rechaza —correctamente— porque el sitio activo es MPC y la plataforma
    sostiene "un archivo de trabajo = una mina".

    Ese conflicto quedó dormido durante meses: el fixture no estaba en el
    repositorio, los tests se omitían, y nadie vio que el canario y el guardián
    de sitio se contradicen. Al reponer los datos, salió a la luz.

    Estos tests SÍ quieren cargar otra mina, a propósito, porque el canario es
    una prueba de geometría y no del sitio. Se declara con la misma puerta que
    usa el usuario en la interfaz —confirmar el token— en vez de apagar el
    guardián: la excepción queda registrada en site_confirmed_tokens y es
    auditable.
    """
    import geomech_wizard as gw
    for k in claves_de_pozo:
        gw.confirm_site_token(f"pozo:{k}")

def asegurar_fixture_granate():
    """
    Extrae test_data/MGN3025.zip si sus archivos no están sueltos todavía.

    El canario (pozo H5 contra Metandesitas → 1437/1743, el 82,4% que CLAUDE.md
    cita como vara de exactitud) necesita el DXF y los XML de Mina Granate. En
    el repositorio vive comprimido, para no duplicar 4 MB; sin este paso, un
    clon limpio omite el canario y sus diez tests derivados —que es exactamente
    como estuvo dormido durante meses sin que nadie lo notara.
    """
    import zipfile
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_data")
    zip_path = os.path.join(base, "MGN3025.zip")
    if not os.path.exists(zip_path):
        return False
    if glob.glob(os.path.join(base, "Metandesitas.dxf")):
        return True
    destino = os.path.join(base, "_MGN3025")
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(destino)
        interno = os.path.join(destino, "MGN3025", ".datos_perforacion.zip")
        if os.path.exists(interno):
            with zipfile.ZipFile(interno) as z:
                z.extractall(destino)
        # os.walk y no glob("**"): los datos de perforación vienen dentro de
        # ".datos_perforacion", y glob NO entra en directorios que empiezan con
        # punto. Con glob el DXF se copiaba y los XML no, en silencio.
        import fnmatch
        patrones = ("*.dxf",
                    # Solo los cuatro DQ hermanos y el MW del canario: copiar
                    # los 50 XML ensuciaría los patrones de otros tests.
                    "DQMGN_3025_PR01_TH_P39_*.xml",
                    "DQMGN_3025_PR01_TH_P40_*.xml",
                    "DQMGN_3025_PR01_TH_P41_*.xml",
                    "DQMGN_3025_PR01_TH_P42_*.xml",
                    "MWMGN_3025_PR01_TH_P41H5_*.xml")
        copiados = 0
        for raiz, _dirs, archivos in os.walk(destino):
            for nombre in archivos:
                if any(fnmatch.fnmatch(nombre, pat) for pat in patrones):
                    shutil.copy(os.path.join(raiz, nombre), base)
                    copiados += 1
        if copiados < 6:
            print(f"⚠ Fixture de Granate incompleto: {copiados} archivo(s) "
                  "copiado(s), se esperaban 6 (1 DXF + 4 DQ + 1 MW).")
        return copiados >= 6
    except Exception as e:
        print(f"⚠ No se pudo preparar el fixture de Granate: {e}")
        return False
