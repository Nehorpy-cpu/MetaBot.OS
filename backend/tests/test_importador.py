"""Alta de profesionales desde el padrón y por planilla.

Nadie va a retipear 40 médicos en un formulario. Estas pruebas defienden que
la planilla se lea como está —no como nos gustaría que estuviera— y que nada
se guarde sin que una persona lo confirme.
"""
import json

from tests.test_api import _create_company, client

from app import importador_profesionales as importador
from app import registry
from app.db import SessionLocal
from app.models import Doctor, MedicalRegistry


PADRON = [
    ("Alexis Roberto Báez Martínez", "Neurocirugía", "7678", "2029-11-22"),
    ("Echagüe Lezcano, Carmen Elisa", "Pediatría General", "7666", "2030-01-15"),
    ("María Cristina Meza Arce", "Cardiología", "7700", "2028-06-01"),
    # Escritas como aparecen de verdad en el CSV del CPM: la misma especialidad
    # con y sin tilde. En el padrón real son 19 cirujanos en "Cirugia General"
    # contra 327 en "Cirugía General".
    ("Rodrigo Emilio Cáceres Vera", "Cirugía General", "7801", "2029-03-10"),
    ("Nilda Beatriz Ruiz Díaz", "Cirugia General", "7802", "2029-04-18"),
    ("Hugo Daniel Villalba Rojas", "Cardiología Pediátrica", "7803", "2029-08-30"),
]


def _sembrar_padron():
    from datetime import date

    db = SessionLocal()
    try:
        db.query(MedicalRegistry).delete()
        for nombre, esp, cert, vence in PADRON:
            db.add(MedicalRegistry(
                full_name=nombre, match_key=registry.clave_de_nombre(nombre),
                specialty=esp, specialty_key=registry.clave_de_especialidad(esp),
                cert_number=cert,
                expires_at=date.fromisoformat(vence), source="CPM",
            ))
        db.commit()
    finally:
        db.close()


# --- Búsqueda en el padrón ---


def test_la_busqueda_exige_un_criterio():
    """Sin criterio no devuelve nada: el padrón no es un directorio para
    navegar, son 4.772 personas reales."""
    _sembrar_padron()
    db = SessionLocal()
    try:
        assert registry.buscar(db) == []
        assert registry.buscar(db, texto="  ") == []
    finally:
        db.close()


def test_encuentra_por_apellido_y_por_orden_invertido():
    """La planilla puede decir 'Baez Martinez' y el padrón 'Alexis Roberto
    Báez Martínez'."""
    _sembrar_padron()
    db = SessionLocal()
    try:
        for consulta in ("baez martinez", "Báez", "martinez alexis"):
            r = registry.buscar(db, texto=consulta)
            assert any("Báez" in x["full_name"] for x in r), f"no encontró con '{consulta}'"
    finally:
        db.close()


def test_la_busqueda_dice_si_la_certificacion_esta_vigente():
    _sembrar_padron()
    db = SessionLocal()
    try:
        r = registry.buscar(db, texto="Meza Arce", especialidad="Cardiología")
        assert len(r) == 1 and r[0]["cert_number"] == "7700"
        assert r[0]["vigente"] is True
    finally:
        db.close()


def test_el_apellido_se_encuentra_aunque_el_padron_sea_grande():
    """El fallo que esto cierra: el nombre se filtraba en Python sobre las
    primeras 600 filas ordenadas alfabéticamente. Como el padrón real llega
    hasta la "C" en esas 600, buscar "Giménez" devolvía 0 de los 57 que
    existen, y la clínica concluía que su médico no estaba certificado."""
    from datetime import date

    db = SessionLocal()
    try:
        db.query(MedicalRegistry).delete()
        # 800 profesionales de apellido temprano, y uno solo al final del
        # abecedario: el que el filtrado por lotes dejaba afuera.
        for i in range(800):
            nombre = f"Aguilera Acosta, Ana {i:04d}"
            db.add(MedicalRegistry(
                full_name=nombre, match_key=registry.clave_de_nombre(nombre),
                specialty="Pediatría General",
                specialty_key=registry.clave_de_especialidad("Pediatría General"),
                cert_number=f"{i:05d}", expires_at=date(2029, 1, 1), source="CPM",
            ))
        tardio = "Zelaya Giménez, Rodrigo"
        db.add(MedicalRegistry(
            full_name=tardio, match_key=registry.clave_de_nombre(tardio),
            specialty="Cardiología",
            specialty_key=registry.clave_de_especialidad("Cardiología"),
            cert_number="99999", expires_at=date(2030, 5, 5), source="CPM",
        ))
        db.commit()

        for consulta in ("Zelaya", "Giménez", "Gimenez", "zelaya gimenez"):
            r = registry.buscar(db, texto=consulta)
            assert [x["full_name"] for x in r] == [tardio], \
                f"'{consulta}' no lo encontró: {r}"
    finally:
        db.close()


def test_se_avisa_cuando_hay_mas_de_los_que_se_muestran():
    """Ver 25 de 346 sin decir nada parece "estos son todos los que hay"."""
    from datetime import date

    company = _create_company(name="Sanatorio Tope")
    db = SessionLocal()
    try:
        db.query(MedicalRegistry).delete()
        for i in range(40):
            nombre = f"Benítez Rolón, Carlos {i:03d}"
            db.add(MedicalRegistry(
                full_name=nombre, match_key=registry.clave_de_nombre(nombre),
                specialty="Cardiología",
                specialty_key=registry.clave_de_especialidad("Cardiología"),
                cert_number=f"{i:05d}", expires_at=date(2029, 1, 1), source="CPM",
            ))
        db.commit()
    finally:
        db.close()

    datos = client.get(f"/api/companies/{company['id']}/registry/search?q=Benítez").json()
    assert datos["mostrados"] == registry.TOPE_BUSQUEDA
    assert datos["total"] == 40
    assert datos["hay_mas"] is True


def test_los_vigentes_se_muestran_primero():
    """De 4.773 certificaciones del padrón real, 4.223 ya vencieron. Ordenar
    solo por nombre llenaba la pantalla de vencidos."""
    from datetime import date

    db = SessionLocal()
    try:
        db.query(MedicalRegistry).delete()
        for i in range(30):  # apellidos tempranos, todos vencidos
            nombre = f"Acosta Aquino, Beatriz {i:03d}"
            db.add(MedicalRegistry(
                full_name=nombre, match_key=registry.clave_de_nombre(nombre),
                specialty="Cardiología",
                specialty_key=registry.clave_de_especialidad("Cardiología"),
                cert_number=f"{i:05d}", expires_at=date(2015, 1, 1), source="CPM",
            ))
        vigente = "Zorrilla Acosta, Mirta"
        db.add(MedicalRegistry(
            full_name=vigente, match_key=registry.clave_de_nombre(vigente),
            specialty="Cardiología",
            specialty_key=registry.clave_de_especialidad("Cardiología"),
            cert_number="88888", expires_at=date(2031, 1, 1), source="CPM",
        ))
        db.commit()

        r = registry.buscar(db, especialidad="Cardiología")
        assert vigente in [x["full_name"] for x in r], \
            "la única certificación vigente quedó fuera de la primera página"
    finally:
        db.close()


def test_la_tilde_no_esconde_profesionales():
    """Elegir "Cirugía General" tiene que traer también a los cargados como
    "Cirugia General". En el padrón real eran 19 cirujanos certificados que la
    clínica no veía, sin ningún aviso de que faltaban."""
    _sembrar_padron()
    db = SessionLocal()
    try:
        for escrito in ("Cirugía General", "Cirugia General", "CIRUGIA GENERAL"):
            nombres = {r["full_name"] for r in registry.buscar(db, especialidad=escrito)}
            assert len(nombres) == 2, f"con '{escrito}' encontró {nombres}"
    finally:
        db.close()


def test_la_especialidad_no_reordena_sus_palabras():
    """`clave_de_nombre` ordena los tokens porque en un nombre el orden varía.
    En una especialidad el orden es parte del término: ordenarlo convertiría
    "Cirugía Cardiovascular" en "cardiovascular cirugia"."""
    assert registry.clave_de_especialidad("Cirugía Cardiovascular") == "cirugia cardiovascular"
    assert registry.clave_de_especialidad("Cirugia  Cardiovascular ") == "cirugia cardiovascular"


def test_elegir_la_especialidad_madre_trae_las_subespecialidades():
    _sembrar_padron()
    db = SessionLocal()
    try:
        nombres = {r["full_name"] for r in registry.buscar(db, especialidad="Cardiología")}
        assert any("Meza" in n for n in nombres)      # Cardiología
        assert any("Villalba" in n for n in nombres)  # Cardiología Pediátrica
    finally:
        db.close()


def test_el_desplegable_muestra_una_opcion_por_especialidad():
    """169 valores distintos en el CSV son 136 especialidades reales. Mostrar
    las variantes por separado obliga a la clínica a adivinar cuál tiene a su
    gente."""
    _sembrar_padron()
    db = SessionLocal()
    try:
        opciones = registry.especialidades(db)
        cirugias = [o for o in opciones if o["clave"] == "cirugia general"]
        assert len(cirugias) == 1, f"quedaron variantes sueltas: {cirugias}"
        assert cirugias[0]["etiqueta"] == "Cirugía General"  # la forma correcta
        assert cirugias[0]["cantidad"] == 2  # cuenta a los dos, no a uno
    finally:
        db.close()


def test_el_alta_desde_el_padron_queda_verificada():
    """La diferencia entre 'lo tipeó la recepcionista' y 'figura en el
    registro con este número'."""
    _sembrar_padron()
    company = _create_company(name="Sanatorio Alta Padrón")
    cid = company["id"]

    db = SessionLocal()
    try:
        entrada = db.query(MedicalRegistry).filter(
            MedicalRegistry.cert_number == "7678").one()
        rid = entrada.id
    finally:
        db.close()

    resp = client.post(f"/api/companies/{cid}/doctors/from-registry",
                       json={"registry_id": rid, "schedule": "Lun a Vie 08:00-14:00"})
    assert resp.status_code == 201
    datos = resp.json()
    assert datos["verification"] == "verified"
    assert datos["cert_number"] == "7678"
    assert datos["specialty"] == "Neurocirugía"

    # Y el horario quedó cargado, que es lo que el bot necesita para ofrecerlo.
    doctores = client.get(f"/api/companies/{cid}/doctors").json()
    assert doctores[0]["schedule"] == "Lun a Vie 08:00-14:00"


def test_no_se_carga_dos_veces_el_mismo_profesional():
    _sembrar_padron()
    company = _create_company(name="Sanatorio Duplicado")
    cid = company["id"]
    db = SessionLocal()
    try:
        rid = db.query(MedicalRegistry).filter(MedicalRegistry.cert_number == "7666").one().id
    finally:
        db.close()

    assert client.post(f"/api/companies/{cid}/doctors/from-registry",
                       json={"registry_id": rid}).status_code == 201
    assert client.post(f"/api/companies/{cid}/doctors/from-registry",
                       json={"registry_id": rid}).status_code == 409


# --- Lectura de la planilla ---


def test_reconoce_los_encabezados_que_usa_la_gente():
    """Pedirle a una recepcionista que renombre columnas a `full_name` es
    pedirle que haga el trabajo del programa."""
    for encabezado in (
        "Nombre,Especialidad,Horario",
        "Profesional,Especialidad,Horarios",
        "Medico,Area,Dias y horarios",
        "Apellido y Nombre,Especialidad,Atencion",
    ):
        for sep in (",", ";"):
            contenido = (
                encabezado.replace(",", sep) + "\n"
                + sep.join(["Dra. Marta Benítez", "Clínica médica", "Lun a Vie 07:00-13:00"])
                + "\n"
            ).encode()
            leidos = importador.leer(contenido, "lista.csv")
            assert len(leidos) == 1, f"no leyó '{encabezado}' con separador '{sep}'"
            assert "Benítez" in leidos[0]["name"]
            assert leidos[0]["schedule"] == "Lun a Vie 07:00-13:00"


def test_el_encabezado_nunca_se_carga_como_medico():
    """Si el separador se detecta mal, la fila de títulos NO puede terminar
    dada de alta como un profesional llamado 'Profesional;Especialidad'."""
    # Archivo con separadores inconsistentes: el peor caso real.
    contenido = (
        "Profesional;Especialidad;Horarios\n"
        "Dra. Marta Benítez,Clínica médica,Lun a Vie 07:00-13:00\n"
    ).encode()
    leidos = importador.leer(contenido, "lista.csv")
    assert not any("Especialidad" in x["name"] for x in leidos), \
        f"cargó el encabezado como médico: {[x['name'] for x in leidos]}"


def test_detecta_el_separador_punto_y_coma():
    """El clásico 'me quedó todo en una columna': Excel exporta con ; según la
    configuración regional."""
    contenido = "Nombre;Especialidad;Horario\nDr. Ramón Ayala;Cardiología;Mar y Jue 14:00-19:00\n".encode()
    leidos = importador.leer(contenido, "lista.csv")
    assert len(leidos) == 1
    assert leidos[0]["specialty"] == "Cardiología"


def test_una_planilla_sin_encabezados_igual_sirve():
    contenido = "Dra. Lucía Ozorio,Pediatría,Lun a Sáb 08:00-12:00\n".encode()
    leidos = importador.leer(contenido, "lista.csv")
    assert len(leidos) == 1
    assert leidos[0]["specialty"] == "Pediatría"


# --- Previsualización y confirmación ---


def test_la_previsualizacion_NO_guarda_nada():
    """Cargar cuarenta médicos de un archivo sin mirarlo es como se meten
    cuarenta errores de una sentada."""
    _sembrar_padron()
    company = _create_company(name="Sanatorio Preview")
    cid = company["id"]

    contenido = (
        "Nombre,Especialidad,Horario\n"
        "Alexis Roberto Baez Martinez,Neurocirugía,Lun a Vie 08:00-14:00\n"
        "Dra. Fulana Inexistente,Clínica médica,Mar 09:00-12:00\n"
    ).encode()

    resp = client.post(
        f"/api/companies/{cid}/doctors/import/preview",
        files={"archivo": ("lista.csv", contenido, "text/csv")},
    )
    assert resp.status_code == 200
    datos = resp.json()
    assert datos["total"] == 2
    assert datos["en_padron"] == 1  # solo Báez figura

    # Nada se guardó.
    assert client.get(f"/api/companies/{cid}/doctors").json() == []


def test_la_previsualizacion_sugiere_aunque_el_nombre_no_sea_exacto():
    """La planilla casi nunca trae el nombre igual que el padrón: falta un
    segundo nombre, sobra el "Dra.", cambia el orden. Sin sugerencias, una fila
    con "Baez Martinez, Alexis" queda como "sin coincidencia" teniendo el
    profesional enfrente."""
    _sembrar_padron()
    company = _create_company(name="Sanatorio Sugerencias")
    cid = company["id"]

    contenido = (
        "Nombre,Especialidad,Horario\n"
        "Dra. Baez Martinez,Neurocirugía,Lun 08:00-12:00\n"
    ).encode()
    resp = client.post(
        f"/api/companies/{cid}/doctors/import/preview",
        files={"archivo": ("lista.csv", contenido, "text/csv")},
    )
    fila = resp.json()["filas"][0]
    candidatos = ([fila["padron"]] if fila["padron"] else []) + fila["sugerencias"]
    assert any("Báez" in c["full_name"] for c in candidatos), \
        f"no ofreció ningún candidato: {fila}"


def test_no_sugiere_a_cualquiera_que_comparta_un_apellido():
    """Ofrecerle "Villalba Salinas, Auria" a quien escribió "Villalba Duarte,
    Rossana" invita a marcar a otra persona. Sugerir mal es peor que no
    sugerir."""
    _sembrar_padron()
    company = _create_company(name="Sanatorio Sin Ruido")
    cid = company["id"]

    # "Meza" existe en el padrón (María Cristina Meza Arce) pero esta es otra:
    # solo comparte el apellido.
    contenido = "Nombre,Especialidad\nMeza Ovelar, Liz Carolina,Dermatología\n".encode()
    resp = client.post(
        f"/api/companies/{cid}/doctors/import/preview",
        files={"archivo": ("lista.csv", contenido, "text/csv")},
    )
    fila = resp.json()["filas"][0]
    assert fila["padron"] is None
    assert fila["sugerencias"] == [], f"sugirió a otra persona: {fila['sugerencias']}"


def test_confirmar_da_de_alta_y_verifica():
    _sembrar_padron()
    company = _create_company(name="Sanatorio Confirma Import")
    cid = company["id"]

    resp = client.post(f"/api/companies/{cid}/doctors/import/confirm", json={
        "profesionales": [
            {"name": "Alexis Roberto Báez Martínez", "specialty": "Neurocirugía",
             "schedule": "Lun a Vie 08:00-14:00"},
            {"name": "Lic. Andrea Sanabria", "specialty": "Bioquímica",
             "schedule": "Lun a Vie 06:30-11:00"},
        ],
    })
    assert resp.status_code == 200
    datos = resp.json()
    assert len(datos["creados"]) == 2
    assert datos["verificados"] == 1   # el médico figura en el padrón
    assert datos["no_figuran"] == 1    # la bioquímica no, y eso está bien

    doctores = client.get(f"/api/companies/{cid}/doctors").json()
    por_nombre = {d["name"]: d for d in doctores}
    assert por_nombre["Alexis Roberto Báez Martínez"]["cert_number"] == "7678"
    assert por_nombre["Lic. Andrea Sanabria"]["verification"] == "not_found"


def test_confirmar_dos_veces_no_duplica():
    _sembrar_padron()
    company = _create_company(name="Sanatorio Import Doble")
    cid = company["id"]
    cuerpo = {"profesionales": [{"name": "María Cristina Meza Arce", "specialty": "Cardiología"}]}

    client.post(f"/api/companies/{cid}/doctors/import/confirm", json=cuerpo)
    segunda = client.post(f"/api/companies/{cid}/doctors/import/confirm", json=cuerpo).json()
    assert segunda["creados"] == []
    assert segunda["omitidos"][0]["motivo"] == "ya estaba cargado"
    assert len(client.get(f"/api/companies/{cid}/doctors").json()) == 1


def test_el_padron_NO_es_una_herramienta_del_bot():
    """Un paciente no puede usar el bot para navegar el registro de médicos
    del país: es una herramienta del panel."""
    from app import chat as chat_engine

    assert "search_registry" not in chat_engine.TOOL_SPECS
    assert not any("registry" in k or "padron" in k for k in chat_engine.TOOL_SPECS)
