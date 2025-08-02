from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import stripe
import os
from datetime import datetime

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


stripe.api_key = os.environ.get("SECRET_KEY")

# Base de datos simulada en memoria
used_cards = []

@app.post("/validate-pay-method")
async def validate_pay_method(req: Request):
    data = await req.json()
    payment_method_id = data.get("paymentMethodId")
    email = data.get("email")
    socialMedia = data.get("socialMedia")
    url = data.get("url")
    typeService = data.get("accion")

    try:
        # Recuperar fingerprint
        pm = stripe.PaymentMethod.retrieve(payment_method_id)
        fingerprint = pm.card.fingerprint

        now = datetime.now()
        for entry in used_cards:
            if entry["fingerprint"] == fingerprint and entry["month"] == now.month and entry["year"] == now.year:
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
            return_url="http://localhost:4321/confirmation-success"  # ⚡ URL de retorno
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

        return {
            "success": True,
            "message": "Tarjeta validada con éxito, redirigiendo...",
            "subscription_id": subscription.id
        }

    except Exception as e:
        return {"error": str(e)}