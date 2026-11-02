# Voice Agent Platform — Full Project Scope

**Document status:** Product and delivery scope based on the current repository and its design documents  
**Scope tracks:** AI voice receptionist and SaaS foundation; outbound voicemail pilot; recruitment email scheduling agent  
**Important product decision:** The repository contains two distinct product tracks (voice operations and recruitment scheduling). This scope documents both, but product ownership, shared branding, and whether they ship as one SaaS product remain to be decided.

## 1. Product vision

Build a secure business automation platform that helps organizations handle routine customer calls and follow-up work with grounded AI, clear human handoffs, and auditable workflows. The core voice product answers inbound calls using business-approved information, captures unresolved enquiries, and supports consent-confirmed callbacks. A separately controlled outbound module can deliver approved voicemail recordings to eligible contacts. The repository also contains a recruitment workflow that coordinates interview scheduling through email.

The platform must keep business data separated, prevent the AI from inventing business facts or taking unapproved actions, and preserve a human review path for uncertain or sensitive work.

## 2. Product outcomes

- Callers receive timely, consistent answers to routine questions.
- The receptionist answers only from approved, current business information or explicitly connected live data.
- Unanswered questions become actionable work for the business owner or staff.
- Callback details are stored only after explicit consent and number read-back confirmation.
- Outbound voicemail activity is gated by contact eligibility, local calling hours, approved content, and opt-out controls.
- Recruiters can coordinate interview invitations and bookings while retaining visibility and control over exceptions.
- Administrators can audit activity, usage, configuration, and operational outcomes.

## 3. Users and roles

| User | Main needs |
|---|---|
| Platform administrator | Manage tenants, access, configuration, support, and service health. |
| Business owner or receptionist administrator | Configure business identity, phone routing, approved knowledge, live-data sources, callbacks, enquiries, and usage. |
| Business staff | Review unresolved questions and callback requests; provide or approve answers. |
| Caller | Get a clear AI disclosure, useful answers, a human follow-up path, and an easy way to opt out of outbound calls. |
| Outbound campaign operator | Import eligible contacts, select approved recording and caller ID, pass preflight, obtain approval, launch, pause, and review campaign outcomes. |
| Recruiter | Manage jobs, candidates, interviewers, availability, invitations, exceptions, and reports. |
| Candidate | Receive interview options, choose a slot by email or fallback booking page, and receive confirmation. |

## 4. Scope status key

- **Present in repository:** Implemented code or an established project workflow exists. Deployment configuration and production readiness still need separate verification.
- **First release scope:** Required for the intended initial usable release; some items may still need implementation or hardening.
- **Later:** Valuable follow-on capability after the first release.
- **Excluded:** Explicitly outside the first release.

The status reflects repository/design evidence, not a production certification. A route or model existing does not by itself mean the complete user journey is operational in a live environment.

## 5. Product modules and functional scope

### 5.1 Shared SaaS and application foundation

**Present in repository / First release scope**

- FastAPI application with server-rendered administrative pages and API routes.
- SQLAlchemy persistence with local SQLite support and PostgreSQL production target.
- Authentication for administrative and portal access, configurable secrets, CORS controls, and rate limiting.
- Business-aware records and APIs for receptionist configuration and operations.
- API client and usage-metering foundations, plus widget/token endpoints.
- Alembic schema migrations for production deployments; production startup should use the current database revision.
- Operational event, enquiry, campaign, and conversation records appropriate to their workflows.

**First release requirements**

- Define and enforce tenant ownership on every tenant-facing read and write.
- Establish a production identity and role model, including platform administration versus tenant administration.
- Maintain audit records for configuration changes, approvals, consent, call outcomes, and campaign actions.
- Provide documented backup, restore, secret rotation, migration, and incident procedures.

### 5.2 Inbound AI voice receptionist

**Present in repository**

- Receptionist agent and business knowledge services, call state, enquiry and callback workflows, admin pages, a browser-based mock call simulator, telephony route foundations, and business phone-number routing.
- Grounded answers based on approved knowledge; configurable conversation context; AI disclosure in the designed call flow.
- Callback consent flow with phone number read-back and explicit caller confirmation.
- Enquiry review and knowledge management foundations.

**First release scope**

1. Route an inbound call to the correct active business using its configured phone number.
2. Tell the caller they are speaking with an AI receptionist.
3. Answer routine questions only from active, approved business knowledge.
4. Use configured live-data adapters only when the source is available and within its freshness limit. Treat missing, stale, or failed data as unconfirmed.
5. Capture an unresolved question with enough context for staff follow-up, without fabricating an answer.
6. Offer a callback where appropriate. Collect contact details only after consent; read the number back and save only after affirmative confirmation.
7. Give the owner/staff a queue to review, resolve, and optionally approve new reusable knowledge.
8. Preserve a clear call outcome and operational audit trail.
9. Support a simulator for development and controlled demonstrations.

**Later**

- Additional telephony providers and regions after the Twilio path is validated.
- More live-data connectors, business-system integrations, and configurable escalation policies.
- Advanced analytics, multilingual support, and human transfer when a supported operating model is designed.

### 5.3 Outbound voicemail pilot

**Present in repository**

- Dedicated outbound worker and Twilio call flow, campaign/contact/audio models and admin endpoints, phone validation, explicit IANA timezone handling, call-window preflight, signed short-lived audio delivery, Twilio signature validation, callback opt-out handling, in-call keypad opt-out, and Alembic migrations.
- Outbound is disabled by default and runs separately from the inbound receptionist.

**First release scope**

1. An operator creates a campaign for a business, selecting a business-registered caller ID and one approved recording.
2. The operator imports contacts with phone, state, explicit IANA timezone, consent type/evidence, and consent date.
3. Preflight rejects invalid or incomplete records and checks configured local calling windows (currently 08:00–21:00 local time).
4. A human records campaign approval and the required recent Do Not Call review before launch. This is an operator-recorded gate; the pilot does not query registry services.
5. The separate worker claims and paces eligible calls. It must not make calls when the feature flag is off or a campaign is paused/stopped.
6. Answering-machine detection delivers the approved recording only for the configured `machine_end_beep` result. Other or ambiguous results do not play the recording.
7. Recipients can opt out by replying to the configured callback number or pressing the configured keypad option during the call. Opt-outs are persisted and applied to future eligible calls within the configured scope.
8. Record submission, completion, opt-out, error, and reconciliation states; do not equate a completed call with confirmed audio playback.
9. Do not retry automatically in this pilot. Ambiguous provider submissions require operator reconciliation.

**Excluded from the pilot**

- Live AI sales conversations or AI-generated per-recipient messages.
- Automatic contact discovery, lead scraping, or calls without documented eligibility and consent evidence.
- Automatic federal/state Do Not Call registry lookup.
- Automatic retries, predictive dialing, parallel high-volume dialing, or multiple campaign workers.
- Treating an answered call or call completion as proof that a voicemail was played.

### 5.4 Recruitment email scheduling track

**Present in repository/design**

- Job, candidate, interviewer, time-slot, invitation, booking, email outbox/inbox, conversation/event audit, admin, and export concepts are described in the recruitment design. The repository contains recruitment-related models and workflows; real-provider email/calendar readiness must be checked separately.

**First release scope for this track**

1. Recruiter creates jobs, candidates, interviewers, and available time slots.
2. Recruiter selects candidates for a job and sends interview invitations listing available options.
3. Candidate replies by email or uses a secure token-based booking page.
4. The system classifies a reply into structured intent, validates it, and books only an available slot using an atomic operation.
5. If a slot is taken, the system offers remaining times; unclear replies receive a clarification; no suitable time or unsupported cases go to the recruiter.
6. Recruiter can inspect the conversation/event history and export operational data.

**Later / provider-dependent**

- Production Gmail/SMTP plus IMAP or equivalent mail integration, reliable inbound delivery, reminders, calendar invitations, cancellation and rescheduling workflows, and broader calendar synchronization.
- Candidate matching/ranking or resume analysis unless separately specified and approved.

This track is a distinct product workflow from the voice receptionist and should have independent release acceptance and positioning.

## 6. End-to-end user flows

### Inbound call

1. Telephony provider calls the application webhook with the dialed business number.
2. The application verifies the provider request, resolves an active business, and creates or retrieves call state.
3. The receptionist discloses its AI role and handles the caller turn.
4. The system retrieves only tenant-scoped, approved, valid knowledge; live data is checked for freshness.
5. It answers supported questions, asks a clarifying question where needed, or logs an unresolved enquiry.
6. If a callback is offered, the caller consents, provides a number, hears a read-back, and explicitly confirms it before a request is saved.
7. Staff review the enquiry/callback, resolve it, and may publish a reviewed answer to the approved knowledge base.

### Outbound voicemail campaign

1. Operator creates campaign, approves one recording, and imports contacts with eligibility evidence and timezones.
2. Preflight validates the campaign, contacts, opt-out status, business caller ID, feature flag, and local calling window.
3. Human approval and required campaign review are recorded.
4. Dedicated worker claims and paces calls; provider callbacks update each attempt.
5. Only the approved machine-beep path plays the recording; opt-outs stop future calls according to the configured scope.
6. Operator reviews results and manually reconciles uncertain submissions; no automated retry is performed.

### Recruitment scheduling

1. Recruiter creates a job, candidates, interviewers, and open slots.
2. Invitations are queued through the configured email provider.
3. Candidate selects an option through a reply or secure booking link.
4. The application validates the choice and atomically reserves the slot.
5. Confirmation or clarification is sent; exceptions are surfaced to the recruiter.

## 7. Core data concepts

The precise schema is defined by the SQLAlchemy models and migrations. The product-level entities include:

- **Tenant/business:** organization identity, settings, status, and owned resources.
- **Business phone number:** provider, number, active routing, and opt-out configuration.
- **Knowledge item / live data source:** tenant-scoped business facts, approval/validity state, source, and freshness configuration.
- **Call / call turn:** provider identifiers, tenant, state, timestamps, outcome, and minimal safe operational context.
- **Unanswered enquiry / callback request / owner notification:** follow-up work, consent evidence, resolution state, and notification status.
- **Outbound campaign / contact / recording asset / call attempt / opt-out:** reviewed content, recipient eligibility, execution state, and suppression records.
- **API client / usage record / widget token:** external access, metering, and controlled public-facing entry points.
- **Recruitment job / candidate / interviewer / slot / invitation / booking:** scheduling lifecycle and ownership.
- **Email outbox / inbound message / conversation event:** delivery and auditable recruitment communication history.

## 8. Safety, privacy, and security requirements

- Enforce tenant scoping at the service and data-access layer; never select a business by untrusted caller input alone.
- Validate telephony webhook signatures and use short-lived signed links for private media.
- Store secrets in environment/secret management, never in source control or logs.
- Avoid logging caller audio and raw speech transcripts by default. Keep diagnostic data minimal and access-controlled.
- Store callback details only after the specified consent and read-back confirmation; define retention and deletion policies before production use.
- Use approved, current facts only. If grounding or live-data freshness fails, ask staff to follow up.
- Require explicit human campaign approval, contact eligibility evidence, opt-out suppression, configured local time windows, and operational kill switches for outbound calls.
- Use idempotent webhook/event processing and database constraints for booking and call-state changes where supported.
- Separate outbound execution from web request processing; use PostgreSQL for production campaign traffic and Alembic for schema changes.
- Restrict admin and tenant access by role; rate-limit sensitive endpoints; audit changes and approvals.
- Apply file validation, private storage, access controls, and retention limits to recordings, resumes, and exports.
- Establish retention, deletion, incident response, backup, and restore procedures appropriate to each data type before production launch.

## 9. Non-functional requirements

- **Reliability:** provider errors and LLM timeouts result in safe fallback or queued human follow-up, not invented answers or duplicate actions.
- **Performance:** voice turn latency must be measured under realistic provider and model conditions; release targets should be set before production rollout.
- **Scale:** initial outbound pilot is a single worker with database-backed claiming/pacing; higher throughput requires a separate capacity design.
- **Maintainability:** provider adapters, business logic, persistence, and UI remain separated; schema changes are reviewed Alembic migrations.
- **Observability:** operational metrics should cover call outcomes, provider errors, answer grounding, unresolved enquiries, callbacks, campaign pacing, opt-outs, and email delivery without exposing unnecessary caller content.
- **Accessibility and usability:** owner and operator screens should make approval status, errors, opt-outs, and follow-up work understandable.
- **Portability:** local development may use SQLite; production should use PostgreSQL and durable private media storage.

## 10. First-release deliverables

1. A tenant-aware inbound receptionist flow with approved static knowledge and safe unknown-answer handling.
2. Owner/staff enquiry and callback review workflow with consent-confirmed callback creation.
3. A controlled telephony integration and a working simulator for development/demo use.
4. A feature-flagged outbound voicemail pilot with Twilio, private recording storage, preflight, human approval, local-time gating, opt-outs, and no automatic retries.
5. Production migration and deployment instructions, including PostgreSQL setup, secret configuration, separate worker operation, backup and restore, and operator runbooks.
6. Recruitment email scheduling delivered as a separately accepted module, with provider integrations explicitly marked as live or simulated.
7. Admin reporting sufficient to review enquiries, callbacks, call outcomes, campaign results, opt-outs, and recruitment bookings.

## 11. Acceptance criteria

### Voice receptionist

- An inbound call to a configured number resolves only to the owning active business.
- The caller hears AI disclosure and receives answers only from approved, valid tenant knowledge or fresh configured live data.
- Unknown, stale, or failed retrieval is not presented as fact and creates a reviewable enquiry.
- A callback cannot be created until consent and explicit read-back confirmation are recorded.
- A business administrator cannot view or modify another tenant's knowledge, enquiries, callbacks, or calls.
- Provider signature failures and service failures fail safely and create actionable operational records where possible.

### Outbound voicemail

- Outbound cannot run with its feature flag disabled.
- Preflight prevents launch with invalid contacts, missing timezone/eligibility evidence, unapproved asset, invalid caller ID, or active opt-out.
- No call is initiated outside the configured local window.
- Only the configured AMD machine-beep result can trigger recording playback.
- Stop/pause prevents new calls; callbacks and keypad opt-outs suppress subsequent eligible campaign calls.
- Ambiguous submissions are not retried automatically and can be reconciled by an operator.

### Recruitment

- A slot cannot be confirmed for more than one candidate, including concurrent selections.
- Unclear or unsupported candidate replies are surfaced for clarification or recruiter handling.
- Email sending and booking outcomes appear in the candidate's ordered conversation/event history.
- Secure booking links do not expose another candidate's data and expire or become invalid according to configured rules.

### Release operations

- A new production database can be initialized from migrations and an existing supported database can be upgraded using the documented procedure.
- Production starts only with required secrets and current schema revision.
- Operator documentation covers pause/stop, opt-out handling, webhook troubleshooting, campaign reconciliation, and incident escalation.

## 12. Success measures

Set numeric targets during pilot planning. Track at minimum:

- Inbound call completion and safe fallback rates.
- Share of routine questions answered from approved knowledge and share routed to staff.
- Callback consent completion, successful follow-up, and enquiry resolution time.
- Telephony/LLM error rate and median/95th percentile response latency.
- Outbound preflight rejection reasons, provider submission outcome, confirmed recording playback, opt-out rate, and reconciliation volume.
- Recruitment invitation delivery, confirmed booking rate, time to booking, and recruiter-handled exception rate.
- Tenant isolation and security incidents (target: zero).

## 13. Deployment and operating assumptions

- Python application with FastAPI; production persistence on PostgreSQL with Alembic migrations.
- Twilio is the first outbound telephony provider; inbound production provider and supported deployment regions must be confirmed for release.
- Outbound media is stored privately and served via HTTPS signed links. The current pilot uses a private local audio directory; production storage durability and backup must be specified for the chosen hosting setup.
- Outbound worker runs as a separate, single process for the pilot.
- LLM provider credentials, mail credentials, telephony credentials, public webhook URL, and secret values are provided through deployment configuration.
- The recruitment track's real email and calendar providers are not considered production-ready until credentials, webhooks/polling, deliverability, and recovery behavior are configured and verified.
- Production launch is contingent on jurisdiction-specific review of call eligibility, consent, disclosure, recording, opt-out wording, retention, and calling rules by the responsible organization.

## 14. Risks and open decisions

1. **Product boundary:** Should recruitment scheduling remain in the same product/repository as the voice receptionist, or become a separate application/product?
2. **First customer and vertical:** Which business types and geographies should shape the first production knowledge and live-data integrations?
3. **Inbound telephony:** Which provider, countries, phone-number provisioning, failover, and call recording/transcription settings are required?
4. **Human escalation:** Should the first release only create callback/enquiry tasks, or include a live transfer workflow later?
5. **Outbound eligibility:** Which campaign categories are allowed, what evidence is required, and who is authorized to approve launch?
6. **Do Not Call operations:** Which registry checks or external suppression sources are required beyond operator attestation before broader rollout?
7. **Media storage:** Which durable object store, retention, access policy, and deletion process should replace local disk in production?
8. **Recruitment integrations:** Which email and calendar providers are in the first usable release, and is an email-only booking flow acceptable initially?
9. **Plans and billing:** What usage limits, metering units, pricing, and tenant self-service are required for a commercial SaaS launch?
10. **Service objectives:** What latency, uptime, support-hours, data-retention, and recovery targets should the pilot meet?

## 15. Recommended delivery sequence

1. **Confirm the product boundary and pilot customer.** Decide whether recruitment ships with voice or as a separate track; pick a narrow first voice use case and jurisdiction.
2. **Close the production foundation.** Confirm tenant roles and isolation, PostgreSQL deployment, migrations, secrets, backups, observability, and durable media storage.
3. **Validate inbound receptionist end to end.** Complete provider routing, business setup, approved knowledge lifecycle, unresolved enquiry, callback consent, and owner review.
4. **Run a controlled outbound pilot.** Keep outbound disabled until contact eligibility, campaign approval, opt-out operations, scripts, jurisdiction review, and provider webhooks are ready. Begin with small volumes and manual reconciliation.
5. **Complete recruitment as its own release track.** Decide provider integrations, then verify invitation, reply ingestion, atomic booking, fallback link, exceptions, and reporting.
6. **Expand integrations and scale.** Add connectors, multiple workers/providers, billing, analytics, and richer automation only after pilot evidence supports them.

## 16. Explicitly outside the initial release

- Autonomous sales negotiation or unsupervised AI conversations with outbound recipients.
- AI-generated voicemail content personalized at call time.
- Unreviewed changes to published business facts or automatic answers from arbitrary web pages.
- Live human call transfer unless separately designed and delivered.
- Automatic campaign retries or high-volume predictive dialing.
- Automatic Do Not Call registry integration in the current pilot.
- Unspecified CRM, calendar, payment, or business-system integrations.
- Candidate ranking, hiring decisions, or fully automated selection/rejection of applicants.
- A guarantee of legal compliance based solely on software controls.
