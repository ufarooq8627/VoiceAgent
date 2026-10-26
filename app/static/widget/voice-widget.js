/**
 * Divine Voice Agent - Commercial Embeddable Web Widget
 * Ultra-secure, Zero-dependency, Shadow-DOM isolated
 */
(function () {
    "use strict";

    class VoiceAgentWidget {
        constructor() {
            this.scriptTag = document.currentScript || document.querySelector('script[data-client-key]');
            if (!this.scriptTag) {
                console.warn("[VoiceWidget] Script tag with data-client-key not found.");
                return;
            }

            this.clientKey = this.scriptTag.getAttribute("data-client-key");
            this.apiBase = this.scriptTag.getAttribute("data-api-base") || this.getScriptBaseUrl();
            this.position = this.scriptTag.getAttribute("data-position") || "bottom-right";
            this.theme = this.scriptTag.getAttribute("data-theme") || "dark";

            this.sessionToken = null;
            this.callId = null;
            this.businessName = "Voice Receptionist";
            this.isOpen = false;
            this.isCallActive = false;
            this.isListening = false;
            this.isSpeaking = false;
            this.recognition = null;

            this.init();
        }

        getScriptBaseUrl() {
            try {
                const src = this.scriptTag.src;
                if (src) {
                    const url = new URL(src);
                    return url.origin;
                }
            } catch (e) {}
            return window.location.origin;
        }

        init() {
            // Create root container
            this.container = document.createElement("div");
            this.container.id = "divine-voice-widget-root";
            this.container.style.position = "fixed";
            this.container.style.zIndex = "999999";
            if (this.position === "bottom-left") {
                this.container.style.bottom = "24px";
                this.container.style.left = "24px";
            } else {
                this.container.style.bottom = "24px";
                this.container.style.right = "24px";
            }

            // Create Shadow DOM
            this.shadowRoot = this.container.attachShadow({ mode: "open" });
            this.render();
            document.body.appendChild(this.container);

            this.bindEvents();
            this.setupSpeechRecognition();
        }

        render() {
            this.shadowRoot.innerHTML = `
            <style>
                :host {
                    all: initial;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                }
                * {
                    box-sizing: border-box;
                    margin: 0;
                    padding: 0;
                }
                .fab-btn {
                    width: 60px;
                    height: 60px;
                    border-radius: 50%;
                    background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
                    box-shadow: 0 10px 25px -5px rgba(99, 102, 241, 0.5), 0 8px 10px -6px rgba(99, 102, 241, 0.4);
                    border: none;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: #ffffff;
                    position: relative;
                    transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.2s ease;
                }
                .fab-btn:hover {
                    transform: scale(1.08);
                    box-shadow: 0 15px 30px -5px rgba(99, 102, 241, 0.6);
                }
                .pulse-ring {
                    position: absolute;
                    width: 100%;
                    height: 100%;
                    border-radius: 50%;
                    border: 2px solid #818cf8;
                    animation: pulse 2.2s infinite;
                    pointer-events: none;
                }
                @keyframes pulse {
                    0% { transform: scale(1); opacity: 0.8; }
                    100% { transform: scale(1.4); opacity: 0; }
                }
                .widget-card {
                    display: none;
                    width: 360px;
                    max-width: calc(100vw - 48px);
                    background: rgba(17, 24, 39, 0.96);
                    backdrop-filter: blur(16px);
                    -webkit-backdrop-filter: blur(16px);
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 20px;
                    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.6);
                    margin-bottom: 16px;
                    flex-direction: column;
                    overflow: hidden;
                    animation: slideUp 0.25s cubic-bezier(0.16, 1, 0.3, 1);
                }
                .widget-card.active {
                    display: flex;
                }
                @keyframes slideUp {
                    from { opacity: 0; transform: translateY(16px); }
                    to { opacity: 1; transform: translateY(0); }
                }
                .widget-header {
                    padding: 16px 20px;
                    background: rgba(31, 41, 55, 0.6);
                    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                }
                .header-title-box {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }
                .status-dot {
                    width: 10px;
                    height: 10px;
                    border-radius: 50%;
                    background: #10b981;
                    box-shadow: 0 0 8px #10b981;
                }
                .business-title {
                    font-size: 15px;
                    font-weight: 600;
                    color: #f3f4f6;
                }
                .close-btn {
                    background: transparent;
                    border: none;
                    color: #9ca3af;
                    font-size: 20px;
                    cursor: pointer;
                    line-height: 1;
                    padding: 4px;
                }
                .close-btn:hover {
                    color: #ffffff;
                }
                .widget-body {
                    padding: 20px;
                    display: flex;
                    flex-direction: column;
                    gap: 16px;
                    min-height: 240px;
                    max-height: 380px;
                    overflow-y: auto;
                }
                .wave-box {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 5px;
                    height: 48px;
                    background: rgba(0, 0, 0, 0.25);
                    border-radius: 12px;
                    padding: 0 16px;
                }
                .wave-bar {
                    width: 4px;
                    height: 12px;
                    background: #6366f1;
                    border-radius: 4px;
                    transition: height 0.15s ease;
                }
                .wave-box.animated .wave-bar {
                    animation: wave 0.8s ease-in-out infinite alternate;
                }
                .wave-box.animated .wave-bar:nth-child(2) { animation-delay: 0.15s; }
                .wave-box.animated .wave-bar:nth-child(3) { animation-delay: 0.3s; }
                .wave-box.animated .wave-bar:nth-child(4) { animation-delay: 0.45s; }
                .wave-box.animated .wave-bar:nth-child(5) { animation-delay: 0.2s; }
                @keyframes wave {
                    0% { height: 8px; background: #6366f1; }
                    100% { height: 32px; background: #a855f7; }
                }
                .chat-history {
                    display: flex;
                    flex-direction: column;
                    gap: 10px;
                    flex-grow: 1;
                }
                .bubble {
                    padding: 10px 14px;
                    border-radius: 14px;
                    font-size: 13.5px;
                    line-height: 1.45;
                    max-width: 88%;
                    word-wrap: break-word;
                }
                .bubble.agent {
                    align-self: flex-start;
                    background: rgba(55, 65, 81, 0.7);
                    color: #f9fafb;
                    border-bottom-left-radius: 4px;
                }
                .bubble.caller {
                    align-self: flex-end;
                    background: #4f46e5;
                    color: #ffffff;
                    border-bottom-right-radius: 4px;
                }
                .status-text {
                    font-size: 12px;
                    color: #9ca3af;
                    text-align: center;
                }
                .widget-footer {
                    padding: 14px 20px;
                    background: rgba(31, 41, 55, 0.5);
                    border-top: 1px solid rgba(255, 255, 255, 0.08);
                    display: flex;
                    gap: 10px;
                    align-items: center;
                }
                .input-msg {
                    flex-grow: 1;
                    background: rgba(17, 24, 39, 0.8);
                    border: 1px solid rgba(255, 255, 255, 0.15);
                    border-radius: 20px;
                    padding: 8px 14px;
                    color: #f3f4f6;
                    font-size: 13px;
                    outline: none;
                }
                .input-msg:focus {
                    border-color: #6366f1;
                }
                .action-btn {
                    background: #4f46e5;
                    border: none;
                    border-radius: 50%;
                    width: 36px;
                    height: 36px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: #ffffff;
                    cursor: pointer;
                    transition: background 0.2s ease;
                }
                .action-btn:hover {
                    background: #4338ca;
                }
                .end-btn {
                    background: #dc2626;
                }
                .end-btn:hover {
                    background: #b91c1c;
                }
                .mic-btn.active {
                    background: #ef4444;
                    animation: pulse 1.5s infinite;
                }
            </style>

            <div class="widget-card" id="widget-card">
                <div class="widget-header">
                    <div class="header-title-box">
                        <div class="status-dot" id="status-dot"></div>
                        <span class="business-title" id="biz-name">AI Receptionist</span>
                    </div>
                    <button class="close-btn" id="close-card-btn" title="Close">×</button>
                </div>
                <div class="widget-body" id="widget-body">
                    <div class="wave-box" id="wave-box">
                        <div class="wave-bar"></div>
                        <div class="wave-bar"></div>
                        <div class="wave-bar"></div>
                        <div class="wave-bar"></div>
                        <div class="wave-bar"></div>
                    </div>
                    <div class="status-text" id="status-indicator">Click mic or type to speak</div>
                    <div class="chat-history" id="chat-history"></div>
                </div>
                <div class="widget-footer">
                    <input type="text" class="input-msg" id="text-input" placeholder="Type a message..." />
                    <button class="action-btn" id="send-btn" title="Send message">➤</button>
                    <button class="action-btn" id="mic-btn" title="Speak via mic">🎤</button>
                    <button class="action-btn end-btn" id="end-btn" title="End call" style="display:none;">✕</button>
                </div>
            </div>

            <button class="fab-btn" id="fab-trigger" title="Talk to Receptionist">
                <div class="pulse-ring"></div>
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
                    <line x1="12" y1="19" x2="12" y2="23"></line>
                    <line x1="8" y1="23" x2="16" y2="23"></line>
                </svg>
            </button>
            `;
        }

        bindEvents() {
            const root = this.shadowRoot;
            this.fab = root.getElementById("fab-trigger");
            this.card = root.getElementById("widget-card");
            this.closeBtn = root.getElementById("close-card-btn");
            this.textInput = root.getElementById("text-input");
            this.sendBtn = root.getElementById("send-btn");
            this.micBtn = root.getElementById("mic-btn");
            this.endBtn = root.getElementById("end-btn");
            this.waveBox = root.getElementById("wave-box");
            this.statusIndicator = root.getElementById("status-indicator");
            this.chatHistory = root.getElementById("chat-history");
            this.bizNameElem = root.getElementById("biz-name");

            this.fab.addEventListener("click", () => this.toggleWidget());
            this.closeBtn.addEventListener("click", () => this.toggleWidget(false));
            this.sendBtn.addEventListener("click", () => this.handleTextSubmit());
            this.textInput.addEventListener("keydown", (e) => {
                if (e.key === "Enter") this.handleTextSubmit();
            });
            this.micBtn.addEventListener("click", () => this.toggleMic());
            this.endBtn.addEventListener("click", () => this.endCall());
        }

        toggleWidget(open) {
            this.isOpen = open !== undefined ? open : !this.isOpen;
            if (this.isOpen) {
                this.card.classList.add("active");
                if (!this.isCallActive) {
                    this.startCallSession();
                }
            } else {
                this.card.classList.remove("active");
            }
        }

        async startCallSession() {
            this.statusIndicator.textContent = "Connecting to agent...";
            try {
                // 1. Handshake Session
                const sessRes = await fetch(`${this.apiBase}/api/v1/widget/session`, {
                    method: "POST",
                    headers: {
                        "X-Client-Key": this.clientKey,
                        "Content-Type": "application/json"
                    }
                });
                if (!sessRes.ok) {
                    throw new Error(`Handshake failed (${sessRes.status})`);
                }
                const sessData = await sessRes.json();
                this.sessionToken = sessData.session_token;
                this.businessName = sessData.business_name || this.businessName;
                this.bizNameElem.textContent = this.businessName;

                // 2. Start Call
                const callRes = await fetch(`${this.apiBase}/api/v1/widget/call/start`, {
                    method: "POST",
                    headers: {
                        "Authorization": `Bearer ${this.sessionToken}`,
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({ caller_name: "Website Visitor" })
                });
                if (!callRes.ok) throw new Error("Call start failed");
                const callData = await callRes.json();
                this.callId = callData.call_id;
                this.isCallActive = true;
                this.endBtn.style.display = "flex";

                this.addBubble("agent", callData.greeting);
                this.speak(callData.greeting);
                this.statusIndicator.textContent = "Connected. Speak or type below.";
            } catch (err) {
                console.error("[VoiceWidget] Error starting call:", err);
                this.statusIndicator.textContent = "Connection error. Please try again.";
            }
        }

        async handleTextSubmit() {
            const text = this.textInput.value.trim();
            if (!text || !this.isCallActive) return;
            this.textInput.value = "";
            this.addBubble("caller", text);
            await this.sendTurn(text);
        }

        async sendTurn(message) {
            this.statusIndicator.textContent = "Thinking...";
            this.waveBox.classList.add("animated");
            try {
                const res = await fetch(`${this.apiBase}/api/v1/widget/call/${this.callId}/turn`, {
                    method: "POST",
                    headers: {
                        "Authorization": `Bearer ${this.sessionToken}`,
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({ caller_message: message })
                });
                if (!res.ok) throw new Error("Turn failed");
                const data = await res.json();
                this.addBubble("agent", data.reply_text);
                this.speak(data.speech_text || data.reply_text);
                this.statusIndicator.textContent = "Listening for your response...";
            } catch (err) {
                console.error("[VoiceWidget] Turn error:", err);
                this.statusIndicator.textContent = "Error sending message.";
            } finally {
                this.waveBox.classList.remove("animated");
            }
        }

        addBubble(role, content) {
            const b = document.createElement("div");
            b.className = `bubble ${role}`;
            b.textContent = content;
            this.chatHistory.appendChild(b);
            const body = this.shadowRoot.getElementById("widget-body");
            body.scrollTop = body.scrollHeight;
        }

        speak(text) {
            if (!window.speechSynthesis) return;
            window.speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.rate = 1.05;
            utterance.pitch = 1.0;
            this.waveBox.classList.add("animated");
            this.isSpeaking = true;
            utterance.onend = () => {
                this.isSpeaking = false;
                this.waveBox.classList.remove("animated");
            };
            window.speechSynthesis.speak(utterance);
        }

        setupSpeechRecognition() {
            const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRec) {
                this.micBtn.title = "Voice recognition not supported in this browser";
                return;
            }
            this.recognition = new SpeechRec();
            this.recognition.continuous = false;
            this.recognition.interimResults = false;
            this.recognition.lang = "en-US";

            this.recognition.onstart = () => {
                this.isListening = true;
                this.micBtn.classList.add("active");
                this.statusIndicator.textContent = "Listening to you...";
            };
            this.recognition.onresult = (event) => {
                const transcript = event.results[0][0].transcript;
                if (transcript) {
                    this.addBubble("caller", transcript);
                    this.sendTurn(transcript);
                }
            };
            this.recognition.onerror = () => {
                this.isListening = false;
                this.micBtn.classList.remove("active");
                this.statusIndicator.textContent = "Ready";
            };
            this.recognition.onend = () => {
                this.isListening = false;
                this.micBtn.classList.remove("active");
            };
        }

        toggleMic() {
            if (!this.recognition) return;
            if (this.isListening) {
                this.recognition.stop();
            } else {
                try {
                    this.recognition.start();
                } catch (e) {}
            }
        }

        async endCall() {
            if (!this.callId || !this.sessionToken) return;
            try {
                await fetch(`${this.apiBase}/api/v1/widget/call/${this.callId}/end`, {
                    method: "POST",
                    headers: { "Authorization": `Bearer ${this.sessionToken}` }
                });
            } catch (e) {}
            this.isCallActive = false;
            this.endBtn.style.display = "none";
            this.statusIndicator.textContent = "Call ended.";
            this.addBubble("agent", "Thank you for contacting us! Have a wonderful day.");
            if (window.speechSynthesis) window.speechSynthesis.cancel();
            if (this.recognition && this.isListening) this.recognition.stop();
        }
    }

    // Auto initialize once DOM is ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => new VoiceAgentWidget());
    } else {
        new VoiceAgentWidget();
    }
})();
