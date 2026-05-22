// public/admin-panel/src/firebase.js
import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";
import { getFirestore } from "firebase/firestore";
import { getFunctions, httpsCallable } from "firebase/functions";

const firebaseConfig = {
  apiKey: "AIzaSyAAlSxno1oBOtyhh7ntS2mv8rkAnWeAzmM",
  authDomain: "recava-buscador.firebaseapp.com",
  projectId: "recava-buscador",
  storageBucket: "recava-buscador.firebasestorage.app",
  messagingSenderId: "370417116045",
  appId: "1:370417116045:web:c282edf6a5c02cfd2d93c4",
  measurementId: "G-Y2MQZ54LLF"
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
// Firestore exportado con la instancia correcta del app
export const firestoreDb = getFirestore(app);

const functions = getFunctions(app, 'europe-west1');

// Exportamos las funciones callable
export const getChatHistory = httpsCallable(functions, 'getChatHistory');
export const updateExpertResponse = httpsCallable(functions, 'updateExpertResponse');