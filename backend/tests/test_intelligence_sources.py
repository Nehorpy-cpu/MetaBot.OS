"""Contrato IntelligenceSource: honestidad sobre de dónde sale el dato.

Lo que estas pruebas defienden: que el sistema diga que NO se puede antes de
intentarlo. Aceptar una URL de Instagram para que después el escaneo falle
raro deja al cliente creyendo que es un bug nuestro; y si funcionara, le
pondríamos la cuenta en riesgo a él.
"""
import pytest
from tests.test_api import _create_company, client

from app import intelligence_sources as fuentes
from app.intelligence_sources import Capacidad, Legalidad


@pytest.mark.parametrize("url,esperada", [
    ("https://www.instagram.com/perfumeria_ejemplo/", "instagram_scrape"),
    ("https://instagram.com/algo", "instagram_scrape"),
    ("https://www.facebook.com/unaclinica", "instagram_scrape"),  # mismos términos
    ("https://www.tiktok.com/@algo", "tiktok_scrape"),
    ("https://www.facebook.com/ads/library/?id=123", "meta_ad_library"),
    ("https://arfagi.com/productos", "website"),
    ("https://sanatorio.com.py", "website"),
])
def test_clasifica_la_url_antes_de_intentar_nada(url, esperada):
    assert fuentes.fuente_de(url).key == esperada


def test_las_redes_sociales_estan_declaradas_como_restringidas():
    """No es que no las hayamos hecho: es que no se deben hacer."""
    for key in ("instagram_scrape", "tiktok_scrape"):
        f = fuentes.FUENTES[key]
        assert f.legalidad is Legalidad.RESTRINGIDA
        assert f.implementada is False
        assert f.usable is False
        assert f.advertencia, "una fuente restringida tiene que explicar por qué"


def test_la_ad_library_es_oficial_y_es_la_alternativa():
    """Para saber qué promociona la competencia es MEJOR fuente que un perfil
    raspado: muestra en qué gastan de verdad."""
    f = fuentes.META_AD_LIBRARY
    assert f.legalidad is Legalidad.OFICIAL
    assert f.puede(Capacidad.ANUNCIOS)
    assert f.requiere, "tiene que decir qué credencial hace falta"


def test_una_fuente_declarada_pero_sin_conectar_no_se_da_por_usable():
    """`implementada=False` no puede colarse como disponible: sería prometer
    algo que no existe."""
    assert fuentes.META_AD_LIBRARY.implementada is False
    assert fuentes.META_AD_LIBRARY.usable is False
    assert fuentes.SITIO_PUBLICO.usable is True


def test_el_endpoint_rechaza_instagram_con_motivo_y_alternativa():
    company = _create_company(name="Inteligencia Instagram")
    cid = company["id"]
    resp = client.post(f"/api/companies/{cid}/competitors",
                       json={"url": "https://www.instagram.com/competidor/", "label": "Competencia"})
    assert resp.status_code == 422
    detalle = resp.json()["detail"]
    assert "términos" in detalle.lower() or "prohib" in detalle.lower()
    assert "Ad Library" in detalle, "tiene que decir qué hacer en su lugar"

    # Y no quedó cargado nada.
    assert client.get(f"/api/companies/{cid}/competitors").json() == []


def test_el_endpoint_acepta_un_sitio_web_publico():
    company = _create_company(name="Inteligencia Web")
    cid = company["id"]
    resp = client.post(f"/api/companies/{cid}/competitors",
                       json={"url": "https://competencia.com.py/productos", "label": "Competencia"})
    assert resp.status_code == 201
    assert resp.json()["fuente"] == "Sitio web público del negocio"


def test_el_catalogo_muestra_tambien_lo_que_NO_se_hace():
    """Un cliente que pregunta '¿pueden mirar el Instagram de mi competencia?'
    merece la razón, no un silencio."""
    company = _create_company(name="Catálogo Fuentes")
    datos = client.get(f"/api/companies/{company['id']}/intelligence-sources").json()
    por_key = {f["key"]: f for f in datos["fuentes"]}

    assert por_key["instagram_scrape"]["usable"] is False
    assert por_key["instagram_scrape"]["advertencia"]
    assert por_key["website"]["usable"] is True
    assert por_key["meta_ad_library"]["legalidad"] == "oficial"
