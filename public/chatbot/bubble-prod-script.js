document.addEventListener('DOMContentLoaded', function() {
    
    // ========================================================================
    // ### INICIO MODIFICACIÓN 1: CONFIGURACIÓN DE FIREBASE Y NUEVOS SELECTORES ###
    // ========================================================================

    // --- COPIA AQUÍ TU CONFIGURACIÓN DE FIREBASE ---
    // La obtienes desde la consola de tu proyecto en Firebase
    const firebaseConfig = {
        apiKey: "AIzaSyAAlSxno1oBOtyhh7ntS2mv8rkAnWeAzmM",
        authDomain: "recava-auditor-dev.firebaseapp.com",
        projectId: "recava-auditor-dev",
        storageBucket: "recava-auditor-dev.firebasestorage.app",
        messagingSenderId: "370417116045",
        appId: "1:370417116045:web:41c77969d5d880382d93c4",
        measurementId: "G-2J8TTR4SD2"
    };

    // --- Inicializar Firebase ---
    firebase.initializeApp(firebaseConfig);
    const auth = firebase.auth();
    // const db = firebase.firestore(); // Lo dejaremos preparado para cuando guardemos chats

    // --- Nuevos Selectores para el Login ---
    const loginViewEl = document.getElementById('login-view');
    const emailInputEl = document.getElementById('email-input');
    const passwordInputEl = document.getElementById('password-input');
    const loginButtonEl = document.getElementById('login-button');
    const registerButtonEl = document.getElementById('register-button');
    const loginErrorEl = document.getElementById('login-error');
    
    // --- Selectores para la funcionalidad de la burbuja ---
    const chatBubbleEl = document.getElementById('chat-bubble');
    const chatWidgetContainerEl = document.getElementById('chat-widget-container');
    const chatCloseButtonEl = document.getElementById('chat-close-button');

    // --- Selectores originales del chat ---
    const chatMessagesEl = document.getElementById('chat-messages');
    const inputAreaWrapperEl = document.getElementById('input-area-wrapper');
    const userInputEl = document.getElementById('user-input');
    const sendButtonEl = document.getElementById('send-button');
    const attachFileButtonEl = document.getElementById('attach-file-button');
    
    // --- Variable para guardar el estado del usuario ---
    let currentUser = null;

    // ========================================================================
    // ### INICIO MODIFICACIÓN 2: CONTROLADOR PRINCIPAL DE AUTENTICACIÓN ###
    // ========================================================================

    auth.onAuthStateChanged(user => {
        if (user) {
            // Usuario está logueado
            currentUser = user;
            console.log("Usuario autenticado:", user.email);

            // Ocultar vista de login y mostrar la del chat
            if (loginViewEl) loginViewEl.style.display = 'none';
            if (chatMessagesEl) chatMessagesEl.style.display = 'flex';
            if (inputAreaWrapperEl) inputAreaWrapperEl.style.display = 'block';

            // Limpiamos el chat e inicializamos la interfaz
            if (chatMessagesEl) chatMessagesEl.innerHTML = '';
            initializeChatInterface();

        } else {
            // Usuario no está logueado
            currentUser = null;
            console.log("Ningún usuario autenticado.");

            // Mostrar vista de login y ocultar la del chat
            if (loginViewEl) loginViewEl.style.display = 'block';
            if (chatMessagesEl) chatMessagesEl.style.display = 'none';
            if (inputAreaWrapperEl) inputAreaWrapperEl.style.display = 'none';
        }
    });

    // ========================================================================
    // ### INICIO MODIFICACIÓN 3: LÓGICA DE LOGIN, REGISTRO Y LOGOUT ###
    // ========================================================================

    if (loginButtonEl) {
        loginButtonEl.addEventListener('click', () => {
            const email = emailInputEl.value;
            const password = passwordInputEl.value;
            if (!email || !password) {
                loginErrorEl.textContent = "Por favor, introduce email y contraseña.";
                loginErrorEl.style.display = 'block';
                return;
            }
            auth.signInWithEmailAndPassword(email, password)
                .catch(error => {
                    console.error("Error de login:", error);
                    loginErrorEl.textContent = "Error: " + error.message;
                    loginErrorEl.style.display = 'block';
                });
        });
    }

    if (registerButtonEl) {
        registerButtonEl.addEventListener('click', () => {
            const email = emailInputEl.value;
            const password = passwordInputEl.value;
            if (!email || !password) {
                loginErrorEl.textContent = "Por favor, introduce email y contraseña.";
                loginErrorEl.style.display = 'block';
                return;
            }
            auth.createUserWithEmailAndPassword(email, password)
                .catch(error => {
                    console.error("Error de registro:", error);
                    loginErrorEl.textContent = "Error: " + error.message;
                    loginErrorEl.style.display = 'block';
                });
        });
    }

    // Lógica para un futuro botón de logout
    // const logoutButton = document.getElementById('logout-button');
    // if(logoutButton) {
    //     logoutButton.addEventListener('click', () => {
    //         auth.signOut();
    //     });
    // }


    // --- Lógica para abrir y cerrar el widget de chat (sin cambios) ---
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
    // ### INICIO MODIFICACIÓN 4: CÓDIGO DEL CHAT ADAPTADO ###
    // ========================================================================

    const endpoints = {
        prod: {
            auditor: 'https://orchestrator-520199812528.europe-west1.run.app/chat_auditor',
            advisor: 'https://orchestrator-520199812528.europe-west1.run.app/chat_assistant'
        }
    };
    let currentEndpoints = endpoints.prod;
    
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

        if(sendButtonEl) sendButtonEl.disabled = true;
        if(attachFileButtonEl) attachFileButtonEl.disabled = true;
        if(userInputEl) userInputEl.placeholder = "Selecciona un modo para comenzar...";
    }

    function handleModeSelectionClick(event) {
        currentChatMode = event.target.dataset.mode;
        const modeButtonContainer = event.target.parentElement;
        console.log(`Chat mode selected: ${currentChatMode}`);
        if (modeButtonContainer) { modeButtonContainer.remove(); }
        if(sendButtonEl) sendButtonEl.disabled = false;
        if(attachFileButtonEl) attachFileButtonEl.disabled = false;
        if(userInputEl) { userInputEl.value = ''; userInputEl.focus(); adjustUserInputHeight(); }
        currentChatThreadId = null; // Reiniciamos el hilo para cada nueva conversación
        console.log("Thread ID ha sido reiniciado.");
        if (currentChatMode === 'auditor') {
            addAssistantMessageInternal("Has seleccionado el modo <strong>AUDITOR</strong>.<br>Comienza por contarme: nombre de la empresa, sector, tamaño y sedes.");
            if(userInputEl) userInputEl.placeholder = "Nombre, sector, tamaño, sedes...";
        } else if (currentChatMode === 'advisor') {
            addAssistantMessageInternal("Has seleccionado el modo <strong>ASESOR</strong>.<br>¿En qué puedo ayudarte hoy?");
            if(userInputEl) userInputEl.placeholder = "Escribe tu consulta de asesoría...";
        }
    }

    async function handleSendMessageToServer() {
        const messageText = userInputEl.value.trim();
        if (!messageText || !currentChatMode) return;

        // ### MODIFICACIÓN 5: AÑADIR TOKEN DE AUTENTICACIÓN ###
        if (!currentUser) {
            addSystemMessageToChat("Error de autenticación. Por favor, recarga la página.");
            return;
        }
        const token = await currentUser.getIdToken();
        // #######################################################

        addUserMessageToChat(messageText);
        userInputEl.value = '';
        adjustUserInputHeight();
        showTypingIndicatorToChat();
        
        const endpointUrl = currentChatMode === 'auditor' ? currentEndpoints.auditor : currentEndpoints.advisor;
        
        try {
            const response = await fetch(endpointUrl, {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}` // <-- ¡Aquí se envía el token!
                },
                body: JSON.stringify({ message: messageText, thread_id: currentChatThreadId })
            });
            removeTypingIndicatorFromChat();
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ error: "Error de red o respuesta no válida.", details: `Status ${response.status}`}));
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

    // --- El resto de funciones auxiliares permanecen igual ---
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
    if (userInputEl) { userInputEl.addEventListener('keypress', function(event) { if (event.key === 'Enter' && !event.shiftKey && sendButtonEl && !sendButtonEl.disabled) { event.preventDefault(); handleSendMessageToServer(); } }); }
    
    // Ya no se llama a initializeChatInterface() al final.
    // El controlador onAuthStateChanged se encarga de todo.
});