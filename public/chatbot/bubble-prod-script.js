document.addEventListener('DOMContentLoaded', function() {
    // --- Selectores para la funcionalidad de la burbuja ---
    const chatBubbleEl = document.getElementById('chat-bubble');
    const chatWidgetContainerEl = document.getElementById('chat-widget-container');
    const chatCloseButtonEl = document.getElementById('chat-close-button');

    // --- Selectores originales del chat ---
    const chatMessagesEl = document.getElementById('chat-messages');
    const userInputEl = document.getElementById('user-input');
    const sendButtonEl = document.getElementById('send-button');
    const attachFileButtonEl = document.getElementById('attach-file-button');
    
    // --- Lógica para abrir y cerrar el widget de chat ---
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

    // --- GESTIÓN DE LAS URLS DE LOS ENDPOINTS ---
    const endpoints = {
        prod: {
            auditor: 'https://orchestrator-520199812528.europe-west1.run.app/chat_auditor',
            advisor: 'https://orchestrator-520199812528.europe-west1.run.app/chat_assistant'
        },
        dev: { // Mantenemos los de dev por si los necesitas en otro lugar, pero no se usarán
            auditor: 'https://orchestrator-dev-370417116045.europe-west1.run.app/chat_auditor',
            advisor: 'https://orchestrator-dev-370417116045.europe-west1.run.app/chat_assistant',
        }
    };
    
    // ===== MODIFICACIÓN CLAVE =====
    // Forzamos el uso de los endpoints de PRODUCCIÓN directamente.
    // Se elimina la función 'configureEnvironment' y la detección automática.
    let currentEndpoints = endpoints.prod;
    console.log("Chat widget configurado para el entorno de PRODUCCIÓN.");
    // =============================
    
    let currentChatMode = null;
    let currentChatThreadId = null;

    function initializeChatInterface() {
        // La inicialización ahora es directa, sin esperar a la configuración de entorno.
        console.log("Chat initializing...");
        addAssistantMessageInternal("¡Hola! Somos tus auditores legales especializados en sostenibilidad empresarial y diligencia debida. Guiaremos el proceso de auditoría.<br>Elige el modo en el que quieres interactuar:");
        
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

    // [ ... El resto del código de script.js (handleModeSelectionClick, handleSendMessageToServer, etc.) permanece exactamente igual ... ]
    function handleModeSelectionClick(event) {
        currentChatMode = event.target.dataset.mode;
        const modeButtonContainer = event.target.parentElement;
        console.log(`Chat mode selected: ${currentChatMode}`);
        if (modeButtonContainer) { modeButtonContainer.remove(); }
        if(sendButtonEl) sendButtonEl.disabled = false;
        if(attachFileButtonEl) attachFileButtonEl.disabled = false;
        if(userInputEl) { userInputEl.value = ''; userInputEl.focus(); adjustUserInputHeight(); }
        currentChatThreadId = null;
        console.log("Thread ID has been reset for the new mode.");
        if (currentChatMode === 'auditor') {
            addAssistantMessageInternal("Has seleccionado el modo <strong>AUDITOR</strong>.<br>Comienza por contarme: nombre de la empresa, sector, tamaño y sedes de la empresa.");
            if(userInputEl) userInputEl.placeholder = "Nombre, sector, tamaño, sedes...";
        } else if (currentChatMode === 'advisor') {
            addAssistantMessageInternal("Has seleccionado el modo <strong>ASESOR</strong>.<br>¿En qué puedo ayudarte hoy?");
            if(userInputEl) userInputEl.placeholder = "Escribe tu consulta de asesoría...";
        }
    }

    async function handleSendMessageToServer() {
        const messageText = userInputEl.value.trim();
        if (!messageText || !currentChatMode) return;
        addUserMessageToChat(messageText);
        userInputEl.value = '';
        adjustUserInputHeight();
        showTypingIndicatorToChat();
        const endpointUrl = currentChatMode === 'auditor' ? currentEndpoints.auditor : currentEndpoints.advisor;
        try {
            const response = await fetch(endpointUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: messageText, thread_id: currentChatThreadId })
            });
            removeTypingIndicatorFromChat();
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ error: "Error de red o respuesta no válida", details: `Status ${response.status}`}));
                addSystemMessageToChat(`Error API: ${errorData.error || response.statusText}. ${errorData.details || ''}`);
                return;
            }
            const dataFromBackend = await response.json();
            if (dataFromBackend.thread_id) { currentChatThreadId = dataFromBackend.thread_id; }
            if (dataFromBackend.response) {
                const cleanedResponseText = dataFromBackend.response.replace(/【.*?†source】/g, '').trim();
                addAssistantMessageWithCitations(cleanedResponseText, dataFromBackend.citations || []);
            } else if (dataFromBackend.error) {
                addSystemMessageToChat(`Error del asistente: ${dataFromBackend.error} ${dataFromBackend.details || ''}`);
            }
        } catch (error) {
            removeTypingIndicatorFromChat();
            addSystemMessageToChat("Error de conexión con el servidor.");
            console.error("Error en fetch:", error);
        }
    }

    function addAssistantMessageWithCitations(responseText, citationsList) {
        const messageWrapper = document.createElement('div');
        messageWrapper.classList.add('message', 'assistant-message');
        const mainTextDiv = document.createElement('div');
        mainTextDiv.classList.add('main-assistant-text');
        mainTextDiv.innerHTML = marked.parse(responseText || "El asistente no proporcionó una respuesta textual.");
        messageWrapper.appendChild(mainTextDiv);
        if (citationsList && citationsList.length > 0) {
            const citationsContainerDiv = document.createElement('div');
            citationsContainerDiv.classList.add('citations-container');
            citationsList.forEach(citation => {
                const citationDiv = document.createElement('div');
                citationDiv.classList.add('citation-item');
                let citationHTML = `<span class="citation-marker">${escapeHtml(citation.marker || '[?]')}</span>`;
                citationHTML += `<span class="citation-quote">${escapeHtml(citation.quote_from_file || 'Contenido no disponible.')}</span>`;
                if (citation.file_id) { citationHTML += `<span class="citation-file-id">ID Archivo: ${escapeHtml(citation.file_id)}</span>`; }
                citationDiv.innerHTML = citationHTML;
                citationsContainerDiv.appendChild(citationDiv);
            });
            messageWrapper.appendChild(citationsContainerDiv);
        }
        if(chatMessagesEl) { chatMessagesEl.appendChild(messageWrapper); chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight; }
    }
    
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
    
    // Iniciar todo
    initializeChatInterface();
});