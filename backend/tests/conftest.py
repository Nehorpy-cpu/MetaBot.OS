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


@pytest.fixture(autouse=True)
def _ninguna_prueba_gasta_plata(monkeypatch):
    """Ninguna corrida de pruebas puede llamar a un proveedor pago.

    OpenAI entró al router para la tarea `finanzas`, y varias pruebas llaman a
    `handle_incoming`, que llama de verdad a un modelo. Sin esto, correr la
    suite le cobraría a la cuenta del usuario — y la suite se corre decenas de
    veces por día.

    Se saca el proveedor, no se corta la red: los modelos gratuitos siguen
    respondiendo y el comportamiento probado es el mismo. Una prueba que SÍ
    quiera verificar el camino de OpenAI parchea `available_providers` por su
    cuenta, y ese parche gana sobre este.

    El import va ADENTRO: importar `app.llm` acá arriba arrastra `app.config`
    antes de que las pruebas fijen el ADMIN_TOKEN, y la suite entera pasa a
    devolver 401.
    """
    from app import llm

    original = llm.available_providers
    monkeypatch.setattr(
        llm, "available_providers",
        lambda: [p for p in original() if p["name"] != "openai"],
    )
