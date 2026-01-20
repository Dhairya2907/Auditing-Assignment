import uuid
import bcrypt
from db_sqlite import execute

def main():
    tenant_id = str(uuid.uuid4())
    admin_id = str(uuid.uuid4())

    tenant_name = "Acme"
    tenant_slug = "acme"

    email = "admin@acme.com"
    password = "ChangeThis123!"
    full_name = "Acme Admin"

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    execute("insert into tenants (id, name, slug) values (?, ?, ?)", (tenant_id, tenant_name, tenant_slug))
    execute(
        "insert into users (id, tenant_id, email, full_name, role, password_hash) values (?, ?, ?, ?, ?, ?)",
        (admin_id, tenant_id, email, full_name, "admin", password_hash),
    )

    print("Seeded tenant:", tenant_slug)
    print("Admin:", email)
    print("Password:", password)

if __name__ == "__main__":
    main()
