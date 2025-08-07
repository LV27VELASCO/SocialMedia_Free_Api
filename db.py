import os
from supabase import Client, create_client
import config


SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
# Crear cliente
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# 🔹 Autenticación con RLS
auth_res = supabase.auth.sign_in_with_password({
    "email": "leduvelasco@gmail.com",
    "password": "162716"
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