"""CFO — Fase 6 parte 2: los conectores que salen a buscar afuera.

Casi nada de acá prueba que traigan filas. Prueba lo otro, que es lo que puede
salir caro:

**El peor escenario del módulo entero.** Un cliente carga un conector de
PostgreSQL apuntando a `db:5432` —o sea, a NUESTRA base— y el sistema se
conecta desde adentro de la red y le devuelve los datos de todos los demás
clientes. Un rato de trabajo para él, todos los clientes para nosotros.

Y la contraseña de su ERP, que ahora guardamos.
"""
import json

import pytest

from tests.test_api import _create_company, client  # noqa: I001

from app import cfo_fuentes_externas as fx
from app import cfo_secretos
from app.db import SessionLocal
from app.models import FinanceConnector

FINANZAS = ["finance"]


def _empresa(nombre: str) -> int:
    return _create_company(name=nombre, packs=FINANZAS)["id"]


def _crear(cid: int, **cuerpo):
    base = {"fuente": "ventas", "tipo": "postgres", "nombre": "ERP"}
    return client.post(f"/api/companies/{cid}/cfo/conectores", json={**base, **cuerpo})


PG_OK = {
    "host": "example.com", "puerto": 5432, "base": "ventas",
    "usuario": "lectura", "consulta": "SELECT fecha, total FROM ventas",
    "columnas": {"fecha": "fecha", "monto": "total"},
}


# ─── El peor escenario: apuntar a nuestra propia red ─────────────────────


def test_un_conector_no_puede_apuntar_a_una_red_interna():
    """Si pudiera, un cliente leería la base de todos los demás."""
    for host in ("localhost", "127.0.0.1", "db", "10.0.0.5", "192.168.1.10",
                 "169.254.169.254", "::1"):
        with pytest.raises(fx.FuenteInvalida) as exc:
            fx.validar_postgres({**PG_OK, "host": host})
        assert "no permitida" in str(exc.value) or "resolver" in str(exc.value), host


def test_tampoco_por_la_url_de_un_conector_rest():
    """169.254.169.254 es el endpoint de metadatos de las nubes: ahí viven las
    credenciales de la máquina."""
    for url in ("https://localhost:8000/ventas",
                "https://127.0.0.1/ventas",
                "https://169.254.169.254/latest/meta-data/",
                "https://192.168.0.10/api"):
        with pytest.raises(fx.FuenteInvalida):
            fx.validar_rest({"url": url, "campos": {"fecha": "f", "monto": "m"}})


def test_el_conector_con_host_interno_ni_siquiera_se_guarda():
    """No se guarda "para arreglarlo después": un conector mal apuntado que
    queda en la base es uno que alguien puede encender más tarde."""
    cid = _empresa("Fuente Host Interno")
    r = _crear(cid, config={**PG_OK, "host": "localhost"}, credencial="x")
    assert r.status_code == 422
    assert r.json()["detail"]["codigo"] == "config_invalida"

    db = SessionLocal()
    try:
        assert db.query(FinanceConnector).filter(
            FinanceConnector.company_id == cid).count() == 0
    finally:
        db.close()


# ─── La consulta del cliente ─────────────────────────────────────────────


def test_la_consulta_tiene_que_ser_de_lectura():
    for mala in ("UPDATE ventas SET total = 0",
                 "DELETE FROM ventas",
                 "DROP TABLE ventas",
                 "INSERT INTO ventas VALUES (1)"):
        with pytest.raises(fx.FuenteInvalida) as exc:
            fx.validar_postgres({**PG_OK, "consulta": mala})
        assert "SELECT" in str(exc.value)


def test_no_se_pueden_encadenar_dos_sentencias():
    """El punto y coma es el mecanismo: `SELECT 1; DROP TABLE ventas`."""
    with pytest.raises(fx.FuenteInvalida) as exc:
        fx.validar_postgres({
            **PG_OK, "consulta": "SELECT 1; DROP TABLE ventas"})
    assert "punto y coma" in str(exc.value)


def test_un_comentario_no_disfraza_una_escritura():
    """`-- SELECT` adelante no convierte en lectura lo que viene después."""
    with pytest.raises(fx.FuenteInvalida):
        fx.validar_postgres({
            **PG_OK, "consulta": "-- SELECT algo\nDELETE FROM ventas"})
    with pytest.raises(fx.FuenteInvalida):
        fx.validar_postgres({
            **PG_OK, "consulta": "/* SELECT */ UPDATE ventas SET total=0"})


def test_una_consulta_con_WITH_se_acepta():
    """Un CTE es lectura, y muchos ERPs lo necesitan."""
    cfg = fx.validar_postgres({
        **PG_OK, "consulta": "WITH v AS (SELECT * FROM ventas) SELECT * FROM v"})
    assert cfg["consulta"].startswith("WITH")


def test_el_tope_de_filas_lo_ponemos_nosotros(monkeypatch):
    """Pedírselo al cliente en su SQL sería confiar en que se acuerde."""
    ejecutadas = []

    class _Cur:
        description = []

        def execute(self, q):
            ejecutadas.append(q)

        def fetchall(self):
            return []

        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Conn:
        read_only = False

        def cursor(self): return _Cur()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    import psycopg
    monkeypatch.setattr(psycopg, "connect", lambda **kw: _Conn())

    with pytest.raises(fx.FalloDeSincronizacion):
        fx.traer_postgres(PG_OK, "clave")
    assert f"LIMIT {fx.MAXIMO_FILAS}" in ejecutadas[0]
    assert "SELECT * FROM (" in ejecutadas[0]


def test_la_conexion_pide_solo_lectura_y_timeout(monkeypatch):
    """No protege al cliente de sí mismo; impide que un UPDATE escrito por
    error o por maldad le toque su sistema DESDE ACÁ."""
    vistos = {}

    class _Cur:
        description = []
        def execute(self, q): pass
        def fetchall(self): return []
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Conn:
        read_only = False
        def cursor(self): return _Cur()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    import psycopg
    monkeypatch.setattr(psycopg, "connect", lambda **kw: (vistos.update(kw), _Conn())[1])

    with pytest.raises(fx.FalloDeSincronizacion):
        fx.traer_postgres(PG_OK, "clave")
    assert "default_transaction_read_only=on" in vistos["options"]
    assert "statement_timeout" in vistos["options"]
    assert vistos["connect_timeout"] <= 15


# ─── La credencial ───────────────────────────────────────────────────────


def test_la_credencial_se_guarda_cifrada_y_no_en_claro():
    """Con acceso de lectura a un respaldo, alguien tendría la contraseña del
    ERP de cada cliente."""
    if not cfo_secretos.hay_llave():
        pytest.skip("sin CFO_SECRETS_KEY en el entorno de prueba")
    cid = _empresa("Fuente Credencial")
    r = _crear(cid, config=PG_OK, credencial="contrasena-del-erp")
    assert r.status_code == 201, r.text

    db = SessionLocal()
    try:
        fila = db.query(FinanceConnector).filter(
            FinanceConnector.company_id == cid).first()
        assert fila.secreto_cifrado
        assert "contrasena-del-erp" not in fila.secreto_cifrado
        assert cfo_secretos.descifrar(fila.secreto_cifrado) == "contrasena-del-erp"
    finally:
        db.close()


def test_la_credencial_no_sale_por_la_api():
    """El panel sabe si HAY credencial, jamás cuál es. Igual que el PIN."""
    if not cfo_secretos.hay_llave():
        pytest.skip("sin CFO_SECRETS_KEY en el entorno de prueba")
    cid = _empresa("Fuente Credencial Oculta")
    _crear(cid, config=PG_OK, credencial="contrasena-del-erp")
    crudo = client.get(f"/api/companies/{cid}/cfo/conectores").text
    assert "contrasena-del-erp" not in crudo
    fila = json.loads(crudo)[0]
    assert fila["config"]["tiene_credencial"] is True
    assert "credencial" not in fila["config"]
    assert "secreto_cifrado" not in crudo


def test_sin_llave_de_cifrado_no_se_guarda_nada(monkeypatch):
    """Ruidoso al crear, no silencioso al sincronizar: un servidor a medias no
    puede terminar guardando credenciales en claro "por ahora"."""
    monkeypatch.setattr(cfo_secretos, "_LLAVE", "")
    cid = _empresa("Fuente Sin Llave")
    r = _crear(cid, config=PG_OK, credencial="algo")
    assert r.status_code == 503
    assert r.json()["detail"]["codigo"] == "sin_llave_de_cifrado"

    db = SessionLocal()
    try:
        assert db.query(FinanceConnector).filter(
            FinanceConnector.company_id == cid).count() == 0
    finally:
        db.close()


def test_un_error_de_conexion_no_arrastra_la_contrasena():
    """Un error de PostgreSQL trae el DSN entero, y ese texto se muestra en el
    panel y se guarda en el conector."""
    sucio = ("connection to server at \"erp.example.com\" failed: "
             "postgresql://lectura:S3cr3t0@erp.example.com:5432/ventas "
             "password=S3cr3t0")
    limpio = fx._limpiar(sucio)
    assert "S3cr3t0" not in limpio
    assert "<credencial>" in limpio or "<oculto>" in limpio


# ─── Lo que llega de afuera ──────────────────────────────────────────────


def test_una_url_http_no_se_acepta():
    """El token viaja en el encabezado: sobre http lo lee cualquiera."""
    with pytest.raises(fx.FuenteInvalida) as exc:
        fx.validar_rest({"url": "http://api.example.com/ventas",
                         "campos": {"fecha": "f", "monto": "m"}})
    assert "https" in str(exc.value)


def test_si_un_registro_no_se_entiende_no_se_carga_ninguno():
    """Misma regla que la planilla: un total con el 98% de los datos se ve
    bien y cierra mal."""
    campos = {"fecha": "f", "monto": "m", "categoria": "", "referencia": ""}
    with pytest.raises(fx.FalloDeSincronizacion) as exc:
        fx._normalizar(
            [{"f": "01/07/2026", "m": "100.000"}, {"f": "ayer", "m": "5"}],
            campos, "Registro",
        )
    assert "no se cargó ninguno" in str(exc.value)


def test_los_montos_y_fechas_se_leen_igual_que_en_la_planilla():
    """Un ERP paraguayo devuelve lo mismo que exporta a CSV. Reusar el lector
    evita tener dos ideas distintas de qué es 1.234.567."""
    campos = {"fecha": "f", "monto": "m", "categoria": "", "referencia": ""}
    filas = fx._normalizar([{"f": "03/07/2026", "m": "1.234.567"}],
                           campos, "Registro")
    assert filas[0]["monto_gs"] == 1_234_567
    assert filas[0]["fecha"].month == 7


def test_una_respuesta_que_no_es_lista_se_rechaza_con_motivo():
    with pytest.raises(fx.FalloDeSincronizacion) as exc:
        fx._por_camino({"data": {"no": "es lista"}}, "data")
    assert "no es una lista" in str(exc.value)


def test_se_dice_donde_se_esperaba_la_lista():
    with pytest.raises(fx.FalloDeSincronizacion) as exc:
        fx._por_camino({"otra_cosa": []}, "data.items")
    assert "data.items" in str(exc.value)


# ─── Permisos y aislamiento ──────────────────────────────────────────────


def test_no_se_sincroniza_el_conector_de_otra_empresa():
    if not cfo_secretos.hay_llave():
        pytest.skip("sin CFO_SECRETS_KEY en el entorno de prueba")
    a = _empresa("Fuente Cruce A")
    b = _empresa("Fuente Cruce B")
    con = _crear(a, config=PG_OK, credencial="x").json()["id"]
    r = client.post(f"/api/companies/{b}/cfo/conectores/{con}/sincronizar")
    assert r.status_code == 404


def test_un_conector_de_planilla_no_se_sincroniza_por_ahi():
    cid = _empresa("Fuente Tipo Mezclado")
    con = _crear(cid, tipo="csv", nombre="Planilla").json()["id"]
    r = client.post(f"/api/companies/{cid}/cfo/conectores/{con}/sincronizar")
    assert r.status_code == 422
    assert r.json()["detail"]["codigo"] == "tipo_incorrecto"
