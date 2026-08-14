"""La aritmética del dinero.

Un error acá no se ve como un error: se ve como una discusión con el paciente
en la caja, o como una planilla que la aseguradora rechaza y el profesional
tiene que rehacer.
"""
from tests.test_api import _create_company, client  # noqa: I001

from app import aranceles
from app.aranceles import Cobertura, honorario_gs, repartir


def test_las_dos_partes_suman_exactamente_el_precio():
    """Lo que pone el paciente más lo que pone la aseguradora tiene que dar el
    precio de lista. Ni un guaraní de más ni de menos.

    Calculando cada parte por separado con su propio redondeo, un precio de
    333 con 50% daba 166 + 166 = 332: un guaraní que no se lo cobró nadie.
    Suena a nada hasta que son 400 atenciones por mes.
    """
    for precio in (0, 1, 333, 1_000, 49_999, 150_000, 1_234_567):
        for pct in range(0, 101, 5):
            m = repartir(precio, Cobertura(pct, 0, False, "convenio"))
            assert m.paga_el_paciente_gs + m.paga_el_seguro_gs == precio, (
                f"precio={precio} pct={pct}: "
                f"{m.paga_el_paciente_gs} + {m.paga_el_seguro_gs} != {precio}"
            )


def test_el_copago_lo_pone_el_paciente_ademas_de_su_parte():
    """Así está definido el convenio: el copago es un fijo que se le cobra
    al paciente, no algo que sale del bolsillo de la aseguradora."""
    m = repartir(100_000, Cobertura(70, 15_000, False, "convenio"))
    assert m.paga_el_seguro_gs == 70_000
    assert m.paga_el_paciente_gs == 30_000 + 15_000


def test_sin_convenio_paga_todo_el_paciente():
    m = repartir(200_000, None)
    assert m.paga_el_paciente_gs == 200_000
    assert m.paga_el_seguro_gs == 0


def test_un_estudio_excluido_no_lo_paga_el_seguro():
    """Aunque el convenio diga 80%: si el estudio está excluido, no cubre."""
    m = repartir(200_000, Cobertura(80, 0, True, "excepción para este estudio"))
    assert m.paga_el_paciente_gs == 200_000
    assert m.paga_el_seguro_gs == 0
    assert m.excluido


def test_un_porcentaje_imposible_no_devuelve_plata_de_la_nada():
    """Un 150% guardado por error no puede hacer que la aseguradora ponga más
    que el precio, ni un -20 que el paciente pague de más."""
    assert repartir(100_000, Cobertura(150, 0, False, "x")).paga_el_seguro_gs == 100_000
    assert repartir(100_000, Cobertura(-20, 0, False, "x")).paga_el_seguro_gs == 0
    assert repartir(-5, Cobertura(50, 0, False, "x")).precio_lista_gs == 0


def test_el_honorario_es_un_porcentaje_de_lo_facturado():
    assert honorario_gs(100_000, 100) == 100_000
    assert honorario_gs(100_000, 60) == 60_000
    assert honorario_gs(0, 60) == 0
    # Un porcentaje fuera de rango no le regala plata a nadie.
    assert honorario_gs(100_000, 250) == 100_000
    assert honorario_gs(100_000, -10) == 0


def test_el_convenio_se_encuentra_como_lo_escribe_el_paciente():
    """En WhatsApp nadie pone tildes ni sabe el nombre exacto del plan."""
    from app.db import SessionLocal
    from app.models import Insurer

    c = _create_company(name="Clínica Convenios")
    cid = c["id"]
    db = SessionLocal()
    try:
        db.add(Insurer(company_id=cid, name="Seguro Ñandutí", plan="Plan Oro",
                       coverage_pct=80, active=True))
        db.add(Insurer(company_id=cid, name="Seguro Ñandutí", plan="Básico",
                       coverage_pct=40, active=True))
        db.commit()

        oro = aranceles.buscar_convenio(db, cid, "seguro nanduti plan oro")
        assert oro is not None and oro.plan == "Plan Oro"
        # El plan importa: dos planes de la misma prepaga cubren distinto, y
        # confundirlos es darle al paciente un precio que no es el suyo.
        basico = aranceles.buscar_convenio(db, cid, "nanduti basico")
        assert basico is not None and basico.plan == "Básico"
        assert aranceles.buscar_convenio(db, cid, "una prepaga que no existe") is None
        assert aranceles.buscar_convenio(db, cid, "") is None
    finally:
        db.close()


def test_el_convenio_de_otra_empresa_no_se_encuentra():
    """No hay base compartida de aseguradoras: cada clínica carga LO QUE ELLA
    firmó. Encontrar el convenio de otra sería inventar un acuerdo."""
    from app.db import SessionLocal
    from app.models import Insurer

    a = _create_company(name="Clínica Convenio Propio")
    b = _create_company(name="Clínica Sin Convenios")
    db = SessionLocal()
    try:
        db.add(Insurer(company_id=a["id"], name="Prepaga Exclusiva", plan="",
                       coverage_pct=90, active=True))
        db.commit()
        assert aranceles.buscar_convenio(db, a["id"], "prepaga exclusiva") is not None
        assert aranceles.buscar_convenio(db, b["id"], "prepaga exclusiva") is None
    finally:
        db.close()
