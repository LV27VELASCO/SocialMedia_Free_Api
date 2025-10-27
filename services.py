import os
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jwt import ExpiredSignatureError, PyJWTError, decode, encode
import requests
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from jinja2 import Environment, FileSystemLoader
from typing import Dict, Any, Optional
from db import supabase, get_client
from schemas import CreateUserOut
import config
import resend

# Variables globales
CODE_SERVICE = {
    "instagram": ["5712","4365","556"],
    "facebook": ["1636","1101","9598"],
    "tiktok": ["8521","2079","6990"]
}
ACTION_INDEX = {
    "followers": 0,
    "likes": 1,
    "views": 2
}

URL_SERVICE = {
    "instagram": "https://www.instagram.com/",
    "tiktok": "https://www.tiktok.com/@"
}

#MENSAJE DE IDIOMAS
MESSAGES = {
    "success_purchase": {
        "es": "Compra exitosa...",
        "en": "Purchase successful...",
        "fr": "Achat réussi...",
        "pt": "Compra bem-sucedida...",
        "de": "Kauf erfolgreich..."
    },
    "price_invalid": {
        "es": "Precio no válido",
        "en": "Invalid price",
        "fr": "Prix invalide",
        "pt": "Preço inválido",
        "de": "Ungültiger Preis"
    },
    "trial_used": {
        "es": "Lo sentimos, ya has usado tu prueba gratuita",
        "en": "Sorry, you have already used your free trial",
        "fr": "Désolé, vous avez déjà utilisé votre essai gratuit",
        "pt": "Desculpe, você já usou seu teste gratuito",
        "de": "Entschuldigung, Sie haben Ihre kostenlose Testversion bereits genutzt"
    },
    "contact_success": {
        "es": "Mensaje enviado con éxito.",
        "en": "Message sent successfully.",
        "fr": "Message envoyé avec succès.",
        "pt": "Mensagem enviada com sucesso.",
        "de": "Nachricht erfolgreich gesendet."
    },
    "contact_error": {
        "es": "Ocurrió un error al enviar el mensaje, intentarlo más tarde.",
        "en": "An error occurred while sending the message, please try later.",
        "fr": "Une erreur est survenue lors de l'envoi du message, veuillez réessayer plus tard.",
        "pt": "Ocorreu um erro ao enviar a mensagem, tente novamente mais tarde.",
        "de": "Beim Senden der Nachricht ist ein Fehler aufgetreten. Bitte versuchen Sie es später erneut."
    },
    "contact_unexpected": {
        "es": "Ocurrió un error inesperado, validar más tarde.",
        "en": "An unexpected error occurred, please check later.",
        "fr": "Une erreur inattendue est survenue, veuillez vérifier plus tard.",
        "pt": "Ocorreu um erro inesperado, verifique mais tarde.",
        "de": "Ein unerwarteter Fehler ist aufgetreten. Bitte überprüfen Sie es später erneut."
    },
    "email_required": {
        "es": "Email requerido",
        "en": "Email is required",
        "fr": "Email requis",
        "pt": "Email obrigatório",
        "de": "E-Mail ist erforderlich"
    },
    "unsubscribe_unexpected": {
        "es": "Ocurrió un error inesperado, validar más tarde.",
        "en": "An unexpected error occurred, please check later.",
        "fr": "Une erreur inattendue est survenue, veuillez vérifier plus tard.",
        "pt": "Ocorreu um erro inesperado, verifique mais tarde.",
        "de": "Ein unerwarteter Fehler ist aufgetreten. Bitte überprüfen Sie es später erneut."
    }
}

templates = {
    "en": "emailtemplate_en.html",
    "es": "emailtemplate_es.html",
    "fr": "emailtemplate_fr.html",
    "pt": "emailtemplate_pt.html",
    "de": "emailtemplate_de.html"
}


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


# Configuración del JWT
SECRET_KEY = os.environ.get("SECRET_JWT")
ALGORITHM = "HS256"
ACCESS2_TOKEN_EXPIRE_MINUTES=10
ACCESS_TOKEN_EXPIRE_MINUTES = 120

def generate_password(length: int = 12) -> str:
    """Genera una contraseña aleatoria segura."""
    import random, string
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def user_exists_by_email(email: str, client_supabase) -> Optional[dict]:
    response = client_supabase.table("Client") \
        .select("id") \
        .eq("email", email) \
        .limit(1) \
        .execute()
    return response.data[0] if response.data else None

def create_user(customer_name: str, customer_email: str, jwt_token: str, lang:str):
    client_supabase = get_client(jwt_token)
    user_id = client_supabase.auth.get_user().user.id

    if not customer_email:
        return CreateUserOut(status=False, message="Email requerido").dict(), 400

    customer_email = customer_email.lower()
    customer_password = generate_password()

    try:
        existing_user = user_exists_by_email(customer_email, client_supabase)
        
        if existing_user:
            client_id = existing_user["id"]
            if not update_client_password(client_supabase, client_id, customer_password):
                return CreateUserOut(status=False, message="Error al actualizar usuario").dict(), 500

            print("ENVIANDO CONTRASEÑA")
            send_email(customer_name, customer_email, customer_password, lang)
            return CreateUserOut(status=True, message="Contraseña actualizada", client_id=client_id).dict(), 200

        else:
            client_id = insert_client(client_supabase, customer_name,customer_email, customer_password, user_id)
            if not client_id:
                return CreateUserOut(status=False, message="Error al crear usuario").dict(), 500

            send_email(customer_name, customer_email, customer_password, lang)
            return CreateUserOut(status=True, message="Usuario creado", client_id=client_id).dict(), 201

    except Exception as e:
        print(f"[create_user] Error: {e}")
        return CreateUserOut(status=False, message=str(e)).dict(), 500

def update_client_password(client_supabase, client_id: int, new_password: str) -> bool:
    timestamp = datetime.utcnow().isoformat()
    response = client_supabase.table("Client") \
        .update({
            "password": new_password,
            "updated_at": timestamp
        }) \
        .eq("id", client_id) \
        .execute()
    return bool(response.data)

def insert_client(client_supabase, name:str, email: str, password: str, user_id: str) -> Optional[int]:
    response = client_supabase.table("Client") \
        .insert({
            "name": name,
            "email": email,
            "password": password,
            "user_id": user_id
        }).execute()
    return response.data[0]['id'] if response.data else None

def send_order(code_service: str, link: str, quantity: int = 1) -> Dict[str, Any]:
    JUSTANOTHER_URL = os.environ.get("JUSTANOTHER_URL")
    JUSTANOTHER_KEY = os.environ.get("JUSTANOTHER_KEY")

    if not JUSTANOTHER_URL or not JUSTANOTHER_KEY:
        return {"success": False, "order_id": None, "error": "Faltan variables de entorno"}

    try:
        payload = {
            "key": JUSTANOTHER_KEY,
            "action": "add",
            "service": code_service,
            "link": link,
            "quantity": quantity
        }
        response = requests.post(JUSTANOTHER_URL, data=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        print("Respuesta JustAnother:",data)
        return {"success": True, "order_id": data.get("order"), "error": None}

    except requests.exceptions.RequestException as e:
        print(e)
        return {"success": False, "order_id": None, "error": str(e)}
    except ValueError:
        print("error")
        return {"success": False, "order_id": None, "error": "Error al parsear JSON"}

def send_email(name: str, email: str, password: str, lang: str):
    htmlContent = build_template(name, email, password, lang)

    try:
        # Preparar parámetros para Resend
        params: resend.Emails.SendParams = {
            "from": f"{os.environ.get('FROM_NAME')} <{os.environ.get('FROM_EMAIL')}>",
            "to": [email],
            "subject": os.environ.get("SUBJECT_MAIL"),
            "html": htmlContent,
        }

        # Enviar email
        email_response = resend.Emails.send(params)
        print("Correo enviado")

    except Exception as e:
        print(e)

def build_template(name: str, email: str, password: str, lang:str) -> str:
    env = Environment(loader=FileSystemLoader('templates'))

    template_name = templates.get(lang.lower(), "emailtemplate_en.html")
    template = env.get_template(template_name)
    return template.render({"name": name, "email": email, "password": password})

def insert_order(client_id:str, order_id:str, jwt_token:str, social:str, service: str, quantity:int, url: str):
    client_supabase = get_client(jwt_token)
    user_id = client_supabase.auth.get_user().user.id
    insert_res = client_supabase.table("Orders").insert({
                "client_id": client_id,
                "order_id": order_id,
                "social": social,
                "service": service,
                "quantity": quantity,
                "url":url.strip(),
                "user_id":user_id
            }).execute()
    
def consult_card_used(fingerprint: str) -> bool:
    response_base = supabase.table("Users_cards") \
        .select("updated_at") \
        .eq("fingerprint", fingerprint) \
        .execute()
    
    if not response_base.data:
        return False  # No existe el registro
    
    updated_at_str = response_base.data[0]["updated_at"]
    updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
    
    hace_un_mes = datetime.now(updated_at.tzinfo) - timedelta(days=30)
    
    # ✅ True si fue actualizado hace menos de un mes
    return updated_at >= hace_un_mes

def insert_card_used(fingerprint:str, jwt_token:str):
    client_supabase = get_client(jwt_token)
    user_id = client_supabase.auth.get_user().user.id

    response_base = client_supabase.table("Users_cards").select("id,fingerprint").eq("fingerprint",fingerprint).execute()
    timestamp = datetime.utcnow().isoformat()

    if len(response_base.data) > 0:
        # ✅ Si existe, actualizar
        user_card_id = response_base.data[0]["id"]
        client_supabase.table("Users_cards") \
            .update({"updated_at": timestamp}) \
            .eq("id", user_card_id) \
            .execute()
    else:
        client_supabase.table("Users_cards") \
            .insert({
                "fingerprint": fingerprint,
                "created_at": timestamp,
                "updated_at": timestamp,
                "user_id": user_id
            }).execute()

def validate_login(email: str, password: str) -> dict | bool:
    response_base = supabase.table("Client").select("id,name,email,password").eq("email", email).execute()
    
    if response_base.data:
        user_data = response_base.data[0]
        if email == user_data["email"] and password == user_data["password"]:
            return {
                "id": user_data["id"],
                "name": user_data["name"]
            }
    
    return False

def create_jwt_token(user_data: dict, expires_delta: timedelta = None):
    to_encode = {
        "id": str(user_data["id"])
    }
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_jwt_auth(expires_delta: timedelta = None):
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS2_TOKEN_EXPIRE_MINUTES))
    to_encode = {"exp": expire}
    return encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Token inválido")
        return user_id
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Token inválido")
    
def validate_token(token: str = Depends(oauth2_scheme)):
    try:
        payload = decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        exp: str = payload.get("exp")
        if exp is None:
            raise HTTPException(status_code=401, detail="Token inválido")
        return exp
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Token inválido")
    
def get_data_user(id:int):
    response_base = supabase.table("Orders").select("order_id,social,service,quantity,created_at").eq("client_id", id).execute()
    
    return response_base.data

def get_data_user_completed(id:int):
    response_base = supabase.table("Orders").select("order_id,social,service,quantity,created_at,url").eq("client_id", id).execute()
    return response_base.data

def consult_user_by_email(email: str):
    response = supabase.table("Client").select("name,email,password") \
        .eq("email", email) \
        .limit(1) \
        .execute()
    return response.data

def consult_product(plataform: str, quantity:str) -> bool:
    response_base = supabase.table("Products") \
        .select("price") \
        .eq("plataform", plataform) \
        .eq("quantity", quantity) \
        .execute()
    
    if not response_base.data:
        return ""  # No existe el registro
    
    price = response_base.data[0]["price"]
    
    # ✅ True si fue actualizado hace menos de un mes
    return price

def unsuscribe_client(customer_email: str, jwt_token: str):
    client_supabase = get_client(jwt_token)
    user_id = client_supabase.auth.get_user().user.id
    customer_email = customer_email.lower()

    try:
        client_id = insert_unsuscribe(client_supabase,customer_email,user_id)
        if not client_id:
            return CreateUserOut(status=False, message="Ocurrió un error al procesar petición, intentarlo mas tarde.").dict(), 400
        else:
            return CreateUserOut(status=True, message="Suscripción cancelada con éxito").dict(), 200

    except Exception as e:
        print(f"[unsuscribe] Error: {e}")
        return CreateUserOut(status=False, message="Ocurrió un error, intentarlo más tarde").dict(), 500
    
def insert_unsuscribe(client_supabase, email: str,user_id:str) -> Optional[int]:
    response = client_supabase.table("Unsuscribe")\
        .insert({
            "email": email,
            "user_id":user_id
        }).execute()
    return response.data[0]['id'] if response.data else None

def get_message(key: str, locale: str = "en") -> str:
    return MESSAGES.get(key, {}).get(locale, MESSAGES.get(key, {}).get("en", ""))

def insert_pending_order(name:str, locale:str,username:str, email:str, platform:str, quantity:int, payment_id:str, jwt_token:str):
    client_supabase = get_client(jwt_token)
    user_id = client_supabase.auth.get_user().user.id
    client_supabase.table("Pending_orders") \
            .insert({
                "name": name,
                "username": username,
                "locale":locale,
                "email": email,
                "platform": platform,
                "quantity": quantity,
                "payment_intent": payment_id,
                "user_id": user_id
            }).execute()
    
def mark_order_as_paid(payment_id:str, jwt_token:str):
    client_supabase = get_client(jwt_token)
    user_id = client_supabase.auth.get_user().user.id
    response_base = client_supabase.table("Pending_orders").select("*").eq("payment_intent",payment_id).execute()

    if len(response_base.data) > 0:
        # ✅ actualizar
        order = response_base.data[0]
        order_id = response_base.data[0]["id"]
        client_supabase.table("Pending_orders") \
            .update({"success": True}) \
            .eq("id", order_id) \
            .execute()
        print(f"[INFO] Orden {order_id} marcada como pagada.")
        return order
    else:
        print(f"[WARN] No se encontró ninguna orden pendiente con payment_intent={payment_id}")
        return None
