import os

# Antes de que cualquier prueba importe `app.config`, que lee esto una sola vez
# al arrancar. En producción sale del entorno; acá se fija para que las pruebas
# corran contra la misma configuración que el servidor real, no contra una
# ausencia que ninguna prueba notaría.
os.environ.setdefault("CFO_REPORT_BASE_URL", "https://informes.test")

import pytest  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"
