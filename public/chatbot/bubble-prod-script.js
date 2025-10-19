document.addEventListener('DOMContentLoaded', function() {
  // ========================================================================
  // ### 1) CONFIGURACIÓN DE FIREBASE ###
  // ========================================================================

  const firebaseConfig = {
    apiKey: "AIzaSyAAlSxno1oBOtyhh7ntS2mv8rkAnWeAzmM",
    authDomain: "recava-auditor-dev.firebaseapp.com",
    projectId: "recava-auditor-dev",
    storageBucket: "recava-auditor-dev.firebasestorage.app",
    messagingSenderId: "370417116045",
    appId: "1:370417116045:web:41c77969d5d880382d93c4",
    measurementId: "G-2J8TTR4SD2"
  };

  firebase.initializeApp(firebaseConfig);
  const auth = firebase.auth();

  // SOLO en local:
  if (location.hostname === 'localhost') {
    firebase.auth().useEmulator('http://localhost:9099/');
    // firebase.firestore().useEmulator('localhost', 8080);
  }

  // endpoints (una sola vez) + switch local/prod
  const endpoints = {
    prod: {
      auditor: 'https://orchestrator-520199812528.europe-west1.run.app/chat_auditor',
      advisor: 'https://orchestrator-520199812528.europe-west1.run.app/chat_assistant'
    },
    local: {
      auditor: 'http://localhost:8080/chat_auditor',
      advisor: 'http://localhost:8080/chat_assistant'
    }
  };
  let currentEndpoints = (location.hostname === 'localhost') ? endpoints.local : endpoints.prod;

  // ========================================================================
  // ### 2) SELECTORES ###
  // ========================================================================

  const loginViewEl = document.getElementById('login-view');
  const emailInputEl = document.getElementById('email-input');
  const passwordInputEl = document.getElementById('password-input');
  const loginButtonEl = document.getElementById('login-button');
  const registerButtonEl = document.getElementById('register-button');
  const loginErrorEl = document.getElementById('login-error');

  const chatBubbleEl = document.getElementById('chat-bubble');
  const chatWidgetContainerEl = document.getElementById('chat-widget-container');
  const chatCloseButtonEl = document.getElementById('chat-close-button');

  const chatMessagesEl = document.getElementById('chat-messages');
  const inputAreaWrapperEl = document.getElementById('input-area-wrapper');
  const userInputEl = document.getElementById('user-input');
  const sendButtonEl = document.getElementById('send-button');
  const attachFileButtonEl = document.getElementById('attach-file-button');

  let currentUser = null;

  // ========================================================================
  // ### 3) HELPERS: verificación, reset y token verificado ###
  // ========================================================================

  async function sendVerificationIfNeeded(user) {
    try { if (user && !user.emailVerified) { await user.sendEmailVerification(); } }
    catch (e) { console.error("No se pudo enviar el email de verificación:", e); }
  }

  async function reloadAndCheckVerification() {
    if (!auth.currentUser) return false;
    await auth.currentUser.reload();
    return !!auth.currentUser.emailVerified;
  }

  async function getVerifiedIdTokenOrThrow() {
    const u = auth.currentUser;
    if (!u) throw new Error("No autenticado");
    if (!u.emailVerified) throw new Error("Email no verificado");
    return await u.getIdToken(true);
  }

  // ========================================================================
  // ### 4) BANNER DINÁMICO PARA VERIFICACIÓN ###
  // ========================================================================

  const verifyBanner = document.createElement('div');
  verifyBanner.style.display = 'none';
  verifyBanner.style.padding = '12px';
  verifyBanner.style.margin = '12px 0';
  verifyBanner.style.border = '1px solid #f0c36d';
  verifyBanner.style.background = '#fff8e1';
  verifyBanner.style.borderRadius = '8px';
  verifyBanner.innerHTML = `
    <strong>Revisa tu correo:</strong> te hemos enviado un email para verificar tu cuenta.<br/>
    <div style="margin-top:8px; display:flex; gap:8px; flex-wrap:wrap;">
      <button id="btn-verify-retry" class="btn">Ya lo verifiqué</button>
      <button id="btn-verify-resend" class="btn">Reenviar verificación</button>
      <button id="btn-verify-logout" class="btn">Cerrar sesión</button>
      <button id="btn-reset-password" class="btn" style="margin-left:auto;">Olvidé mi contraseña</button>
    </div>
  `;
  if (loginViewEl) loginViewEl.appendChild(verifyBanner);

  verifyBanner.addEventListener('click', async (e) => {
    const id = e.target?.id;
    try {
      if (id === 'btn-verify-retry') {
        const ok = await reloadAndCheckVerification();
        if (ok) {
          if (loginErrorEl) { loginErrorEl.style.display = 'none'; }
          verifyBanner.style.display = 'none';
          if (loginViewEl) loginViewEl.style.display = 'none';
          if (chatMessagesEl) chatMessagesEl.style.display = 'flex';
          if (inputAreaWrapperEl) inputAreaWrapperEl.style.display = 'block';
          if (chatMessagesEl) chatMessagesEl.innerHTML = '';
          initializeChatInterface();
        } else {
          if (loginErrorEl) {
            loginErrorEl.textContent = "Tu email sigue sin estar verificado. Revisa el buzón o reenvía el correo.";
            loginErrorEl.style.display = 'block';
          }
        }
      } else if (id === 'btn-verify-resend') {
        await sendVerificationIfNeeded(auth.currentUser);
        if (loginErrorEl) {
          loginErrorEl.textContent = "Hemos reenviado el email de verificación.";
          loginErrorEl.style.display = 'block';
        }
      } else if (id === 'btn-verify-logout') {
        await auth.signOut();
      } else if (id === 'btn-reset-password') {
        const email = emailInputEl?.value || auth.currentUser?.email;
        if (!email) throw new Error("Introduce tu email en el formulario");
        await auth.sendPasswordResetEmail(email);
        if (loginErrorEl) {
          loginErrorEl.textContent = "Te hemos enviado un enlace para restablecer tu contraseña.";
          loginErrorEl.style.display = 'block';
        }
      }
    } catch (err) {
      if (loginErrorEl) {
        loginErrorEl.textContent = "Error: " + (err?.message || "Operación no completada");
        loginErrorEl.style.display = 'block';
      }
    }
  });

  // ========================================================================
  // ### 5) AUTH STATE: gate por emailVerified ###
  // ========================================================================

  auth.onAuthStateChanged(async (user) => {
    if (user) {
      currentUser = user;
      console.log("Usuario autenticado:", user.email, "verificado:", user.emailVerified);

      if (!user.emailVerified) {
        if (loginViewEl) loginViewEl.style.display = 'block';
        if (verifyBanner) verifyBanner.style.display = 'block';
        if (chatMessagesEl) chatMessagesEl.style.display = 'none';
        if (inputAreaWrapperEl) inputAreaWrapperEl.style.display = 'none';
        return;
      }

      if (verifyBanner) verifyBanner.style.display = 'none';
      if (loginErrorEl) loginErrorEl.style.display = 'none';
      if (loginViewEl) loginViewEl.style.display = 'none';
      if (chatMessagesEl) chatMessagesEl.style.display = 'flex';
      if (inputAreaWrapperEl) inputAreaWrapperEl.style.display = 'block';

      if (chatMessagesEl) chatMessagesEl.innerHTML = '';
      initializeChatInterface();

    } else {
      currentUser = null;
      console.log("Ningún usuario autenticado.");
      if (verifyBanner) verifyBanner.style.display = 'none';
      if (loginViewEl) loginViewEl.style.display = 'block';
      if (chatMessagesEl) chatMessagesEl.style.display = 'none';
      if (inputAreaWrapperEl) inputAreaWrapperEl.style.display = 'none';
    }
  });

  // ========================================================================
  // ### 6) LOGIN / REGISTRO / LOGOUT ###
  // ========================================================================

  if (loginButtonEl) {
    loginButtonEl.addEventListener('click', async () => {
      const email = emailInputEl.value;
      const password = passwordInputEl.value;
      if (!email || !password) {
        loginErrorEl.textContent = "Por favor, introduce email y contraseña.";
        loginErrorEl.style.display = 'block';
        return;
      }
      try {
        const cred = await auth.signInWithEmailAndPassword(email, password);
        if (!cred.user.emailVerified) {
          if (verifyBanner) verifyBanner.style.display = 'block';
          loginErrorEl.textContent = "Debes verificar tu correo antes de usar el chat.";
          loginErrorEl.style.display = 'block';
        }
      } catch (error) {
        console.error("Error de login:", error);
        const msg = String(error?.message || "");
        loginErrorEl.textContent = "Error: " + msg;
        loginErrorEl.style.display = 'block';
        if (msg.includes('user-not-found') && registerButtonEl) {
          registerButtonEl.focus();
        } else if (msg.includes('wrong-password')) {
          if (verifyBanner) verifyBanner.style.display = 'block';
        }
      }
    });
  }

  if (registerButtonEl) {
    registerButtonEl.addEventListener('click', async () => {
      const email = emailInputEl.value;
      const password = passwordInputEl.value;
      if (!email || !password) {
        loginErrorEl.textContent = "Por favor, introduce email y contraseña.";
        loginErrorEl.style.display = 'block';
        return;
      }
      try {
        const cred = await auth.createUserWithEmailAndPassword(email, password);
        await sendVerificationIfNeeded(cred.user);
        loginErrorEl.textContent = "Cuenta creada. Te hemos enviado un email para verificarla.";
        loginErrorEl.style.display = 'block';
        if (verifyBanner) verifyBanner.style.display = 'block';
      } catch (error) {
        console.error("Error de registro:", error);
        loginErrorEl.textContent = "Error: " + (error?.message || "No se pudo registrar");
        loginErrorEl.style.display = 'block';
      }
    });
  }

  // // logout opcional
  // const logoutButton = document.getElementById('logout-button');
  // if (logoutButton) { logoutButton.addEventListener('click', () => auth.signOut()); }

  // ========================================================================
  // ### 7) WIDGET: abrir/cerrar ###
  // ========================================================================

  if (chatBubbleEl) {
    chatBubbleEl.addEventListener('click', () => {
      chatWidgetContainerEl.classList.toggle('is-open');
    });
  }
  if (chatCloseButtonEl) {
    chatCloseButtonEl.addEventListener('click', () => {
      chatWidgetContainerEl.classList.remove('is-open');
    });
  }

  // ========================================================================
  // ### 8) CHAT + FETCH (con token verificado) ###
  // ========================================================================

  let currentChatMode = null;
  let currentChatThreadId = null;

  function initializeChatInterface() {
    console.log("Inicializando interfaz de chat para el usuario:", currentUser.email);
    addAssistantMessageInternal(`¡Hola ${currentUser.email}! Somos tus auditores legales especializados.<br>Elige el modo en el que quieres interactuar:`);

    const modeSelectionContainer = document.createElement('div');
    modeSelectionContainer.className = 'mode-button-container';
    modeSelectionContainer.innerHTML = `
      <button class="mode-button-chat" data-mode="auditor" title="Modo Auditor">Modo Auditor</button>
      <button class="mode-button-chat" data-mode="advisor" title="Modo Asesor">Modo Asesor</button>
    `;
    if (chatMessagesEl) chatMessagesEl.appendChild(modeSelectionContainer);

    modeSelectionContainer.querySelectorAll('.mode-button-chat').forEach(button => {
      button.addEventListener('click', handleModeSelectionClick);
    });

    if (sendButtonEl) sendButtonEl.disabled = true;
    if (attachFileButtonEl) attachFileButtonEl.disabled = true;
    if (userInputEl) userInputEl.placeholder = "Selecciona un modo para comenzar...";
  }

  function handleModeSelectionClick(event) {
    currentChatMode = event.target.dataset.mode;
    const modeButtonContainer = event.target.parentElement;
    console.log(`Chat mode selected: ${currentChatMode}`);
    if (modeButtonContainer) { modeButtonContainer.remove(); }
    if (sendButtonEl) sendButtonEl.disabled = false;
    if (attachFileButtonEl) attachFileButtonEl.disabled = false;
    if (userInputEl) { userInputEl.value = ''; userInputEl.focus(); adjustUserInputHeight(); }
    currentChatThreadId = null;

    if (currentChatMode === 'auditor') {
      addAssistantMessageInternal("Has seleccionado el modo <strong>AUDITOR</strong>.<br>Comienza por contarme: nombre de la empresa, sector, tamaño y sedes.");
      if (userInputEl) userInputEl.placeholder = "Nombre, sector, tamaño, sedes...";
    } else if (currentChatMode === 'advisor') {
      addAssistantMessageInternal("Has seleccionado el modo <strong>ASESOR</strong>.<br>¿En qué puedo ayudarte hoy?");
      if (userInputEl) userInputEl.placeholder = "Escribe tu consulta de asesoría...";
    }
  }

  async function handleSendMessageToServer() {
    const messageText = userInputEl.value.trim();
    if (!messageText || !currentChatMode) return;

    if (!currentUser) {
      addSystemMessageToChat("Error de autenticación. Por favor, recarga la página.");
      return;
    }

    let token;
    try {
      token = await getVerifiedIdTokenOrThrow();
    } catch (e) {
      removeTypingIndicatorFromChat();
      addSystemMessageToChat(e.message || "Necesitas verificar tu email para continuar.");
      if (verifyBanner) verifyBanner.style.display = 'block';
      return;
    }

    addUserMessageToChat(messageText);
    userInputEl.value = '';
    adjustUserInputHeight();
    showTypingIndicatorToChat();

    const endpointUrl = (currentChatMode === 'auditor')
      ? currentEndpoints.auditor
      : currentEndpoints.advisor;

    try {
      const response = await fetch(endpointUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ message: messageText, thread_id: currentChatThreadId })
      });
      removeTypingIndicatorFromChat();
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ error: "Error de red o respuesta no válida.", details: `Status ${response.status}` }));
        addSystemMessageToChat(`Error del servidor: ${errorData.error || response.statusText}.`);
        return;
      }
      const dataFromBackend = await response.json();
      if (dataFromBackend.thread_id) { currentChatThreadId = dataFromBackend.thread_id; }
      if (dataFromBackend.response) {
        const cleanedResponseText = dataFromBackend.response.replace(/【.*?†source】/g, '').trim();
        addAssistantMessageWithCitations(cleanedResponseText, dataFromBackend.citations || []);
      } else if (dataFromBackend.error) {
        addSystemMessageToChat(`Error del asistente: ${dataFromBackend.error}`);
      }
    } catch (error) {
      removeTypingIndicatorFromChat();
      addSystemMessageToChat("No se pudo conectar con el servidor.");
      console.error("Error en fetch:", error);
    }
  }

  // ========================================================================
  // ### 9) AUXILIARES UI ###
  // ========================================================================

  function addAssistantMessageWithCitations(responseText, citationsList) { /* ...código sin cambios... */ const messageWrapper = document.createElement('div'); messageWrapper.classList.add('message', 'assistant-message'); const mainTextDiv = document.createElement('div'); mainTextDiv.classList.add('main-assistant-text'); mainTextDiv.innerHTML = marked.parse(responseText || "El asistente no proporcionó una respuesta textual."); messageWrapper.appendChild(mainTextDiv); if (citationsList && citationsList.length > 0) { const citationsContainerDiv = document.createElement('div'); citationsContainerDiv.classList.add('citations-container'); citationsList.forEach(citation => { const citationDiv = document.createElement('div'); citationDiv.classList.add('citation-item'); let citationHTML = `<span class="citation-marker">${escapeHtml(citation.marker || '[?]')}</span>`; citationHTML += `<span class="citation-quote">${escapeHtml(citation.quote_from_file || 'Contenido no disponible.')}</span>`; if (citation.file_id) { citationHTML += `<span class="citation-file-id">ID Archivo: ${escapeHtml(citation.file_id)}</span>`; } citationDiv.innerHTML = citationHTML; citationsContainerDiv.appendChild(citationDiv); }); messageWrapper.appendChild(citationsContainerDiv); } if(chatMessagesEl) { chatMessagesEl.appendChild(messageWrapper); chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight; } }
  function adjustUserInputHeight() { if (!userInputEl) return; userInputEl.style.height = 'auto'; let scrollHeight = userInputEl.scrollHeight; const maxHeight = 120; if (scrollHeight > maxHeight) { userInputEl.style.height = maxHeight + 'px'; userInputEl.style.overflowY = 'auto'; } else { userInputEl.style.height = scrollHeight + 'px'; userInputEl.style.overflowY = 'hidden'; } }
  if (userInputEl) { userInputEl.addEventListener('input', adjustUserInputHeight); adjustUserInputHeight(); }
  if (attachFileButtonEl) { attachFileButtonEl.addEventListener('click', () => addSystemMessageToChat("La funcionalidad de adjuntar archivos se gestiona automáticamente por el asistente."));}
  function addMessageToChatDOM(htmlContent, cssClass) { const el = document.createElement('div'); el.classList.add('message', cssClass); el.innerHTML = htmlContent; if(chatMessagesEl) { chatMessagesEl.appendChild(el); chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight; } }
  function addUserMessageToChat(text) { const escapedText = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); addMessageToChatDOM(escapedText, 'user-message'); }
  function addSystemMessageToChat(text) { const escapedText = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); addMessageToChatDOM(escapedText, 'system-message'); }
  function addAssistantMessageInternal(htmlContent) { const el = document.createElement('div'); el.classList.add('message', 'assistant-message'); el.innerHTML = `<div class="main-assistant-text">${htmlContent}</div>`; if(chatMessagesEl) { chatMessagesEl.appendChild(el); chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight; } }
  function escapeHtml(unsafe) { if (!unsafe) return ''; return unsafe.toString().replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;"); }
  let typingIndicatorDiv = null;
  function showTypingIndicatorToChat() { if (typingIndicatorDiv) return; typingIndicatorDiv = document.createElement('div'); typingIndicatorDiv.classList.add('message', 'assistant-message', 'typing-indicator'); typingIndicatorDiv.textContent = "Generando una respuesta..."; if(chatMessagesEl) { chatMessagesEl.appendChild(typingIndicatorDiv); chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight; } }
  function removeTypingIndicatorFromChat() { if (typingIndicatorDiv) { typingIndicatorDiv.remove(); typingIndicatorDiv = null; } }

  if (sendButtonEl) { sendButtonEl.addEventListener('click', handleSendMessageToServer); }
  if (userInputEl) {
    userInputEl.addEventListener('keypress', function(event) {
      if (event.key === 'Enter' && !event.shiftKey && sendButtonEl && !sendButtonEl.disabled) {
        event.preventDefault();
        handleSendMessageToServer();
      }
    });
  }

  // No llamamos a initializeChatInterface() aquí; lo hace onAuthStateChanged.
});
