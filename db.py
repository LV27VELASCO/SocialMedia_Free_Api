import os
from supabase import Client, create_client
import config
import time


SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SUPABASE_EMAIL = os.environ.get("SUPABASE_EMAIL")
SUPABASE_PASSWORD = os.environ.get("SUPABASE_PASSWORD")

# Crear cliente
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Sesión global
session = None
token_expiry = 0  # timestamp de expiración

# 🔹 Autenticación con RLS
auth_res = supabase.auth.sign_in_with_password({
    "email": SUPABASE_EMAIL,
    "password": SUPABASE_PASSWORD
})

def sign_in() -> str:
    """Inicia sesión y guarda la sesión y expiración global."""
    global session, token_expiry
    auth_res = supabase.auth.sign_in_with_password({
        "email": SUPABASE_EMAIL,
        "password": SUPABASE_PASSWORD
    })
    session = auth_res.session
    token_expiry = int(time.time()) + 3600  # el JWT dura ~1 hora
    supabase.postgrest.auth(session.access_token)
    return session.access_token

def refresh_if_needed() -> str:
    """Renueva el token si ha expirado y devuelve un JWT válido."""
    global session, token_expiry
    now = int(time.time())
    if not session or now >= token_expiry:
        if session and session.refresh_token:
            # Renovar usando refresh_token
            refreshed = supabase.auth.refresh_session(session.refresh_token)
            session = refreshed.session
            token_expiry = int(time.time()) + 3600
        else:
            # No hay refresh_token, iniciar sesión de nuevo
            sign_in()
    return session.access_token

def get_client(*args, **kwargs) -> Client:
    """Devuelve el cliente Supabase con RLS usando un JWT válido."""
    token = refresh_if_needed()
    supabase.postgrest.auth(token)
    return supabase