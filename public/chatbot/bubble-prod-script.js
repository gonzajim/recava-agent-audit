document.addEventListener('DOMContentLoaded', function () {
  // ===================== 1) FIREBASE =====================
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

  if (location.hostname === 'localhost') {
    firebase.auth().useEmulator('http://localhost:9099/');
  }

  // Endpoints por entorno
  const endpoints = {
    prod: {
      auditor: 'https://orchestrator-520199812528.europe-west1.run.app/chat_auditor',
      advisor: 'https://orchestrator-520199812528.europe-west1.run.app/chat_assistant'
    },
    dev: {
      auditor: 'https://orchestrator-dev-370417116045.europe-west1.run.app/chat_auditor',
      advisor: 'https://orchestrator-dev-370417116045.europe-west1.run.app/chat_assistant'
    },
    local: {
      auditor: 'http://localhost:8080/chat_auditor',
      advisor: 'http://localhost:8080/chat_assistant'
    }
  };
  let currentEndpoints = endpoints.prod;

  async function configureEnvironment() {
    if (location.hostname === 'localhost') {
      currentEndpoints = endpoints.local; return;
    }
    try {
      const r = await fetch('/__firebase/init.json');
      const cfg = await r.json();
      currentEndpoints = (cfg?.projectId === 'recava-auditor') ? endpoints.prod : endpoints.dev;
    } catch (_e) {
      currentEndpoints = endpoints.dev;
    }
  }
  const environmentReadyPromise = configureEnvironment();

  // ===================== 2) SELECTORES =====================
  const loginViewEl = document.getElementById('login-view') || document.getElementById('login-container');
  const chatWrapperEl = document.querySelector('.chat-wrapper');
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
  let currentChatMode = null;
  let currentChatThreadId = null;

  // ===================== 3) HELPERS VERIFICACIÓN =====================
  async function sendVerificationIfNeeded(user) {
    try { if (user && !user.emailVerified) await user.sendEmailVerification(); }
    catch(e){ console.error('No se pudo enviar verificación:', e); }
  }
  async function reloadAndCheckVerification() {
    if (!auth.currentUser) return false;
    await auth.currentUser.reload(); return !!auth.currentUser.emailVerified;
  }
  async function getVerifiedIdTokenOrThrow() {
    const u = auth.currentUser;
    if (!u) throw new Error('No autenticado');
    if (!u.emailVerified) throw new Error('Email no verificado');
    return await u.getIdToken(true);
  }

  // ===================== 4) BANNER VERIFICACIÓN =====================
  const verifyBanner = document.createElement('div');
  verifyBanner.classList.add('verify-banner');
  verifyBanner.style.display = 'none';
  verifyBanner.innerHTML = `
    <strong class="verify-banner__title">Revisa tu correo</strong>
    <span class="verify-banner__subtitle">Te hemos enviado un email para verificar tu cuenta.</span>
    <div class="verify-banner__actions">
      <button id="btn-verify-retry" class="verify-banner__button primary">Ya lo verifiqué</button>
      <button id="btn-verify-resend" class="verify-banner__button secondary">Reenviar verificación</button>
      <button id="btn-verify-logout" class="verify-banner__button secondary">Cerrar sesión</button>
      <button id="btn-reset-password" class="verify-banner__button ghost">Olvidé mi contraseña</button>
    </div>`;
  if (loginViewEl) loginViewEl.appendChild(verifyBanner);

  verifyBanner.addEventListener('click', async (e) => {
    const id = e.target?.id;
    try {
      if (id === 'btn-verify-retry') {
        const ok = await reloadAndCheckVerification();
        if (ok) {
          loginErrorEl.style.display = 'none';
          verifyBanner.style.display = 'none';
          loginViewEl.style.display = 'none';
          document.querySelector('.chat-wrapper').style.display = 'flex';
          chatMessagesEl.style.display = 'none';
          inputAreaWrapperEl.style.display = 'block';
          await initializeSelectionLayout();
        } else {
          loginErrorEl.textContent = "Tu email sigue sin estar verificado. Revisa el buzón o reenvía el correo.";
          loginErrorEl.style.display = 'block';
        }
      } else if (id === 'btn-verify-resend') {
        await sendVerificationIfNeeded(auth.currentUser);
        loginErrorEl.textContent = "Hemos reenviado el email de verificación.";
        loginErrorEl.style.display = 'block';
      } else if (id === 'btn-verify-logout') {
        await auth.signOut();
      } else if (id === 'btn-reset-password') {
        const email = emailInputEl?.value || auth.currentUser?.email;
        if (!email) throw new Error("Introduce tu email en el formulario");
        await auth.sendPasswordResetEmail(email);
        loginErrorEl.textContent = "Te hemos enviado un enlace para restablecer tu contraseña.";
        loginErrorEl.style.display = 'block';
      }
    } catch (err) {
      loginErrorEl.textContent = "Error: " + (err?.message || "Operación no completada");
      loginErrorEl.style.display = 'block';
    }
  });

  // ===================== 5) AUTH STATE =====================
  auth.onAuthStateChanged(async (user) => {
    if (user) {
      currentUser = user;
      if (!user.emailVerified) {
        loginViewEl.style.display = 'block';
        verifyBanner.style.display = 'block';
        document.querySelector('.chat-wrapper').style.display = 'none';
        chatMessagesEl.style.display = 'none';
        inputAreaWrapperEl.style.display = 'none';
        return;
      }
      verifyBanner.style.display = 'none';
      loginErrorEl.style.display = 'none';
      loginViewEl.style.display = 'none';
      document.querySelector('.chat-wrapper').style.display = 'flex';
      chatMessagesEl.style.display = 'none';
      inputAreaWrapperEl.style.display = 'block';
      await initializeSelectionLayout();
    } else {
      currentUser = null;
      verifyBanner.style.display = 'none';
      loginViewEl.style.display = 'block';
      document.querySelector('.chat-wrapper').style.display = 'none';
      chatMessagesEl.style.display = 'none';
      inputAreaWrapperEl.style.display = 'none';
    }
  });

  // ===================== 6) LOGIN / REGISTRO =====================
  loginButtonEl?.addEventListener('click', async () => {
    const email = emailInputEl.value, password = passwordInputEl.value;
    if (!email || !password) {
      loginErrorEl.textContent = "Por favor, introduce email y contraseña.";
      loginErrorEl.style.display = 'block'; return;
    }
    try {
      const cred = await auth.signInWithEmailAndPassword(email, password);
      if (!cred.user.emailVerified) {
        verifyBanner.style.display = 'block';
        loginErrorEl.textContent = "Debes verificar tu correo antes de usar el chat.";
        loginErrorEl.style.display = 'block';
      }
    } catch (err) {
      const msg = String(err?.message || "");
      loginErrorEl.textContent = "Error: " + msg;
      loginErrorEl.style.display = 'block';
    }
  });

  registerButtonEl?.addEventListener('click', async () => {
    const email = emailInputEl.value, password = passwordInputEl.value;
    if (!email || !password) {
      loginErrorEl.textContent = "Por favor, introduce email y contraseña.";
      loginErrorEl.style.display = 'block'; return;
    }
    try {
      const cred = await auth.createUserWithEmailAndPassword(email, password);
      await sendVerificationIfNeeded(cred.user);
      loginErrorEl.textContent = "Cuenta creada. Te hemos enviado un email para verificarla.";
      loginErrorEl.style.display = 'block';
      verifyBanner.style.display = 'block';
    } catch (err) {
      loginErrorEl.textContent = "Error: " + (err?.message || "No se pudo registrar");
      loginErrorEl.style.display = 'block';
    }
  });

  // ===================== 7) WIDGET OPEN/CLOSE =====================
  chatBubbleEl?.addEventListener('click', () => chatWidgetContainerEl.classList.toggle('is-open'));
  chatCloseButtonEl?.addEventListener('click', () => chatWidgetContainerEl.classList.remove('is-open'));

  // ===================== 8) SELECCIÓN (3 FILAS) =====================
  async function initializeSelectionLayout() {
    await environmentReadyPromise;

    // Fila 3 deshabilitada hasta elegir modo
    sendButtonEl.disabled = true;
    attachFileButtonEl.disabled = true;
    userInputEl.placeholder = "Selecciona un modo para comenzar...";

    // Ocultamos timeline en la selección
    chatMessagesEl.style.display = 'none';

    // evita duplicado
    document.querySelector('.selection-container')?.remove();

    const selectionContainer = document.createElement('section');
    selectionContainer.className = 'selection-container';

    // Fila 1: bienvenida
    const welcome = document.createElement('div');
    welcome.className = 'welcome-banner';
    welcome.innerHTML =
      `¡Hola ${currentUser.email}! Somos tus auditores legales especializados en Diligencia Debida en materia de Sostenibilidad.<br/>
       <strong>Elige el modo en el que quieres interactuar:</strong>`;
    selectionContainer.appendChild(welcome);

    // Fila 2: tarjetas
    const grid = document.createElement('div');
    grid.className = 'mode-grid';
    grid.innerHTML = `
      <article class="mode-card mode-card--advisor">
        <header class="mode-card__header">Modo Asesor</header>
        <div class="mode-card__body">
          <p class="mode-card__text">
            En el modo Asesor, el asistente se comporta como un experto en sostenibilidad corporativa.
            Puedes consultarle cómo cumplir con la CSRD, preparar indicadores GRI,
            interpretar las NEIS o estructurar la memoria de sostenibilidad.
          </p>
          <p class="mode-card__text">
            Las respuestas se basan en fuentes normativas verificadas y conocimiento especializado,
            por lo que es ideal para consultas técnicas, operativas o formativas sin intervención humana directa.
          </p>
        </div>
        <footer class="mode-card__footer">
          <button class="mode-button-chat" data-mode="advisor" title="Seleccionar modo asesor">
            Seleccionar Modo Asesor
          </button>
        </footer>
      </article>

      <article class="mode-card mode-card--auditor">
        <header class="mode-card__header">Modo Auditor</header>
        <div class="mode-card__body">
          <p class="mode-card__text">
            En el modo Auditor, el asistente adopta el rol de un auditor digital de sostenibilidad.
            Revisa tus respuestas, identifica posibles incumplimientos y puede solicitar
            información adicional sobre tu empresa, sedes, políticas o métricas.
          </p>
          <p class="mode-card__text">
            Este modo está diseñado para recolectar y analizar evidencias, no solo para responder preguntas,
            y te guiará paso a paso durante todo el proceso.
          </p>
          <div class="mode-card__modules">
            <div class="mode-card__modules-title">Módulos del proceso</div>
            <ul class="mode-card__modules-list">
              <li>Análisis de Riesgos</li>
              <li>Políticas y Códigos en DDHH</li>
              <li>Sistema de Gestión de Riesgos</li>
              <li>Transparencia y Publicidad</li>
              <li>Informe de Sostenibilidad</li>
              <li>Reparación de Daños</li>
              <li>Condiciones de Trabajo Dignas</li>
              <li>Seguridad y Salud Laboral</li>
              <li>Trabajo Forzado</li>
              <li>Trabajo Infantil</li>
              <li>Medioambiente y Cambio Climático</li>
            </ul>
          </div>
        </div>
        <footer class="mode-card__footer">
          <button class="mode-button-chat" data-mode="auditor" title="Seleccionar modo auditor">
            Seleccionar Modo Auditor
          </button>
        </footer>
      </article>`;
    selectionContainer.appendChild(grid);

    // Insertar Fila 1+2 justo antes del input (Fila 3)
    if (chatWrapperEl && inputAreaWrapperEl) {
      chatWrapperEl.insertBefore(selectionContainer, inputAreaWrapperEl);
    } else {
      chatWidgetContainerEl.appendChild(selectionContainer);
    }

    // listeners
    selectionContainer.querySelectorAll('[data-mode]').forEach(btn => {
      btn.addEventListener('click', handleModeSelectionClick);
    });
  }

  function handleModeSelectionClick(e) {
    currentChatMode = e.target.dataset.mode;
    document.querySelector('.selection-container')?.remove();

    // Mostrar timeline y habilitar input (Fila 3)
    chatMessagesEl.style.display = 'flex';
    sendButtonEl.disabled = false;
    attachFileButtonEl.disabled = false;
    userInputEl.value = ''; userInputEl.focus(); adjustUserInputHeight();
    currentChatThreadId = null;

    if (currentChatMode === 'auditor') {
      addAssistantMessageInternal("Has seleccionado el modo <strong>AUDITOR</strong>.<br>Comienza por contarme: nombre de la empresa, sector, tamaño y sedes.");
      userInputEl.placeholder = "Nombre, sector, tamaño, sedes...";
    } else {
      addAssistantMessageInternal("Has seleccionado el modo <strong>ASESOR</strong>.<br>¿En qué puedo ayudarte hoy?");
      userInputEl.placeholder = "Escribe tu consulta de asesoría...";
    }
  }

  // ===================== 9) ENVÍO MENSAJES =====================
  async function handleSendMessageToServer() {
    const messageText = userInputEl.value.trim();
    if (!messageText) return;

    if (!currentChatMode) {
      addSystemMessageToChat("Elige primero <strong>Modo Asesor</strong> o <strong>Modo Auditor</strong>.");
      return;
    }
    if (!currentUser) {
      addSystemMessageToChat("Error de autenticación. Por favor, recarga la página.");
      return;
    }

    let token;
    try { token = await getVerifiedIdTokenOrThrow(); }
    catch(e){
      removeTypingIndicatorFromChat();
      addSystemMessageToChat(e.message || "Necesitas verificar tu email para continuar.");
      verifyBanner.style.display = 'block';
      return;
    }

    addUserMessageToChat(messageText);
    userInputEl.value = ''; adjustUserInputHeight();
    showTypingIndicatorToChat();

    const endpointUrl = currentChatMode === 'auditor' ? currentEndpoints.auditor : currentEndpoints.advisor;

    try {
      const resp = await fetch(endpointUrl, {
        method:'POST',
        headers:{ 'Content-Type':'application/json', 'Authorization':`Bearer ${token}` },
        body: JSON.stringify({ message: messageText, thread_id: currentChatThreadId })
      });
      removeTypingIndicatorFromChat();
      if (!resp.ok) {
        const err = await resp.json().catch(()=>({error:"Error de red", details:`Status ${resp.status}`}));
        addSystemMessageToChat(`Error del servidor: ${err.error || resp.statusText}.`);
        return;
      }
      const data = await resp.json();
      if (data.thread_id) currentChatThreadId = data.thread_id;
      if (data.response) {
        const cleaned = data.response.replace(/【.*?†source】/g,'').trim();
        addAssistantMessageWithCitations(cleaned, data.citations || []);
      } else if (data.error) {
        addSystemMessageToChat(`Error del asistente: ${data.error}`);
      }
    } catch (e) {
      removeTypingIndicatorFromChat();
      addSystemMessageToChat("No se pudo conectar con el servidor.");
      console.error("fetch error:", e);
    }
  }

  // ===================== 10) AUXILIARES UI =====================
  function addAssistantMessageWithCitations(responseText, citationsList){
    const wrap = document.createElement('div'); wrap.classList.add('message','assistant-message');
    const main = document.createElement('div'); main.classList.add('main-assistant-text');
    main.innerHTML = (window.marked ? marked.parse(responseText || "El asistente no proporcionó una respuesta textual.") : (responseText || "El asistente no proporcionó una respuesta textual."));
    wrap.appendChild(main);
    if (citationsList && citationsList.length){
      const cont = document.createElement('div'); cont.classList.add('citations-container');
      citationsList.forEach(c=>{
        const item = document.createElement('div'); item.classList.add('citation-item');
        let html = `<span class="citation-marker">${escapeHtml(c.marker || '[?]')}</span>`;
        html += `<span class="citation-quote">${escapeHtml(c.quote_from_file || 'Contenido no disponible.')}</span>`;
        if (c.file_id) html += `<span class="citation-file-id">ID Archivo: ${escapeHtml(c.file_id)}</span>`;
        item.innerHTML = html; cont.appendChild(item);
      });
      wrap.appendChild(cont);
    }
    chatMessagesEl.appendChild(wrap);
    chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
  }
  function addMessageToChatDOM(html, cls){
    const el = document.createElement('div'); el.classList.add('message', cls); el.innerHTML = html;
    chatMessagesEl.appendChild(el); chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
  }
  function addUserMessageToChat(t){ const s=t.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); addMessageToChatDOM(s,'user-message'); }
  function addSystemMessageToChat(t){ const s=t.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); addMessageToChatDOM(s,'system-message'); }
  function addAssistantMessageInternal(html){ const el=document.createElement('div'); el.classList.add('message','assistant-message'); el.innerHTML=`<div class="main-assistant-text">${html}</div>`; chatMessagesEl.appendChild(el); chatMessagesEl.scrollTop=chatMessagesEl.scrollHeight; }
  function escapeHtml(u){ if(!u) return ''; return u.toString().replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#039;"); }
  function adjustUserInputHeight(){
    userInputEl.style.height='auto';
    const max=120, sh=userInputEl.scrollHeight;
    userInputEl.style.height=(sh>max?max:sh)+'px';
    userInputEl.style.overflowY=(sh>max?'auto':'hidden');
  }
  userInputEl?.addEventListener('input', adjustUserInputHeight); adjustUserInputHeight();

  let typingIndicatorDiv=null;
  function showTypingIndicatorToChat(){
    if(typingIndicatorDiv) return;
    typingIndicatorDiv=document.createElement('div');
    typingIndicatorDiv.classList.add('message','assistant-message','typing-indicator');
    typingIndicatorDiv.textContent="Generando una respuesta...";
    chatMessagesEl.appendChild(typingIndicatorDiv);
    chatMessagesEl.scrollTop=chatMessagesEl.scrollHeight;
  }
  function removeTypingIndicatorFromChat(){ if(typingIndicatorDiv){ typingIndicatorDiv.remove(); typingIndicatorDiv=null; } }

  attachFileButtonEl?.addEventListener('click', ()=> addSystemMessageToChat("La funcionalidad de adjuntar archivos se gestiona automáticamente por el asistente."));
  sendButtonEl?.addEventListener('click', handleSendMessageToServer);
  userInputEl?.addEventListener('keypress', (e)=> {
    if (e.key === 'Enter' && !e.shiftKey && !sendButtonEl.disabled) { e.preventDefault(); handleSendMessageToServer(); }
  });
});
