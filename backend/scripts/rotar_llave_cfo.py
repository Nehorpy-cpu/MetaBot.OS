"""Rota CFO_SECRETS_KEY sin perder las credenciales guardadas.

El día que haya que rotar —alguien vio el `.env`, se fue un empleado, o
simplemente pasó el tiempo— sin esto la única salida es pedirle a cada cliente
que vuelva a cargar la contraseña de su ERP. Eso, en la práctica, significa
que la llave no se rota nunca.

Cómo funciona: descifra con la llave VIEJA y vuelve a cifrar con la NUEVA, en
una transacción. Si algo falla, no queda nada a medias.

    # 1. Generar la llave nueva
    docker compose run --rm backend python -c \\
        "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    # 2. Rotar (la vieja sale del .env, la nueva se pasa por argumento)
    docker compose run --rm backend python scripts/rotar_llave_cfo.py <llave_nueva>

    # 3. Recién ahora, reemplazar CFO_SECRETS_KEY en el .env y reiniciar

El orden importa: si se cambia el .env primero, el script arranca sin poder
descifrar nada y no hay vuelta atrás automática.

No imprime ninguna credencial, ni la vieja ni la nueva.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import cfo_secretos  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import FinanceConnector  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Uso: python scripts/rotar_llave_cfo.py <llave_nueva>")
    nueva = sys.argv[1].strip()

    if not cfo_secretos.hay_llave():
        sys.exit(
            "No hay CFO_SECRETS_KEY en el entorno. Tiene que estar la VIEJA "
            "para poder descifrar lo guardado."
        )

    from cryptography.fernet import Fernet

    try:
        fernet_nuevo = Fernet(nueva.encode())
    except (ValueError, TypeError):
        sys.exit("La llave nueva no tiene formato Fernet válido.")

    db = SessionLocal()
    try:
        filas = (
            db.query(FinanceConnector)
            .filter(FinanceConnector.secreto_cifrado != "")
            .all()
        )
        if not filas:
            print("No hay credenciales guardadas: se puede cambiar la llave "
                  "directamente en el .env.")
            return

        print(f"Credenciales a rotar: {len(filas)}")
        # Se descifra TODO primero. Si una sola falla, no se toca ninguna: una
        # rotación a medias deja unas credenciales con la llave vieja y otras
        # con la nueva, y ninguna de las dos abre todo.
        en_claro = {}
        for f in filas:
            try:
                en_claro[f.id] = cfo_secretos.descifrar(f.secreto_cifrado)
            except cfo_secretos.SinLlave as exc:
                sys.exit(
                    f"El conector {f.id} (empresa {f.company_id}) no se pudo "
                    f"descifrar con la llave actual: {exc}. No se rotó nada."
                )

        for f in filas:
            f.secreto_cifrado = fernet_nuevo.encrypt(
                en_claro[f.id].encode()
            ).decode()
        db.commit()
        print(f"Listo: {len(filas)} credenciales recifradas.")
        print("Ahora sí, cambiá CFO_SECRETS_KEY en el .env y reiniciá el "
              "backend.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
