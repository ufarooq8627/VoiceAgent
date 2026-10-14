# Mock Agentic AI Voice Receptionist — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-grade Mock Voice Receptionist using FastAPI, SQLAlchemy (PostgreSQL/SQLite dual-compatible), and Gemini LLM with function-calling tools. It resolves dialed numbers to businesses, answers via approved static FAQs & freshness-validated live data, logs unanswerable enquiries, manages consent-gated callbacks with read-backs, and provides an owner review admin panel with Excel export.

**Architecture:** 
1. Multi-tenant data model with strict `business_id` isolation.
2. Deterministic Validation & Retrieval Engine (static approved knowledge + freshness-checked live adapters).
3. Receptionist Agent loop (`GeminiReceptionistAgent`) invoking four strictly scoped backend tools.
4. Mock Call Session runner simulating phone call turns with AI disclosure, conversation state, and consent read-back.
5. Owner Admin portal for enquiry resolution, knowledge base publishing, and Excel reporting.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic v2, Google GenAI SDK (`google-genai`), Jinja2, OpenPyXL, Pytest.

**Spec:** Agentic AI Voice Receptionist System Specification (Prompt 2026-10-14).

## Global Constraints
- Database schema must match the exact 8 tables and column types specified in Section 4.
- Zero invented business facts: if data is stale, missing, or unapproved, the agent must treat it as unconfirmed and log an unanswered enquiry.
- Personal data protection: callback contact info (`customer_name`, `callback_number`) can ONLY be stored if explicit caller consent and read-back confirmation occurred.
- All database operations and queries must be strictly scoped by `business_id` to prevent cross-business data leakage.
- Live human call transfers are out of scope for the MVP.

## Review Focus
1. Dialed phone number maps to an inactive or non-existent business: system must reject or play an unassigned message, never leak another business's data.
2. Expired or unapproved static knowledge items: must be filtered out by SQL queries before reaching the LLM.
3. Stale or failing live data adapter response: must return `status="unconfirmed"` and trigger the unanswered enquiry workflow.
4. Caller asks to callback but refuses confirmation of phone number: callback row must NOT be created; unanswered enquiry must still be preserved.
5. Excel export handles empty fields and unicode without corruption.

---

### Task 1: Receptionist Data Models & Multi-Tenant Business Isolation

**Files:**
- Create: `app/models/receptionist.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_receptionist_models.py`

**Interfaces:**
- Produces: `Business`, `BusinessPhoneNumber`, `KnowledgeItem`, `LiveDataSource`, `Call`, `UnansweredEnquiry`, `CallbackRequest`, `OwnerNotification`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_receptionist_models.py
import pytest
from datetime import datetime, timezone
from app.models.receptionist import (
    Business, BusinessPhoneNumber, KnowledgeItem, LiveDataSource,
    Call, UnansweredEnquiry, CallbackRequest, OwnerNotification
)

def test_create_business_and_phone_number(db_session):
    biz = Business(name="Acme Dental Clinic", timezone="Asia/Kolkata")
    db_session.add(biz)
    db_session.commit()
    assert biz.id is not None

    phone = BusinessPhoneNumber(
        business_id=biz.id,
        phone_number="+15551234567",
        provider="mock",
        active=True
    )
    db_session.add(phone)
    db_session.commit()
    assert phone.business.name == "Acme Dental Clinic"

def test_knowledge_item_status_and_validity(db_session):
    biz = Business(name="Dr. Smith Practice", timezone="UTC")
    db_session.add(biz)
    db_session.commit()

    item = KnowledgeItem(
        business_id=biz.id,
        question="What are your opening hours?",
        answer="Monday to Friday, 9am to 5pm.",
        category="hours",
        source="owner_manual",
        status="approved",
        valid_from=datetime.now(timezone.utc)
    )
    db_session.add(item)
    db_session.commit()
    assert item.status == "approved"
    assert item.valid_until is None
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_receptionist_models.py -v`
Expected: FAIL (ModuleNotFoundError or cannot import)

- [ ] **Step 3: Write implementation**
Create `app/models/receptionist.py` defining all 8 tables using SQLAlchemy 2.0 `Mapped` and `mapped_column`, foreign keys with cascading where appropriate, and relationships.

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/test_receptionist_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add app/models/receptionist.py app/models/__init__.py tests/test_receptionist_models.py
git commit -m "feat(receptionist): add core multi-tenant receptionist data models"
```

---

### Task 2: Static Knowledge Repository & Live Data Adapters

**Files:**
- Create: `app/services/knowledge_service.py`
- Create: `app/services/live_data_adapter.py`
- Test: `tests/test_knowledge_service.py`

**Interfaces:**
- `KnowledgeService.search_static(db, business_id, query) -> list[dict]`
- `KnowledgeService.bulk_import_csv(db, business_id, file_content) -> dict`
- `LiveDataAdapter.get_price_or_availability(db, business_id, item_key, requested_date) -> dict`

- [ ] **Step 1: Write failing tests**
Test approved vs unapproved knowledge filtering, validity window (`valid_from` <= now <= `valid_until`), live data freshness checking (results older than `freshness_limit_seconds` returned as unconfirmed).

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_knowledge_service.py -v`
Expected: FAIL

- [ ] **Step 3: Implement KnowledgeService and LiveDataAdapter**
Implement deterministic keyword / semantic matcher filtering strictly on `status == 'approved'`, business isolation, and `LiveDataAdapter` with mock flight/clinic/inventory data and freshness timestamp validation.

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/test_knowledge_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add app/services/knowledge_service.py app/services/live_data_adapter.py tests/test_knowledge_service.py
git commit -m "feat(receptionist): static knowledge search and freshness-checked live data adapter"
```

---

### Task 3: Unanswered Enquiries & Callback Manager

**Files:**
- Create: `app/services/enquiry_service.py`
- Test: `tests/test_enquiry_service.py`

**Interfaces:**
- `EnquiryService.log_unanswered(db, business_id, call_id, question, reason, context_summary) -> UnansweredEnquiry`
- `EnquiryService.create_callback_request(db, business_id, call_id, enquiry_id, customer_name, callback_number, consent=True) -> CallbackRequest`
- `EnquiryService.resolve_enquiry(db, enquiry_id, owner_answer, publish_to_kb=False) -> UnansweredEnquiry`

- [ ] **Step 1: Write failing tests**
Verify logging unanswered question creates notification; verify callback rejected without consent; verify resolving enquiry optionally creates an approved `KnowledgeItem`.

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_enquiry_service.py -v`
Expected: FAIL

- [ ] **Step 3: Implement EnquiryService**
Write clean, transaction-safe service methods with input validation and notification retry incrementing.

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/test_enquiry_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add app/services/enquiry_service.py tests/test_enquiry_service.py
git commit -m "feat(receptionist): enquiry logging, consent-checked callbacks and KB publishing"
```

---

### Task 4: Gemini Receptionist Agent & Function-Calling Tools

**Files:**
- Create: `app/agent/receptionist_agent.py`
- Create: `app/agent/receptionist_tools.py`
- Create: `app/agent/receptionist_prompts.py`
- Test: `tests/test_receptionist_agent.py`

**Interfaces:**
- `ReceptionistTools(db, business_id, call_id)`: provides approved tool signatures for LLM
- `GeminiReceptionistAgent.process_caller_turn(history, caller_text) -> AgentResponse`

- [ ] **Step 1: Write failing tests**
Verify agent discloses AI role on opening; verify agent calls `search_business_knowledge` for FAQ queries; verify agent queries `check_live_availability`; verify agent logs unanswered enquiry and prompts for callback when tool returns unconfirmed; verify agent executes read-back before final callback submission.

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_receptionist_agent.py -v`
Expected: FAIL

- [ ] **Step 3: Implement agent loop with Gemini tool calling**
Using `google-genai` SDK with function declarations for:
1. `search_faq(query)`
2. `check_dynamic_info(item_name, date)`
3. `record_unanswered_question(question, reason)`
4. `save_callback_request(customer_name, phone_number, read_back_confirmed)`

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/test_receptionist_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add app/agent/receptionist_agent.py app/agent/receptionist_tools.py app/agent/receptionist_prompts.py tests/test_receptionist_agent.py
git commit -m "feat(receptionist): Gemini tool-calling receptionist agent with zero-hallucination prompt"
```

---

### Task 5: Mock Call Interactive Simulator & Telephony Webhook Skeleton

**Files:**
- Create: `app/routes/receptionist_api.py`
- Create: `app/templates/admin/mock_call.html`
- Modify: `app/main.py`
- Test: `tests/test_mock_call_flow.py`

**Interfaces:**
- `POST /api/receptionist/calls/start`: initiates call session with dialed number resolution
- `POST /api/receptionist/calls/{call_id}/turn`: sends caller audio/text and gets agent speech text
- `POST /api/receptionist/calls/{call_id}/end`: ends call and saves summary

- [ ] **Step 1: Write failing tests**
End-to-end multi-turn simulation:
1. Dial business phone $ightarrow$ agent answers with AI disclosure.
2. Caller asks valid FAQ $ightarrow$ agent responds with verified answer.
3. Caller asks unknown question $ightarrow$ agent explains unconfirmed, saves enquiry, offers callback.
4. Caller accepts callback, provides details $ightarrow$ agent reads back details and confirms.

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_mock_call_flow.py -v`
Expected: FAIL

- [ ] **Step 3: Implement routes and interactive simulation UI**
Mount interactive test page in admin UI so developer can type/test simulated voice calls directly in browser.

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/test_mock_call_flow.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add app/routes/receptionist_api.py app/templates/admin/mock_call.html tests/test_mock_call_flow.py
git commit -m "feat(receptionist): mock call interactive simulator and turn API"
```

---

### Task 6: Owner Admin Management & Excel/CSV Export

**Files:**
- Create: `app/routes/receptionist_admin.py`
- Create: `app/templates/admin/enquiries.html`
- Create: `app/services/receptionist_export.py`
- Test: `tests/test_receptionist_admin.py`

**Interfaces:**
- `GET /admin/receptionist/enquiries`: list pending & resolved enquiries
- `POST /admin/receptionist/enquiries/{id}/resolve`: save owner answer & toggle publish to KB
- `GET /admin/receptionist/export`: export Excel with all 11 required columns

- [ ] **Step 1: Write failing tests**
Test resolution workflow, knowledge base update, and `.xlsx` generation with all required columns.

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_receptionist_admin.py -v`
Expected: FAIL

- [ ] **Step 3: Implement admin views and OpenPyXL export**

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/test_receptionist_admin.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add app/routes/receptionist_admin.py app/templates/admin/enquiries.html app/services/receptionist_export.py tests/test_receptionist_admin.py
git commit -m "feat(receptionist): owner review admin portal, KB publisher, and Excel export"
```

---

### Task 7: Full 25-Scenario Evaluation Suite & Final Verification

**Files:**
- Create: `tests/fixtures/receptionist_eval_cases.json`
- Create: `tests/test_receptionist_evaluation.py`

- [ ] **Step 1: Define comprehensive test suite covering Section 9**
Known FAQs, expired validity, stale live data, missing tickets, prompt injection attempts, caller consent refusal, read-back number mismatch, multiple businesses isolation.

- [ ] **Step 2: Run complete evaluation suite**
Run: `python -m pytest tests/test_receptionist_*.py -v`
Expected: 100% PASS with ZERO invented business facts.

- [ ] **Step 3: Final Commit**
```bash
git add -A
git commit -m "feat(receptionist): complete mock voice receptionist with 100% eval suite"
```
