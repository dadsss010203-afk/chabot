(function() {
    const API_URL = 'http://localhost:5000';
    let idiomaActual = 'es';

    const UI_TEXTOS = {
        es: {
            placeholder: "Escribe tu consulta aquí...",
            analizando: "Analizando tu consulta...",
        },
        en: {
            placeholder: "Type your question here...",
            analizando: "Analyzing your request...",
        },
        fr: {
            placeholder: "Écrivez votre question ici...",
            analizando: "Analyse en cours...",
        },
        pt: {
            placeholder: "Digite sua consulta aqui...",
            analizando: "Analisando sua consulta...",
        },
        zh: {
            placeholder: "在此输入您的问题...",
            analizando: "正在分析您的请求...",
        },
    };

    // Inyectar estilos
    const style = document.createElement('style');
    style.textContent = `
        #correos-chat-bubble {
            position: fixed; bottom: 24px; right: 24px;
            width: 64px; height: 64px;
            background: #003DA5; border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer; box-shadow: 0 4px 24px rgba(0, 61, 165, 0.4);
            z-index: 9999; border: 3px solid #FFD100;
            transition: all 0.3s; font-size: 28px;
        }
        #correos-chat-bubble:hover { transform: scale(1.12); }
        
        #correos-chat-window {
            position: fixed; bottom: 100px; right: 24px;
            width: 370px; height: 520px;
            background: white; border-radius: 20px;
            box-shadow: 0 4px 20px rgba(0, 61, 165, 0.15);
            display: none; flex-direction: column;
            z-index: 9998; border: 1.5px solid #DDE2E8;
            font-family: 'Sora', sans-serif;
            overflow: hidden;
        }
        #correos-chat-window.open { display: flex; animation: slideIn 0.3s; }
        
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        #correos-header {
            background: #003DA5; padding: 0 14px;
            height: 52px; display: flex; align-items: center;
            justify-content: space-between; color: white;
            border-bottom: 3px solid #FFD100;
        }
        
        .correos-logo { width: 34px; height: 34px;
            background: #FFD100; border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            font-size: 18px; flex-shrink: 0; }
        
        #correos-header h3 { margin: 0; font-size: 0.88rem; font-weight: 700;
            flex: 1; text-align: center; }
        
        .correos-header-buttons { display: flex; gap: 6px; }
        .correos-header-btn { background: rgba(255,255,255,0.12); border: none;
            color: white; width: 26px; height: 26px; border-radius: 6px;
            cursor: pointer; font-size: 13px; font-weight: 700;
            transition: all 0.2s; }
        .correos-header-btn:hover { background: rgba(255,209,0,0.3); }
        
        #correos-status-bar {
            background: rgba(0, 38, 128, 0.95); padding: 3px 14px;
            display: flex; align-items: center; gap: 6px;
            font-size: 0.68rem; color: rgba(255,255,255,0.7);
            flex-shrink: 0; border-bottom: 1px solid rgba(255,255,255,0.08);
        }
        
        .correos-dot { width: 6px; height: 6px; border-radius: 50%;
            background: rgba(255,255,255,0.4); transition: background 0.3s; }
        .correos-dot.activo { background: #4ade80; box-shadow: 0 0 6px #4ade80; }
        
        #correos-lang-selector {
            display: flex; align-items: center; gap: 4px;
            padding: 4px 10px; background: #F4F6F8;
            border-top: 1px solid #DDE2E8; flex-shrink: 0;
            overflow-x: auto; scrollbar-width: none;
        }
        #correos-lang-selector::-webkit-scrollbar { display: none; }
        
        .correos-lang-btn {
            background: none; border: 1.5px solid transparent;
            border-radius: 6px; padding: 3px 7px; font-size: 0.72rem;
            cursor: pointer; font-family: 'Sora', sans-serif;
            color: #3A3A3A; white-space: nowrap;
            transition: all 0.2s; flex-shrink: 0;
        }
        .correos-lang-btn:hover { border-color: #003DA5; color: #003DA5;
            background: #E8EFFE; }
        .correos-lang-btn.activo { background: #003DA5; color: #FFD100;
            border-color: #003DA5; font-weight: 700; }
        
        #correos-messages {
            flex: 1; overflow-y: auto; padding: 16px;
            background: #F4F6F8; display: flex; flex-direction: column; gap: 14px;
        }
        #correos-messages::-webkit-scrollbar { width: 4px; }
        #correos-messages::-webkit-scrollbar-thumb { background: #DDE2E8; border-radius: 2px; }
        
        .correos-message { display: flex; gap: 8px; max-width: 100%; animation: fadeUp 0.35s ease; }
        .correos-message.user { align-self: flex-end; flex-direction: row-reverse; }
        .correos-message.bot { align-self: flex-start; }
        
        @keyframes fadeUp {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .correos-avatar { width: 28px; height: 28px; border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            font-size: 13px; flex-shrink: 0; }
        .correos-message.user .correos-avatar { background: #FFD100; color: #003DA5;
            font-weight: 700; }
        .correos-message.bot .correos-avatar { background: #003DA5; color: #FFD100; }
        
        .correos-bubble { padding: 9px 13px; border-radius: 14px;
            font-size: 0.85rem; line-height: 1.5; word-wrap: break-word;
            max-width: 78%; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08); }
        
        .correos-message.user .correos-bubble { background: #003DA5; color: white;
            border-bottom-right-radius: 4px; }
        .correos-message.bot .correos-bubble { background: white; color: #3A3A3A;
            border: 1px solid #DDE2E8; border-bottom-left-radius: 4px; }
        
        .correos-typing .correos-bubble {
            display: flex; align-items: center; gap: 6px;
            padding: 12px 14px; background: white; border: 1px solid #DDE2E8;
        }
        .correos-typing-dot { width: 6px; height: 6px; border-radius: 50%;
            animation: bounce 1.2s infinite; opacity: 0.8; }
        .correos-typing-dot:nth-child(1) { background: #003DA5; }
        .correos-typing-dot:nth-child(2) { background: #F0C300; animation-delay: 0.2s; }
        .correos-typing-dot:nth-child(3) { background: #003DA5; animation-delay: 0.4s; }
        @keyframes bounce {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-5px); }
        }
        
        #correos-form-area {
            background: white; border-top: 2px solid #FFD100;
            padding: 12px 14px; flex-shrink: 0;
        }
        
        #correos-form { display: flex; gap: 8px; align-items: center; }
        #correos-input { flex: 1; background: #F4F6F8; border: 1.5px solid #DDE2E8;
            color: #3A3A3A; padding: 9px 14px; border-radius: 22px;
            font-size: 0.85rem; font-family: 'Sora', sans-serif;
            outline: none; transition: border-color 0.25s, box-shadow 0.25s; }
        #correos-input:focus { border-color: #003DA5; box-shadow: 0 0 0 3px rgba(0, 61, 165, 0.12); }
        #correos-input::placeholder { color: #A0A0A0; }
        
        #correos-send { width: 40px; height: 40px; background: #FFD100;
            border: none; border-radius: 50%; color: #003DA5;
            font-size: 16px; cursor: pointer; display: flex;
            align-items: center; justify-content: center;
            transition: all 0.25s; flex-shrink: 0; font-weight: 700;
            box-shadow: 0 2px 8px rgba(255, 209, 0, 0.4); }
        #correos-send:hover { background: #F0C300; transform: scale(1.08); }
        #correos-send:active { transform: scale(0.95); }
        
        #correos-stop { width: 40px; height: 40px; background: #E74C3C;
            border: none; border-radius: 50%; color: white;
            font-size: 16px; cursor: pointer; display: none;
            align-items: center; justify-content: center;
            transition: all 0.25s; flex-shrink: 0; font-weight: 700;
            box-shadow: 0 2px 8px rgba(231, 76, 60, 0.4);
            animation: aparecer 0.2s ease; }
        #correos-stop.visible { display: flex; }
        #correos-stop:hover { background: #c0392b; transform: scale(1.08); }
        #correos-stop:active { transform: scale(0.95); }
        
        @keyframes aparecer {
            from { opacity: 0; transform: scale(0.7); }
            to { opacity: 1; transform: scale(1); }
        }
    `;
    document.head.appendChild(style);

    // Crear HTML
    const container = document.createElement('div');
    container.innerHTML = `
        <div id="correos-chat-bubble">📬</div>
        <div id="correos-chat-window">
            <header id="correos-header">
                <div class="correos-logo">📬</div>
                <h3>Correos de Bolivia</h3>
                <div class="correos-header-buttons">
                    <button class="correos-header-btn" id="correos-clear" title="Borrar conversación" onclick="window.limpiarChatWidget()">🗑️</button>
                    <button class="correos-header-btn" id="correos-close" title="Cerrar">✕</button>
                </div>
            </header>
            
            <div id="correos-status-bar">
                <div class="correos-dot activo" id="correos-dot"></div>
                <span id="correos-status-text">Conectando...</span>
            </div>
            
            <div id="correos-lang-selector">
                <span style="font-size: 0.65rem; color: #999; margin-right: 2px;">🌐</span>
                <button class="correos-lang-btn activo" data-lang="es" onclick="window.cambiarIdiomaWidget('es')">🇧🇴 ES</button>
                <button class="correos-lang-btn" data-lang="en" onclick="window.cambiarIdiomaWidget('en')">🇺🇸 EN</button>
                <button class="correos-lang-btn" data-lang="fr" onclick="window.cambiarIdiomaWidget('fr')">🇫🇷 FR</button>
                <button class="correos-lang-btn" data-lang="pt" onclick="window.cambiarIdiomaWidget('pt')">🇧🇷 PT</button>
                <button class="correos-lang-btn" data-lang="zh" onclick="window.cambiarIdiomaWidget('zh')">🇨🇳 中文</button>
            </div>
            
            <div id="correos-messages"></div>
            
            <div id="correos-form-area">
                <form id="correos-form">
                    <input type="text" id="correos-input" placeholder="Escribe tu consulta aquí..." />
                    <button type="button" id="correos-stop" onclick="window.detenerRespuestaWidget()" title="Detener respuesta">⏹</button>
                    <button type="submit" id="correos-send">➤</button>
                </form>
            </div>
        </div>
    `;
    document.body.appendChild(container);

    const bubble = document.getElementById('correos-chat-bubble');
    const win = document.getElementById('correos-chat-window');
    const messagesDiv = document.getElementById('correos-messages');
    const form = document.getElementById('correos-form');
    const input = document.getElementById('correos-input');
    const closeBtn = document.getElementById('correos-close');
    const statusDot = document.getElementById('correos-dot');
    const statusText = document.getElementById('correos-status-text');
    const sendBtn = document.getElementById('correos-send');
    const stopBtn = document.getElementById('correos-stop');
    let esperando = false;
    let abortController = null;

    // Cargar bienvenida
    async function cargarBienvenida() {
        await new Promise(r => setTimeout(r, 400));
        mostrarTyping();
        await new Promise(r => setTimeout(r, 900));
        removeTyping();
        try {
            const res = await fetch(`${API_URL}/api/welcome?lang=${idiomaActual}`);
            const data = await res.json();
            addMessage(data.response || 'Bienvenido', 'bot');
        } catch {
            addMessage('¡Hola! Bienvenido al asistente de Correos de Bolivia.', 'bot');
        }
    }

    // Cargar estado
    async function checkStatus() {
        try {
            const res = await fetch(`${API_URL}/api/status`);
            const data = await res.json();
            statusDot.className = 'correos-dot activo';
            statusText.textContent = `En línea · ${data.chunks} docs · ${data.modelo}`;
        } catch {
            statusDot.className = 'correos-dot';
            statusText.textContent = 'Sin conexión';
        }
    }

    // Cambiar idioma
    window.cambiarIdiomaWidget = function(lang) {
        idiomaActual = lang;
        document.querySelectorAll('.correos-lang-btn').forEach(btn => {
            btn.classList.toggle('activo', btn.dataset.lang === lang);
        });
        const ui = UI_TEXTOS[lang] || UI_TEXTOS.es;
        document.getElementById('correos-input').placeholder = ui.placeholder;
        messagesDiv.innerHTML = '';
        cargarBienvenida();
    };

    // Limpiar chat
    window.limpiarChatWidget = function() {
        try { fetch(`${API_URL}/api/reset`, { method: 'POST' }); } catch {}
        messagesDiv.innerHTML = '';
        cargarBienvenida();
    };

    // Mostrar/ocultar botón stop
    function mostrarStop(visible) {
        if (visible) {
            stopBtn.classList.add('visible');
            sendBtn.style.display = 'none';
        } else {
            stopBtn.classList.remove('visible');
            sendBtn.style.display = 'flex';
        }
    }

    // Detener respuesta
    window.detenerRespuestaWidget = function() {
        if (abortController) {
            abortController.abort();
            abortController = null;
        }
    };

    function addMessage(text, tipo) {
        const msg = document.createElement('div');
        msg.className = `correos-message ${tipo}`;

        const avatar = document.createElement('div');
        avatar.className = 'correos-avatar';
        avatar.textContent = tipo === 'user' ? '👤' : '🤖';

        const bubble = document.createElement('div');
        bubble.className = 'correos-bubble';
        bubble.textContent = text;

        msg.appendChild(avatar);
        msg.appendChild(bubble);
        messagesDiv.appendChild(msg);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    function mostrarTyping() {
        const msg = document.createElement('div');
        msg.className = 'correos-message bot correos-typing';
        msg.id = 'correos-typing';

        const avatar = document.createElement('div');
        avatar.className = 'correos-avatar';
        avatar.textContent = '🤖';

        const bubble = document.createElement('div');
        bubble.className = 'correos-bubble';
        const ui = UI_TEXTOS[idiomaActual] || UI_TEXTOS.es;
        bubble.innerHTML = `<span style="color: #666; margin-right: 4px;">${ui.analizando}</span><div class="correos-typing-dot"></div><div class="correos-typing-dot"></div><div class="correos-typing-dot"></div>`;

        msg.appendChild(avatar);
        msg.appendChild(bubble);
        messagesDiv.appendChild(msg);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    function removeTyping() {
        const t = document.getElementById('correos-typing');
        if (t) t.remove();
    }

    bubble.addEventListener('click', () => {
        win.classList.toggle('open');
        if (win.classList.contains('open')) {
            checkStatus();
            input.focus();
        }
    });

    closeBtn.addEventListener('click', () => win.classList.remove('open'));

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const text = input.value.trim();
        if (!text || esperando) return;

        addMessage(text, 'user');
        input.value = '';
        esperando = true;
        input.disabled = true;
        mostrarStop(true);

        mostrarTyping();
        abortController = new AbortController();

        try {
            const res = await fetch(`${API_URL}/api/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text, lang: idiomaActual }),
                signal: abortController.signal
            });
            const data = await res.json();
            removeTyping();
            addMessage(data.response || data.error || 'Error', 'bot');
        } catch (err) {
            removeTyping();
            if (err.name === 'AbortError') {
                addMessage('⏹ Respuesta detenida.', 'bot');
            } else {
                addMessage('Error de conexión con el servidor.', 'bot');
            }
        }

        abortController = null;
        esperando = false;
        mostrarStop(false);
        input.disabled = false;
        input.focus();
    });

    // Init
    cargarBienvenida();
    setTimeout(checkStatus, 500);
})();
