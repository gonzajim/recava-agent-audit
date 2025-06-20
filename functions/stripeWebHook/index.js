const { initializeApp, applicationDefault } = require('firebase-admin/app');
const { getFirestore, FieldValue } = require('firebase-admin/firestore');
const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);

// La clave secreta del endpoint del webhook, para verificar la firma.
// Debe configurarse como variable de entorno en la Cloud Function.
const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET;

// Inicializar Firebase
initializeApp({ credential: applicationDefault() });
const db = getFirestore();

exports.stripeWebhook = async (req, res) => {
  // Solo procesar peticiones POST
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    res.status(405).end('Method Not Allowed');
    return;
  }
  
  const sig = req.headers['stripe-signature'];
  let event;

  try {
    // Verificar que la petición viene de Stripe
    event = stripe.webhooks.constructEvent(req.rawBody, sig, webhookSecret);
  } catch (err) {
    console.error(`⚠️ Webhook signature verification failed.`, err.message);
    res.status(400).send(`Webhook Error: ${err.message}`);
    return;
  }

  // Manejar solo el evento de pago exitoso
  if (event.type === 'checkout.session.completed') {
    const session = event.data.object;
    
    // Extraer los metadatos que guardamos al crear la sesión
    const userUid = session.metadata.user_uid;
    const creditsToAdd = parseInt(session.metadata.credits_to_add, 10);

    if (!userUid || !creditsToAdd) {
      console.error('Error: Missing metadata in Stripe session.', session.id);
      res.status(400).send('Error: Missing metadata.');
      return;
    }

    // Actualizar el saldo del usuario en Firestore
    const userRef = db.collection('users').doc(userUid);
    try {
      // Usar FieldValue.increment() para una actualización atómica y segura
      await userRef.update({
        credits: FieldValue.increment(creditsToAdd)
      });
      console.log(`Successfully added ${creditsToAdd} credits to user ${userUid}.`);
    } catch (error) {
      console.error('Error updating user credits in Firestore:', error);
      res.status(500).send('Internal server error.');
      return;
    }
  }

  // Devolver una respuesta 200 para confirmar la recepción del evento
  res.status(200).send({ received: true });
};
