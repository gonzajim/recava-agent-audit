// public/admin-panel/src/firebase.js
import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";
import { getFunctions, httpsCallable } from "firebase/functions";

const firebaseConfig = {
  apiKey: "AIzaSyBxUCiBCbofCAhc-Pi5DEgUPlajKvcJiok",
  authDomain: "divulgador-uclm-5b8b9.firebaseapp.com",
  projectId: "divulgador-uclm-5b8b9",
  storageBucket: "divulgador-uclm-5b8b9.firebasestorage.app",
  messagingSenderId: "596892874241",
  appId: "1:596892874241:web:a184e062be23746c587200",
  measurementId: "G-75K01Z3B5R"
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
const functions = getFunctions(app, "europe-west1"); // Asegurate de usar la region correcta

// Exportamos las funciones callable
export const getChatHistory = httpsCallable(functions, "getChatHistory");
export const updateExpertResponse = httpsCallable(functions, "updateExpertResponse");
