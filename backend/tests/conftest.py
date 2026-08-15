import os

# `conftest.py` es lo PRIMERO que importa pytest, antes que cualquier archivo
# de pruebas. Por eso el entorno se arma acá y no en un módulo de pruebas:
# `app.config` lee estas variables una sola vez, al importarse, y el primer
# `from app import ...` de cualquier archivo la congela. Con la configuración
# repartida, agregar un import arriba de todo en un test nuevo rompía la suite
# entera con 401 — pasó dos veces el 15-ago-2026, y las dos por lo mismo.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ADMIN_TOKEN"] = "test-token-secreto"
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ["WHATSAPP_APP_SECRET"] = "secreto-de-prueba"
os.environ["WHATSAPP_VERIFY_TOKEN"] = "verify-de-prueba"
# En producción sale del entorno; acá se fija para que las pruebas corran
# contra la misma configuración que el servidor real, no contra una ausencia
# que ninguna prueba notaría.
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
