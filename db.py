import os
from supabase import Client, create_client
import config


SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
# Crear cliente
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


SUPABASE_EMAIL = os.environ.get("SUPABASE_EMAIL")
SUPABASE_PASSWORD = os.environ.get("SUPABASE_PASSWORD")
# 🔹 Autenticación con RLS
auth_res = supabase.auth.sign_in_with_password({
    "email": SUPABASE_EMAIL,
    "password": SUPABASE_PASSWORD
})



# JWT del usuario autenticado
jwt_token = auth_res.session.access_token

# Aplicar token al cliente PostgREST para respetar RLS
supabase.postgrest.auth(jwt_token)

def get_client(jwt_token: str = None) -> Client:
    """Devuelve el cliente supabase. Si hay JWT, aplica RLS."""
    client = supabase
    if jwt_token:
        client.postgrest.auth(jwt_token)
    return client