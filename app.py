from fastapi import Depends, FastAPI, HTTPException, Request, requests
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import stripe
import os
from datetime import datetime
from services import (
    create_user,
    send_order,
    insert_order,
    consult_card_used,
    insert_card_used,
    validate_login,
    create_jwt_token,
    get_current_user,
    get_data_user,
    CODE_SERVICE,
    ACTION_INDEX
)
from schemas import LoginSuccessResponse, ValidatePayResponse
import config
from db import supabase, jwt_token, get_client


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



#Stripe
stripe.api_key = os.environ.get("SECRET_KEY")

# Base de datos simulada en memoria
used_cards = []

@app.post("/validate-pay-method")
async def validate_pay_method(req: Request):
    data = await req.json()
    payment_method_id = data.get("paymentMethodId")
    name = data.get("name")
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
            email=email,
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

        # Registrar tarjeta usada
        used_cards.append({
            "fingerprint": fingerprint,
            "month": now.month,
            "year": now.year
        })

        #Obtenemos PriceId
        priceId = os.environ.get("PRICE_ID")

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
        result_order = send_order(code_service=code_service, link=url, quantity=500)

        order_id= result_order.get("order_id")

        # guardar orden con codigo usuario
        result_insert_order = insert_order(client_id,order_id, jwt_token, social, action, 500)

        response = ValidatePayResponse(
            success=True,
            message="Tarjeta validada con éxito, redirigiendo...",
            subscription_id=subscription.id,
            order_id=str(order_id),
            )

        return JSONResponse(content=response.model_dump(), status_code=200)
    except Exception as e:
        return {"error": str(e)}
    

@app.post("/login")
async def validate_pay_method(req: Request):
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
async def dashboard(id_user: str = Depends(get_current_user)):
    print(id_user)
    data_user = get_data_user(id_user)
    return data_user