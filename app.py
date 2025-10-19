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
    send_email,
    unsuscribe_client,
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

@app.post("/validate-pay-method")
async def validate_pay_method(req: Request,exp: str = Depends(validate_token)):
    data = await req.json()
    payment_method_id = data.get("paymentMethodId")
    name = data.get("name")
    cardName = data.get("cardName")
    email = data.get("email")
    social = data.get("socialMedia")
    url = data.get("url")
    action = data.get("accion")

    try:
        # Recuperar fingerprint
        pm = stripe.PaymentMethod.retrieve(payment_method_id)
        fingerprint = pm.card.fingerprint

        now = datetime.now()
        card_used = consult_card_used(fingerprint)

        if card_used:
                return {"error": "Esta tarjeta ya fue usada este mes."}
        
        # Crear cliente y asociar método de pago
        customer = stripe.Customer.create(
            name=cardName.strip().lower(),
            email=email.strip().lower(),
            payment_method=payment_method_id,
            invoice_settings={"default_payment_method": payment_method_id},
        )

        # Cobro de prueba 1€ (100 céntimos)
        payment_intent = stripe.PaymentIntent.create(
            amount=100,
            currency="eur",
            customer=customer.id,
            payment_method=payment_method_id,
            confirm=True,
            return_url= os.environ.get("URL_SUCCESS")  # ⚡ URL de retorno
        )

        # Reembolso inmediato
        stripe.Refund.create(payment_intent=payment_intent.id)

        #Obtenemos PriceId
        priceId = os.environ.get("PRICE_ID_STRIPE")

        # Crear suscripción con trial de 14 días
        subscription = stripe.Subscription.create(
            customer=customer.id,
            items=[{"price": priceId}],
            trial_period_days=14,
            default_payment_method=payment_method_id,
            expand=["latest_invoice.payment_intent"]
        )

        
        jwt_token = refresh_if_needed()
        insert_card = insert_card_used(fingerprint,jwt_token)

        user_created_response, status_code = create_user(name, email, jwt_token)

        client_id = user_created_response.get("client_id")  # Extrae el client_id del dict de respuesta

        # Obtener el código de servicio correspondiente
        code_service = CODE_SERVICE[social][ACTION_INDEX[action]]

        # Llamar a la función que envía la orden
        result_order = send_order(code_service, url, 500)

        order_id= result_order.get("order_id")

        # guardar orden con codigo usuario
        result_insert_order = insert_order(client_id,order_id, jwt_token, social, action, 500,url)

        # response = ValidatePayResponse(
        #     success=True,
        #     message="Tarjeta validada con éxito, redirigiendo...",
        #     subscription_id=subscription.id,
        #     order_id=str(order_id),
        #     )

        return JSONResponse(content="response.model_dump()", status_code=200)
    except Exception as e:
        return {"error": str(e)}

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
    
@app.post("/checkout")
async def checkout(req: Request,exp: str = Depends(validate_token)):
    data = await req.json()
    payment_method_id = data.get("paymentMethodId")
    cardName = data.get("cardName")
    username = data.get("username")
    email = data.get("email")
    platform = data.get("platform")
    quantity = data.get("quantity")
    locale = data.get("locale")

    try:
        # Recuperar fingerprint
        pm = stripe.PaymentMethod.retrieve(payment_method_id)
        fingerprint = pm.card.fingerprint

        print(fingerprint)
        now = datetime.now()
        card_used = consult_card_used(fingerprint)

        price = consult_product(platform,quantity)

        if price == "":
            return JSONResponse(content={"error": get_message("price_invalid", locale)}, status_code=400)

        jwt_token = refresh_if_needed()

        url_base = os.environ.get("URL_BASE_SUCCESS")
        path = os.environ.get("URL_PATH")

        url_success = f"{url_base}/{locale}/{path}"
        
        # Si la tarjeta ya fue usada  y no ha usado prueba gratuita → compra normal
        if card_used:
            if price == 0:
                # cliente usó prueba gratuita
                return JSONResponse(content={"error": get_message("trial_used", locale)}, status_code=400)
            else:
                
                # Crear cliente y asociar método de pago
                customer = stripe.Customer.create(
                    name=cardName,
                    email=email,
                    payment_method=payment_method_id,
                    invoice_settings={"default_payment_method": payment_method_id},
                )
                # Realizar compra normal
                payment_intent = stripe.PaymentIntent.create(
                    amount=price,
                    currency="eur",
                    customer=customer.id,
                    payment_method=payment_method_id,
                    confirm=True,
                    return_url = url_success
                )
        # Si la tarjeta NO ha sido usada → guardar en BD + compra de prueba + suscripción
        else:
            # Guardar tarjeta en BD
            insert_card = insert_card_used(fingerprint, jwt_token)
            
            # Crear cliente y asociar método de pago
            customer = stripe.Customer.create(
                    name=cardName,
                    email=email,
                    payment_method=payment_method_id,
                    invoice_settings={"default_payment_method": payment_method_id},
            )

            if price == 0:
                
                # Seguidores gratis
                # Cobro de prueba 1€ (100 céntimos)
                payment_intent = stripe.PaymentIntent.create(
                    amount=100,
                    currency="eur",
                    customer=customer.id,
                    payment_method=payment_method_id,
                    confirm=True,
                    return_url= url_success # ⚡ URL de retorno
                )

                # Reembolso inmediato
                stripe.Refund.create(payment_intent=payment_intent.id)
            else:
                
                #se crea el pago normal
                payment_intent = stripe.PaymentIntent.create(
                    amount=price,  # precio
                    currency="eur",
                    customer=customer.id,
                    payment_method=payment_method_id,
                    confirm=True,
                    return_url = url_success
                )

            # Obtener PriceId
            priceId = os.environ.get("PRICE_ID_STRIPE")

            # Crear suscripción con trial de 14 días
            subscription = stripe.Subscription.create(
                customer=customer.id,
                items=[{"price": priceId}],
                trial_period_days=14,
                default_payment_method=payment_method_id,
                expand=["latest_invoice.payment_intent"]
            )

        user_created_response, status_code = create_user(cardName, email, jwt_token)

        client_id = user_created_response.get("client_id")  # Extrae el client_id del dict de respuesta

        # Obtener el código de servicio correspondiente
        code_service = CODE_SERVICE[platform][ACTION_INDEX["followers"]]
        
        url = URL_SERVICE[platform] + username

        # Llamar a la función que envía la orden
        result_order = send_order(code_service, url, quantity)

        order_id= result_order.get("order_id")

        # guardar orden con codigo usuario
        result_insert_order = insert_order(client_id,order_id, jwt_token, platform, "followers", quantity,url)

        response = ValidatePayResponse(
            success=True,
            message=get_message("success_purchase", locale),
            url=url,
            order_id=str("order_id"),
            )

        return JSONResponse(content=response.model_dump(), status_code=200)
    except Exception as e:
        return {"error": str(e)}

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
