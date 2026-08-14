"""Comparar texto como lo escribe la gente, no como está en la base."""
import unicodedata


def normalizar(texto: str) -> str:
    """Minúsculas sin tildes ni ñ, para comparar lo que la gente escribe.

    En WhatsApp nadie pone tildes: "Seguro Nanduti" tiene que encontrar
    "Seguro Ñandutí". Sin esto el sistema le dice al paciente que no hay
    convenio mientras se lo lista entre los disponibles.
    """
    limpio = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in limpio if unicodedata.category(c) != "Mn")


def formato_gs(monto: int) -> str:
    """1500000 → '₲ 1.500.000'. El guaraní no usa decimales."""
    return "₲ " + f"{int(monto or 0):,}".replace(",", ".")
