"""Roles y permisos del tenant.

Vive en código (no en la base) a propósito: un cambio de permisos tiene que
verse en el diff de un commit y pasar por revisión, no editarse en caliente.
"""
from enum import Enum


class Role(str, Enum):
    OWNER = "owner"        # dueño: todo + miembros + claves + auditoría
    ADMIN = "admin"        # operación completa + prompts + canales
    OPERATOR = "operator"  # día a día: citas, chats, catálogo, campañas
    VIEWER = "viewer"      # solo lectura


class Perm(str, Enum):
    READ = "read"                  # ver datos de la empresa
    OPERATE = "operate"            # citas, conversaciones, catálogo, servicios
    CONFIGURE_AGENTS = "configure_agents"  # prompts, modelos, temperaturas
    MANAGE_CHANNELS = "manage_channels"    # WhatsApp, QR, tokens de Meta
    MANAGE_MEMBERS = "manage_members"      # invitar/quitar usuarios
    VIEW_AUDIT = "view_audit"              # bitácora de accesos


ROLE_PERMS: dict[Role, frozenset[Perm]] = {
    Role.OWNER: frozenset(Perm),
    Role.ADMIN: frozenset(
        {Perm.READ, Perm.OPERATE, Perm.CONFIGURE_AGENTS, Perm.MANAGE_CHANNELS}
    ),
    Role.OPERATOR: frozenset({Perm.READ, Perm.OPERATE}),
    Role.VIEWER: frozenset({Perm.READ}),
}


def role_has(role: str, perm: Perm) -> bool:
    try:
        return perm in ROLE_PERMS[Role(role)]
    except ValueError:
        return False
