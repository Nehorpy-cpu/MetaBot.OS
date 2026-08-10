"""Alta de usuarios y membresías.

Uso (dentro del contenedor backend):
    python scripts/crear_usuario.py <email> <password> [--platform-admin]
    python scripts/crear_usuario.py <email> <password> --company <id> --role owner

Roles: owner | admin | operator | viewer
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import hash_password, MIN_PASSWORD_LEN  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Company, Membership, User  # noqa: E402
from app.permissions import Role  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    parser.add_argument("password")
    parser.add_argument("--platform-admin", action="store_true")
    parser.add_argument("--company", type=int)
    parser.add_argument("--role", default=Role.OWNER.value)
    parser.add_argument("--name", default="")
    args = parser.parse_args()

    if len(args.password) < MIN_PASSWORD_LEN:
        sys.exit(f"La contraseña debe tener al menos {MIN_PASSWORD_LEN} caracteres.")
    if args.role not in {r.value for r in Role}:
        sys.exit(f"Rol inválido. Válidos: {', '.join(r.value for r in Role)}")

    db = SessionLocal()
    try:
        email = args.email.lower().strip()
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.password_hash = hash_password(args.password)
            if args.platform_admin:
                user.is_platform_admin = True
            print(f"Usuario existente actualizado: {email}")
        else:
            user = User(
                email=email,
                password_hash=hash_password(args.password),
                full_name=args.name,
                is_platform_admin=args.platform_admin,
            )
            db.add(user)
            db.flush()
            print(f"Usuario creado: {email} (platform_admin={args.platform_admin})")

        if args.company:
            company = db.get(Company, args.company)
            if not company:
                sys.exit(f"No existe la empresa {args.company}")
            existing = (
                db.query(Membership)
                .filter(Membership.user_id == user.id, Membership.company_id == args.company)
                .first()
            )
            if existing:
                existing.role = args.role
                existing.status = "active"
                print(f"Membresía actualizada: {company.name} → {args.role}")
            else:
                db.add(Membership(user_id=user.id, company_id=args.company, role=args.role))
                print(f"Membresía creada: {company.name} → {args.role}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
