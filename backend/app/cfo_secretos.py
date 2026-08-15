"""Las credenciales de terceros que el sistema tiene que guardar.

Un conector REST necesita un token; uno de PostgreSQL, una contraseña. No hay
forma de sincronizar sin eso, así que la pregunta no es si guardarlos sino
cómo.

Se cifran con Fernet (AES-128-CBC + HMAC), de la biblioteca `cryptography`.
Escribir el cifrado a mano habría sido la peor decisión posible del archivo:
esto es exactamente lo que no se improvisa.

Tres cosas que valen más que el algoritmo:

1. **La llave vive en el entorno del servidor, no en la base.** Cifrar con una
   llave guardada al lado de lo cifrado es guardar en claro con pasos de más.

2. **Sin llave configurada no se crean conectores con credencial.** Falla
   ruidoso al crear, no silencioso al sincronizar: un despliegue a medias no
   puede terminar en credenciales guardadas en claro "por ahora".

3. **El valor descifrado no sale nunca por la API.** El panel sabe si hay
   credencial, jamás cuál es. Igual que el PIN.
"""
import os

_LLAVE = os.environ.get("CFO_SECRETS_KEY", "").strip()


class SinLlave(Exception):
    """No hay CFO_SECRETS_KEY. Es un error de despliegue, no del usuario."""


def hay_llave() -> bool:
    return bool(_LLAVE)


def _fernet():
    if not _LLAVE:
        raise SinLlave(
            "Falta CFO_SECRETS_KEY en el servidor. Sin esa llave no se pueden "
            "guardar credenciales de conectores."
        )
    from cryptography.fernet import Fernet

    try:
        return Fernet(_LLAVE.encode())
    except (ValueError, TypeError) as exc:
        raise SinLlave(
            f"CFO_SECRETS_KEY no tiene el formato de una llave Fernet: {exc}"
        )


def cifrar(valor: str) -> str:
    """Devuelve el texto cifrado, listo para guardar."""
    if not valor:
        return ""
    return _fernet().encrypt(valor.encode()).decode()


def descifrar(guardado: str) -> str:
    """Devuelve el valor. Solo lo llama quien va a usarlo para conectarse.

    Si la llave cambió, esto explota — y está bien: mejor un conector que
    falla ruidoso que uno que intenta autenticarse con basura y deja al
    sistema del cliente con intentos fallidos.
    """
    if not guardado:
        return ""
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(guardado.encode()).decode()
    except InvalidToken:
        raise SinLlave(
            "La credencial guardada no se puede descifrar con la llave "
            "actual. Si se rotó CFO_SECRETS_KEY, hay que volver a cargar las "
            "credenciales de los conectores."
        )


def generar_llave() -> str:
    """Para el despliegue. Se corre una vez y el valor va al .env del servidor."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()
