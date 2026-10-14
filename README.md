# 🎙️ AI Voice Receptionist & Autonomous Recruitment Agent

An intelligent, multi-tenant AI voice receptionist and hiring workflow agent built with **FastAPI**, **Google Gemini multimodal LLM**, and production-grade **telephony architecture for Twilio & Telnyx**.

Designed for zero-latency, realistic voice interaction with live tool execution, dynamic FAQ lookup, unanswered question logging with staff escalation, and callback consent tracking.

---

## 🌟 Key Features

### 1. 🤖 AI Voice Receptionist Engine
* **Multimodal Speech Processing**: Transcribes voice input with Google Gemini using anti-hallucination guardrails (`temperature=0.0`) and silence detection.
* **Autonomous Tool Execution**:
  * `search_faq`: Dynamic similarity and keyword matching across approved business knowledge items.
  * `record_unanswered_question`: Automatically logs unknown queries as `pending` enquiries and asks for caller callback consent.
  * `request_callback`: Captures verified customer callback phone numbers and timestamps.
* **Anti-Hallucination Audio Pipeline**: Guarded against ghost phrases and silent audio hallucinations with real decibel VU metering.

### 2. 🎛️ Interactive Voice Simulator (Web-Based Sandbox)
* **Real-time Web Audio API Waveform**: Canvas visualizer reactive only to actual microphone decibels (no fake animations).
* **Hardware Device Selector**: Pick any active microphone/headset on your operating system on the fly.
* **Instant TTS Voice Channel**: Native browser speech synthesis or server-rendered audio playback.
* **Turn-by-turn Diagnostic Badges**: See real-time execution badges for every tool invoked during a call.

### 3. 📞 Dual Telephony Integration (Twilio & Telnyx Ready)
* **Twilio Webhooks (TwiML)**: Full `<Gather input="speech">` and Amazon Polly neural voice streaming (`Polly.Joanna-Neural`).
* **Telnyx Webhooks (TeXML)**: Complete TeXML speech callbacks and call-control lifecycle handlers.
* **Zero Development Cost**: Fully testable on Twilio Free Trial ($15 credit) or Telnyx using `ngrok`.

### 4. 🏢 Multi-Tenant Back-Office Admin Portal
* **Business & Phone Number Routing**: Maps inbound caller `To` numbers to corresponding registered businesses.
* **Knowledge Base Management**: Add, update, and categorize business FAQs and operating hours.
* **Customer Enquiries Dashboard**: Review unanswered voice inquiries, triage callbacks, and train the agent with owner responses.
* **Call Transcript History**: Audit full message transcripts, duration, tool traces, and automated call summaries.

---

## 🏗️ Architecture

```
                                [Inbound Caller]
                                       │
                      ┌────────────────┴────────────────┐
                      ▼                                 ▼
             [Twilio / Telnyx]                [Voice Simulator Web UI]
              (Voice Webhooks)               (MediaRecorder + WebAudio)
                      │                                 │
                      └────────────────┬────────────────┘
                                       ▼
                       [FastAPI Unified Telephony Router]
                                       │
                     ┌─────────────────┴─────────────────┐
                     ▼                                   ▼
             [Gemini STT Layer]               [Gemini Receptionist Agent]
         (Temperature 0.0 + Guard)            (Tool Calling & Prompt Eng)
                                                         │
                                        ┌────────────────┴────────────────┐
                                        ▼                                 ▼
                              [Receptionist Tools]              [SQLite / PostgreSQL]
                          (search_faq, record_enquiry)          (Calls, Enquiries, FAQs)
```

---

## 🚀 Quickstart Guide

### 1. Prerequisites
* Python 3.11+
* A free [Google AI Studio Gemini API Key](https://aistudio.google.com/)

### 2. Clone and Setup Environment

```bash
git clone https://github.com/YOUR_USERNAME/Voice_agent.git
cd Voice_agent

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Open `.env` and fill in your Gemini API key:
```env
LLM_PROVIDER=gemini
LLM_API_KEY=your_gemini_api_key_here
LLM_MODEL=gemini-3.5-flash-lite
```

### 4. Initialize Database & Seed Demo Business

```bash
# Initialize DB tables and seed the demo clinic (Apex Dental)
python -c "from app.database import Base, engine; Base.metadata.create_all(bind=engine)"
python -c "from app.scripts.seed_receptionist import seed; seed()"
```

### 5. Run the Server

```bash
uvicorn app.main:app --reload --port 8000
```

Open your browser at:
* **Voice Receptionist Simulator**: [http://localhost:8000/admin/mock-call](http://localhost:8000/admin/mock-call)
* **Customer Enquiries Dashboard**: [http://localhost:8000/admin/customer-enquiries](http://localhost:8000/admin/customer-enquiries)
* **Swagger API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 🧪 Testing the Voice Simulator

1. Navigate to `http://localhost:8000/admin/mock-call`.
2. Select your microphone from the **🎤 Mic Input** dropdown.
3. Click **"Test Mic"** to verify sound is detected (Volume percentage turns green).
4. Click **"Start Inbound Call"**.
5. Click **"Mic"** to speak:
   * **FAQ Query**: *"Where is your clinic located and what are your opening hours?"*
   * **Unanswered Query**: *"Do you offer emergency root canals on Sunday midnight?"*
6. Click **"Hang Up"** to finalize the call and inspect the generated transcript and summary.

---

## 📞 Connecting Real Phone Numbers (Twilio / Telnyx)

### Free Testing with ngrok
Because Twilio and Telnyx require a public webhook URL to deliver incoming calls, expose your local server using `ngrok`:

```bash
ngrok http 8000
```

Copy the forwarding HTTPS URL (e.g. `https://your-domain.ngrok-free.app`).

### Twilio Console Setup
1. Go to your Twilio Phone Number configuration.
2. Under **"A Call Comes In"**, set:
   * **HTTP Method**: `POST`
   * **URL**: `https://your-domain.ngrok-free.app/api/telephony/twilio/voice`
3. Under **"Call Status Changes"**, set:
   * **URL**: `https://your-domain.ngrok-free.app/api/telephony/twilio/status`
4. Dial your Twilio number from your mobile phone!

### Telnyx Portal Setup
1. Go to **Telnyx Mission Control Portal** ➔ **TeXML Applications**.
2. Set **Voice URL** to `POST https://your-domain.ngrok-free.app/api/telephony/telnyx/voice`.
3. Set **Status Callback URL** to `POST https://your-domain.ngrok-free.app/api/telephony/telnyx/status`.

---

## 🧪 Running Automated Tests

Run the full test suite (Webhooks, Mock Call Flow, Agent Turn Processing):

```bash
pytest -v
```

---

## 🔒 Security & Privacy Notice
* API keys and secrets must never be committed to git.
* `.gitignore` is pre-configured to exclude `.env`, `keys.txt`, and database binaries.
