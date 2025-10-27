from fastapi import Depends, FastAPI, HTTPException, Request
import requests
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import stripe
import os
from datetime import datetime, timedelta, timezone
from services import (
    create_user,
    send_order,
    insert_order,
    consult_card_used,
    consult_product,
    insert_card_used,
    validate_login,
    create_jwt_token,
    create_jwt_auth,
    get_current_user,
    get_data_user,
    get_data_user_completed,
    validate_token,
    consult_user_by_email,
    mark_order_as_paid,
    send_email,
    unsuscribe_client,
    insert_pending_order,
    get_message,
    CODE_SERVICE,
    ACTION_INDEX,
    URL_SERVICE
)
from schemas import LoginSuccessResponse, NewOrderResponse, TokenResponse, ValidatePayResponse
import config
from db import supabase, refresh_if_needed, get_client
from jinja2 import Environment, FileSystemLoader
import resend

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
     allow_origins=[
        "http://localhost:4321",
        "https://trendyup.es",
        "https://www.trendyup.es"
    ],
    allow_methods=["GET", "POST","OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
)



#Stripe
stripe.api_key = os.environ.get("SECRET_KEY_STRIPE")
#resend
resend.api_key =os.environ.get("RESEND_API_KEY")


@app.post("/login")
async def login(req: Request, exp: str = Depends(validate_token)):
     data = await req.json()
     email = data.get("email", "").strip()
     password = data.get("password", "").strip()
     login_data = validate_login(email, password)
     if login_data:
        token = create_jwt_token(login_data)
        return LoginSuccessResponse(
            message="Inicio de sesión exitoso",
            user=login_data["name"],
            access_token=token
        )
     else:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

@app.get("/dashboard")
async def dashboard(id_client: str = Depends(get_current_user)):
    data_user = get_data_user(id_client)
    return data_user

@app.get("/new-order")
async def new_order(id_client: str = Depends(get_current_user)):
    try:
        data_user = get_data_user_completed(id_client)
        # si no tiene  error
        if not data_user:
            response = NewOrderResponse(
                message="No hay órdenes."
            )
            return JSONResponse(content=response.model_dump(), status_code=404)
        
        if len(data_user) > 3:
            # Si tiene mas de 3 registros no hará mas
            response = NewOrderResponse(
                message="Limite de seguidores alcanzado."
            )
            return JSONResponse(content=response.model_dump(), status_code=200)

        fechas = [datetime.fromisoformat(item["created_at"]) for item in data_user]
        max_fecha = max(fechas)

        ahora = datetime.now(timezone.utc)  # Ahora aware en UTC
        diferencia = ahora - max_fecha

        if diferencia > timedelta(weeks=1):
            social = data_user[0]["social"]
            action = data_user[0]["service"]
            url = data_user[0]["url"]
            quantity = 500 #por defecto
            
            # Obtener el código de servicio correspondiente
            code_service = CODE_SERVICE[social][ACTION_INDEX[action]]

            result_order = send_order(code_service, url, quantity)
            order_id= result_order.get("order_id")
            jwt_token = refresh_if_needed()
            # guardar orden con codigo usuario
            result_insert_order = insert_order(id_client,order_id, jwt_token, social, action, quantity,url)
            response = NewOrderResponse(
                message="Orden generada con éxito!"
            )
            return JSONResponse(content=response.model_dump(), status_code=200)
        else:
            response = NewOrderResponse(
                message="Aun no tienes una semana desde tu ultima orden."
            )
            return JSONResponse(content=response.model_dump(), status_code=404)
    except Exception as e:
        response = NewOrderResponse(
                message="Ocurrió un error inesperado, validar mas tarde."
            )
        return JSONResponse(content=response.model_dump(), status_code=404)

@app.get("/token")
async def token():
    try:
        token = create_jwt_auth()
        response = TokenResponse(
                    message="Login successful",
                    token=token,
        )
        return JSONResponse(content=response.model_dump(), status_code=200)
    except:
        response = TokenResponse(
                    message="An error occurred",
                    token=''
        )
        return JSONResponse(content=response.model_dump(), status_code=400)

@app.post("/recovery-password")
async def recovery_password(
    req: Request, exp: str = Depends(validate_token)):
    data = await req.json()
    email = data.get("email", "").strip()
    try:
       data_user = consult_user_by_email(email)
       if not data_user:
            response = NewOrderResponse(
                message="Usuario no existe."
            )
            return JSONResponse(content=response.model_dump(), status_code=404)
       

       customer_name = data_user[0]["name"]
       customer_email = data_user[0]["email"]
       customer_password = data_user[0]["password"]
       send_email(customer_name, customer_email, customer_password)
       response = NewOrderResponse(
                message="Contraseña enviada con éxito, por favor revisar email."
            )
       return JSONResponse(content=response.model_dump(), status_code=200)
    except Exception as e:
        response = NewOrderResponse(
                 message="Ocurrió un error inesperado, validar mas tarde."
             )
        return JSONResponse(content=response.model_dump(), status_code=404)

@app.post("/contact-mesagge")
async def recovery_password(
    req: Request, exp: str = Depends(validate_token)):
    data = await req.json()
    name = data.get("name")
    email = data.get("email")
    textarea = data.get("textarea")
    locale = data.get("locale")
    try:
       url = os.environ.get("EMAILJS_URL")
       service_id = os.environ.get("SERVICE_ID")
       template_id = os.environ.get("TEMPLATE_ID")
       user_id = os.environ.get("USER_ID")

       payload = {
            "service_id": service_id,
            "template_id": template_id,
            "user_id": user_id,   # tu Public Key de EmailJS
            "template_params": {
                "name_user": name,
                "message_user": textarea,
                "email_user": email
            }
        }
       headers = { "Content-Type": "application/json" }
       
       response = requests.post(url, json=payload, headers=headers)
       if response.status_code == 200:
            response = NewOrderResponse(message=get_message("contact_success", locale))
            return JSONResponse(content=response.model_dump(), status_code=200)
       else:
            response = NewOrderResponse(message=get_message("contact_error", locale))
            return JSONResponse(content=response.model_dump(), status_code=400)
    except Exception as e:
        response = NewOrderResponse(message=get_message("contact_unexpected", locale))
        return JSONResponse(content=response.model_dump(), status_code=404)

@app.post("/unsuscribe")
async def recovery_password(
    req: Request, exp: str = Depends(validate_token)):
    data = await req.json()
    email = data.get("email")
    locale = data.get("locale")
    try:
       
       if not email:
           return JSONResponse(content={"error": get_message("email_required", locale)}, status_code=400)
       
       jwt_token = refresh_if_needed()
       user_unsuscribe_response, status_code = unsuscribe_client(email, jwt_token)
       status = user_unsuscribe_response.get("status")
       message_res = user_unsuscribe_response.get("message")
       if status:
           response = NewOrderResponse(message=message_res)
           return JSONResponse(content=response.model_dump(), status_code=200)
       else:
            response = NewOrderResponse(message=message_res)
            return JSONResponse(content=response.model_dump(), status_code=400)
    except Exception as e:
        print(e)
        response = NewOrderResponse(message=get_message("unsubscribe_unexpected", locale))
        return JSONResponse(content=response.model_dump(), status_code=404)

@app.post("/checkout")
async def checkout(req: Request, exp: str = Depends(validate_token)):
    data = await req.json()
    payment_method_id = data.get("paymentMethodId")
    name = data.get("cardName")
    username = data.get("username")
    email = data.get("email")
    platform = data.get("platform")
    quantity = data.get("quantity")
    locale = data.get("locale")

    try:
        # 🔍 Recuperar fingerprint de la tarjeta
        pm = stripe.PaymentMethod.retrieve(payment_method_id)
        fingerprint = pm.card.fingerprint

        # ✅ Verificar si ya usó prueba gratuita
        card_used = consult_card_used(fingerprint)

        # Calcular precio del producto
        price = consult_product(platform, quantity)
        if price == "":
            return JSONResponse(content={"error": get_message("price_invalid", locale)}, status_code=400)

        jwt_token = refresh_if_needed()
        url_base = os.environ.get("URL_BASE_SUCCESS")
        path = os.environ.get("URL_PATH")
        url_success = f"{url_base}/{locale}/{path}"

        # 🚫 Si ya usó la tarjeta y el precio = 0 (prueba)
        if card_used and price == 0:
            return JSONResponse(
                content={"error": get_message("trial_used", locale)},
                status_code=400,
            )

        # 🧾 Crear cliente
        customer = stripe.Customer.create(
            name=name,
            email=email,
            payment_method=payment_method_id,
            invoice_settings={"default_payment_method": payment_method_id},
        )

        # 💳 Crear PaymentIntent (solo se confirma en frontend)
        # Si nunca usó prueba y el precio = 0 → cobro de prueba de 1€
        amount = 100 if (not card_used and price == 0) else price

        payment_intent = stripe.PaymentIntent.create(
            amount=amount,
            currency="eur",
            customer=customer.id,
            payment_method=payment_method_id,
            confirmation_method="automatic",
        )

        # 🗄️ Guardar que la tarjeta fue usada (solo si aún no estaba)
        if not card_used:
            insert_card_used(fingerprint, jwt_token)

        # ✅ Si es prueba gratuita → crear suscripción + reembolso automático
        if not card_used and price == 0:
            priceId = os.environ.get("PRICE_ID_STRIPE")

            subscription = stripe.Subscription.create(
                customer=customer.id,
                items=[{"price": priceId}],
                trial_period_days=14,
                default_payment_method=payment_method_id,
                expand=["latest_invoice.payment_intent"]
            )

        # Guardar pedido pendiente en tu BD
        insert_pending_order(name,locale, username, email, platform, quantity, payment_intent.id, jwt_token)

        return JSONResponse({
            "clientSecret": payment_intent.client_secret,
        })

    except Exception as e:
        print(e)
        return JSONResponse(content={"error": str(e)}, status_code=400)

@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    print("Webhook iniciado")
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.environ.get("WEBHOOK_SECRET")
        )
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid signature"})

    if event["type"] == "payment_intent.succeeded":
        payment_intent = event["data"]["object"]
        payment_id = payment_intent["id"]
        
        print("Pago exitoso para: ",payment_id)
        jwt_token = refresh_if_needed()

        # Marcar en tu BD como pagado
        order = mark_order_as_paid(payment_id,jwt_token)
        name = order["name"]
        email = order["email"]
        platform = order["platform"]
        username = order["username"]
        quantity = order["quantity"]
        locale = order["locale"]

        if quantity < 500:
            print("Reembolso automático procesado (prueba gratuita)")
            stripe.Refund.create(payment_intent=payment_id)

        user_created_response, status_code = create_user(name, email, jwt_token, locale)
        client_id = user_created_response.get("client_id")

        code_service = CODE_SERVICE[platform][ACTION_INDEX["followers"]]
        url = URL_SERVICE[platform] + username

        result_order = send_order(code_service, url, quantity)
        order_id= result_order.get("order_id")

        insert_order(client_id, order_id, jwt_token, platform, "followers", quantity, url)

    return JSONResponse(status_code=200, content={"success": True})
