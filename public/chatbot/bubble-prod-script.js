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

  function getOrchestratorBaseUrl() {
    const ref = currentEndpoints?.auditor || currentEndpoints?.advisor;
    if (!ref) return "";
    if (ref.includes("/chat_auditor")) return ref.split("/chat_auditor")[0];
    if (ref.includes("/chat_assistant")) return ref.split("/chat_assistant")[0];
    return ref.replace(/\/$/, "");
  }

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
  let currentConversationMessages = [];
  let recentConversationsCache = [];
  const conversationThreadCache = new Map();
  let historySectionState = null;
  let isRestoringHistoryPlayback = false;

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
      currentConversationMessages = [];
      recentConversationsCache = [];
      conversationThreadCache.clear();
      historySectionState = null;
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
      currentConversationMessages = [];
      recentConversationsCache = [];
      conversationThreadCache.clear();
      historySectionState = null;
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

    renderConversationHistorySection(selectionContainer);

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

  // ===================== 8B) HISTORIAL DE CONVERSACIONES =====================
  function renderConversationHistorySection(parentEl) {
    if (!parentEl) return;
    historySectionState = null;

    const section = document.createElement('section');
    section.className = 'history-section';

    const header = document.createElement('header');
    header.className = 'history-header';

    const title = document.createElement('h2');
    title.className = 'history-title';
    title.textContent = 'Tus ultimas conversaciones';

    const subtitle = document.createElement('p');
    subtitle.className = 'history-subtitle';
    subtitle.textContent = 'Pulsa sobre una para reanudarla.';

    header.appendChild(title);
    header.appendChild(subtitle);
    section.appendChild(header);

    const listEl = document.createElement('ul');
    listEl.className = 'history-list';
    section.appendChild(listEl);

    const statusEl = document.createElement('p');
    statusEl.className = 'history-status';
    statusEl.textContent = 'Cargando conversaciones...';
    section.appendChild(statusEl);

    parentEl.appendChild(section);

    historySectionState = { section, listEl, statusEl };

    fetchRecentConversations(5)
      .then((conversations) => {
        recentConversationsCache = conversations;
        updateHistoryList(conversations);
      })
      .catch((error) => {
        console.error('No se pudo cargar el historial:', error);
        setHistoryStatusMessage('No se pudo cargar el historial. Intentalo mas tarde.', true);
      });
  }

  function setHistoryStatusMessage(message, isError = false) {
    if (!historySectionState?.statusEl) return;
    const { statusEl } = historySectionState;
    if (!message) {
      statusEl.textContent = '';
      statusEl.style.display = 'none';
      statusEl.classList.remove('is-error');
      return;
    }
    statusEl.textContent = message;
    statusEl.style.display = 'block';
    statusEl.classList.toggle('is-error', !!isError);
  }

  function updateHistoryList(conversations) {
    if (!historySectionState?.listEl) return;
    const { listEl } = historySectionState;
    listEl.innerHTML = '';

    if (!conversations || !conversations.length) {
      setHistoryStatusMessage('Todavia no tienes conversaciones previas.', false);
      return;
    }

    setHistoryStatusMessage('', false);

    conversations.forEach((conversation) => {
      const item = document.createElement('li');
      item.className = 'history-item';

      const link = document.createElement('a');
      link.href = '#';
      link.className = 'history-link';
      link.dataset.threadId = conversation.thread_id;
      if (conversation.endpoint_source) {
        link.dataset.endpointSource = conversation.endpoint_source;
      }
      link.textContent = conversation.summary || 'Conversacion previa';
      link.addEventListener('click', handleHistoryItemClick);

      item.appendChild(link);

      const metaText = formatHistoryTimestamp(conversation.last_timestamp);
      if (metaText) {
        const meta = document.createElement('span');
        meta.className = 'history-meta';
        meta.textContent = metaText;
        item.appendChild(meta);
      }

      listEl.appendChild(item);

      const existing = conversationThreadCache.get(conversation.thread_id) || {};
      const merged = { ...existing, ...conversation };
      if (existing.messages && !conversation.messages) {
        merged.messages = existing.messages;
      }
      conversationThreadCache.set(conversation.thread_id, merged);
    });
  }

  function formatHistoryTimestamp(isoString) {
    if (!isoString) return '';
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) return '';
    try {
      return date.toLocaleString('es-ES', { dateStyle: 'short', timeStyle: 'short' });
    } catch (_e) {
      return date.toISOString().replace('T', ' ').split('.')[0];
    }
  }

  async function fetchRecentConversations(limit = 5) {
    await environmentReadyPromise;
    const baseUrl = getOrchestratorBaseUrl();
    if (!baseUrl) throw new Error('No se pudo determinar la URL del orquestador.');
    const token = await getVerifiedIdTokenOrThrow();
    const url = `${baseUrl}/chat_history/recents?limit=${encodeURIComponent(limit)}`;

    const resp = await fetch(url, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    });

    if (!resp.ok) {
      let message = `Error ${resp.status}`;
      try {
        const payload = await resp.json();
        if (payload?.error) message = payload.error;
      } catch (_err) {
        // noop
      }
      throw new Error(message);
    }

    const data = await resp.json();
    return Array.isArray(data?.conversations) ? data.conversations : [];
  }

  async function fetchConversationThread(threadId) {
    if (!threadId) throw new Error('threadId requerido');

    const cached = conversationThreadCache.get(threadId);
    if (cached?.messages && cached.messages.length) {
      return cached;
    }

    await environmentReadyPromise;
    const baseUrl = getOrchestratorBaseUrl();
    if (!baseUrl) throw new Error('No se pudo determinar la URL del orquestador.');
    const token = await getVerifiedIdTokenOrThrow();
    const url = `${baseUrl}/chat_history/thread/${encodeURIComponent(threadId)}`;

    const resp = await fetch(url, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    });

    if (!resp.ok) {
      let message = `Error ${resp.status}`;
      try {
        const payload = await resp.json();
        if (payload?.error) message = payload.error;
      } catch (_err) {
        // noop
      }
      throw new Error(message);
    }

    const data = await resp.json();
    if (!data || typeof data !== 'object') {
      throw new Error('Respuesta invalida al recuperar la conversacion.');
    }
    if (!Array.isArray(data.messages)) {
      data.messages = [];
    }

    const existing = conversationThreadCache.get(threadId) || {};
    conversationThreadCache.set(threadId, { ...existing, ...data });

    return data;
  }

  function determineModeFromEndpoint(endpointSource) {
    if (!endpointSource) return currentChatMode || 'advisor';
    if (endpointSource.includes('auditor')) return 'auditor';
    if (endpointSource.includes('assistant')) return 'advisor';
    return currentChatMode || 'advisor';
  }

  function resumeConversationFromHistory(conversationData) {
    if (!conversationData) return;

    currentChatThreadId = conversationData.thread_id || null;
    currentChatMode = determineModeFromEndpoint(conversationData.endpoint_source);
    currentConversationMessages = Array.isArray(conversationData.messages)
      ? conversationData.messages.slice()
      : [];

    document.querySelector('.selection-container')?.remove();

    chatMessagesEl.style.display = 'flex';
    sendButtonEl.disabled = false;
    attachFileButtonEl.disabled = false;
    userInputEl.value = '';
    adjustUserInputHeight();

    const messagesToShow = currentConversationMessages.slice(-5);
    chatMessagesEl.innerHTML = '';

    if (!messagesToShow.length) {
      addSystemMessageToChat('No encontramos mensajes previos en esta conversacion.');
    } else {
      isRestoringHistoryPlayback = true;
      try {
        messagesToShow.forEach((msg) => {
          if (msg.role === 'assistant') {
            addAssistantMessageWithCitations(msg.text, []);
          } else if (msg.role === 'user') {
            addUserMessageToChat(msg.text);
          } else if (msg.role === 'system') {
            addSystemMessageToChat(msg.text);
          }
        });
      } finally {
        isRestoringHistoryPlayback = false;
      }
    }

    scrollChatToBottom({ behavior: 'auto' });

    if (currentChatMode === 'auditor') {
      userInputEl.placeholder = 'Continua con la conversacion de auditor...';
    } else {
      userInputEl.placeholder = 'Escribe tu mensaje para continuar...';
    }

    userInputEl.focus();
    syncConversationCache(currentChatThreadId, conversationData.endpoint_source);
    setHistoryStatusMessage('', false);
  }

  function syncConversationCache(threadId, endpointSource) {
    if (!threadId) return;
    const existing = conversationThreadCache.get(threadId) || {};
    const payload = {
      ...existing,
      thread_id: threadId,
      endpoint_source: endpointSource || existing.endpoint_source || getEndpointSourceForMode(currentChatMode),
      messages: currentConversationMessages.slice(),
      last_timestamp: new Date().toISOString(),
    };
    conversationThreadCache.set(threadId, payload);
  }

  function getEndpointSourceForMode(mode) {
    if (mode === 'auditor') return '/chat_auditor';
    if (mode === 'advisor') return '/chat_assistant';
    return undefined;
  }

  async function handleHistoryItemClick(event) {
    event.preventDefault();
    const link = event.currentTarget;
    if (!link || link.dataset.loading === '1') return;

    const threadId = link.dataset.threadId;
    if (!threadId) return;

    link.dataset.loading = '1';
    link.classList.add('is-loading');
    setHistoryStatusMessage('Cargando conversacion...', false);

    try {
      const conversation = await fetchConversationThread(threadId);
      resumeConversationFromHistory(conversation);
    } catch (error) {
      console.error('No se pudo abrir la conversacion seleccionada:', error);
      setHistoryStatusMessage('No se pudo abrir la conversacion seleccionada.', true);
    } finally {
      link.dataset.loading = '';
      link.classList.remove('is-loading');
    }
  }

  function handleModeSelectionClick(e) {
    currentChatMode = e.target.dataset.mode;
    document.querySelector('.selection-container')?.remove();

    // Mostrar timeline y habilitar input (Fila 3)
    chatMessagesEl.style.display = 'flex';
    chatMessagesEl.innerHTML = '';
    sendButtonEl.disabled = false;
    attachFileButtonEl.disabled = false;
    userInputEl.value = ''; userInputEl.focus(); adjustUserInputHeight();
    currentChatThreadId = null;
    currentConversationMessages = [];
    setHistoryStatusMessage('', false);

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

    currentConversationMessages.push({
      role: 'user',
      text: messageText,
      timestamp: new Date().toISOString(),
    });

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
        currentConversationMessages.push({
          role: 'assistant',
          text: cleaned,
          timestamp: new Date().toISOString(),
        });
      } else if (data.error) {
        addSystemMessageToChat(`Error del asistente: ${data.error}`);
      }
      syncConversationCache(currentChatThreadId, getEndpointSourceForMode(currentChatMode));
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
    scrollChatToBottom();
  }
  function addMessageToChatDOM(html, cls){
    const el = document.createElement('div'); el.classList.add('message', cls); el.innerHTML = html;
    chatMessagesEl.appendChild(el); scrollChatToBottom();
  }
  function addUserMessageToChat(t){ const s=t.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); addMessageToChatDOM(s,'user-message'); }
  function addSystemMessageToChat(t){ const s=t.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); addMessageToChatDOM(s,'system-message'); }
  function addAssistantMessageInternal(html){ const el=document.createElement('div'); el.classList.add('message','assistant-message'); el.innerHTML=`<div class="main-assistant-text">${html}</div>`; chatMessagesEl.appendChild(el); scrollChatToBottom(); }
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
    scrollChatToBottom({ behavior: 'smooth' });
  }
  function removeTypingIndicatorFromChat(){ if(typingIndicatorDiv){ typingIndicatorDiv.remove(); typingIndicatorDiv=null; } }

  function scrollChatToBottom(options){
    if (!chatMessagesEl) return;
    const requestedBehavior = (options && options.behavior) ? options.behavior : 'smooth';
    const effectiveBehavior = isRestoringHistoryPlayback ? 'auto' : requestedBehavior;

    const performScroll = () => {
      if (typeof chatMessagesEl.scrollTo === 'function') {
        try {
          chatMessagesEl.scrollTo({ top: chatMessagesEl.scrollHeight, behavior: effectiveBehavior });
          return;
        } catch (_e) {
          // fallback below
        }
      }
      chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
    };

    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(performScroll);
    } else {
      performScroll();
    }
  }

  attachFileButtonEl?.addEventListener('click', ()=> addSystemMessageToChat("La funcionalidad de adjuntar archivos se gestiona automáticamente por el asistente."));
  sendButtonEl?.addEventListener('click', handleSendMessageToServer);
  userInputEl?.addEventListener('keypress', (e)=> {
    if (e.key === 'Enter' && !e.shiftKey && !sendButtonEl.disabled) { e.preventDefault(); handleSendMessageToServer(); }
  });
});
