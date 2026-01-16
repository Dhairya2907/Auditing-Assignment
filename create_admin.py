import os
import json
import engine

tenant_code = "acme"
admin_username = "admin"
admin_password = "admin123"

print("Password JSON to store in DB:")
print(json.dumps(engine.make_password_record(admin_password), indent=2))
