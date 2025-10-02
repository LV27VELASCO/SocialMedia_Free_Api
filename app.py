from fastapi import Depends, FastAPI, HTTPException, Request, requests
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
    CODE_SERVICE,
    ACTION_INDEX,
    URL_SERVICE
)
from schemas import LoginSuccessResponse, NewOrderResponse, TokenResponse, ValidatePayResponse
import config
from db import supabase, jwt_token, get_client


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
     allow_origins=[
        "http://localhost:4321",
        "https://trendyup.com",
        "https://www.trendyup.com"
    ],
    allow_methods=["GET", "POST","OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
)



#Stripe
stripe.api_key = os.environ.get("SECRET_KEY_STRIPE")



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

        return JSONResponse(content=response.model_dump(), status_code=200)
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
                    message="Inicio de sesión exitoso",
                    token=token,
        )
        return JSONResponse(content=response.model_dump(), status_code=200)
    except:
        response = TokenResponse(
                    message="Ocurrió un error",
                    token='',
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

    try:
        # Recuperar fingerprint
        pm = stripe.PaymentMethod.retrieve(payment_method_id)
        fingerprint = pm.card.fingerprint

        now = datetime.now()
        card_used = consult_card_used(fingerprint)

        price = consult_product(platform,quantity)

        if price == "":
            return JSONResponse(content="Bad Request: price no válido", status_code=400)

        # Crear cliente y asociar método de pago
        customer = stripe.Customer.create(
            name=cardName,
            email=email,
            payment_method=payment_method_id,
            invoice_settings={"default_payment_method": payment_method_id},
        )

        # Si la tarjeta ya fue usada → compra normal
        if card_used:
            payment_intent = stripe.PaymentIntent.create(
                amount=price,  # aquí ajusta el importe real de la compra
                currency="eur",
                customer=customer.id,
                payment_method=payment_method_id,
                confirm=True,
                return_url=os.environ.get("URL_SUCCESS")
            )
        # Si la tarjeta NO ha sido usada → guardar en BD + compra de prueba + suscripción
        else:
            # Guardar tarjeta en BD
            insert_card = insert_card_used(fingerprint, jwt_token)

            payment_intent = stripe.PaymentIntent.create(
                amount=price,  # 1€ en céntimos
                currency="eur",
                customer=customer.id,
                payment_method=payment_method_id,
                confirm=True,
                return_url=os.environ.get("URL_SUCCESS")
            )

            # No hay reembolso, se deja el cobro
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
            message="Compra exitosa...",
            url=url,
            order_id=str("order_id"),
            )

        return JSONResponse(content=response.model_dump(), status_code=200)
    except Exception as e:
        return {"error": str(e)}