const { initializeApp, applicationDefault } = require('firebase-admin/app');
const { getFirestore, FieldValue } = require('firebase-admin/firestore');
const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);

// La clave secreta del endpoint del webhook, para verificar la firma.
const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET;

// Inicializar Firebase
initializeApp({ credential: applicationDefault() });
const db = getFirestore();

exports.stripeWebhook = async (req, res) => {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    res.status(405).end('Method Not Allowed');
    return;
  }
  
  const sig = req.headers['stripe-signature'];
  let event;

  try {
    event = stripe.webhooks.constructEvent(req.rawBody, sig, webhookSecret);
  } catch (err) {
    console.error(`⚠️ Webhook signature verification failed.`, err.message);
    res.status(400).send(`Webhook Error: ${err.message}`);
    return;
  }

  if (event.type === 'checkout.session.completed') {
    const session = event.data.object;
    
    const userUid = session.metadata.user_uid;
    const creditsToAdd = parseInt(session.metadata.credits_to_add, 10);

    if (!userUid || !creditsToAdd) {
      console.error('Error: Missing metadata in Stripe session.', session.id);
      res.status(400).send('Error: Missing metadata.');
      return;
    }

    const userRef = db.collection('users').doc(userUid);
    try {
      await userRef.update({
        credits: FieldValue.increment(creditsToAdd)
      });
      console.log(`Successfully added ${creditsToAdd} credits to user ${userUid}.`);
    } catch (error) {
      console.error('Error updating user credits in Firestore:', error);
      // Si el usuario no existe, lo creamos
      if (error.code === 5) { // 'NOT_FOUND'
        try {
            await userRef.set({ credits: creditsToAdd });
            console.log(`User ${userUid} not found. Created new document with ${creditsToAdd} credits.`);
        } catch (set_error) {
            console.error('Failed to create new user document in Firestore:', set_error);
            res.status(500).send('Internal server error.');
            return;
        }
      } else {
        res.status(500).send('Internal server error.');
        return;
      }
    }
  }

  res.status(200).send({ received: true });
};