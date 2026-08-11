from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _sqlite_refuerza_claves_foraneas(dbapi_connection, connection_record):
    """SQLite arranca con PRAGMA foreign_keys = 0: NO refuerza nada.

    Los tests corren sobre SQLite. Sin este pragma, una prueba que intente
    ligar el doctor de una empresa con el servicio de otra pasaría igual —la
    base aceptaría el cruce— y tendríamos una suite verde certificando un
    aislamiento que no existe. Verificado empíricamente antes de escribir
    esto: sin el pragma el cruce se acepta; con él, IntegrityError.

    Se engancha al Engine genérico y no al nuestro porque los tests crean su
    propio engine en memoria.
    """
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
