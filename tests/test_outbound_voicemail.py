import pytest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from unittest.mock import patch

from app.models.receptionist import Business, BusinessPhoneNumber
from app.models.outbound import (
    OutboundCampaign,
    OutboundContact,
    OutboundConsent,
    OutboundVoicemailAsset,
    OutboundOptOutNumber,
    OutboundCampaignRecipient,
    OutboundCallAttempt,
    OutboundSuppression,
)
from app.services.outbound_service import (
    normalize_us_phone,
    assess_contact,
)
from app.outbound.worker import _claim_one
from app.config import settings


def test_normalize_us_phone_valid():
    assert normalize_us_phone("(415) 555-2671") == "+14155552671"
    assert normalize_us_phone("4155552671") == "+14155552671"
    assert normalize_us_phone("+1 415 555 2671") == "+14155552671"


def test_normalize_us_phone_invalid_raises():
    with pytest.raises(ValueError, match="Invalid phone number|Only valid US telephone numbers"):
        normalize_us_phone("12345")

    with pytest.raises(ValueError, match="Only valid US telephone numbers"):
        # UK number
        normalize_us_phone("+44 20 7946 0991")


def test_outbound_models_persistence(db_session):
    biz = Business(name="Dental Pro")
    db_session.add(biz)
    db_session.flush()

    caller = BusinessPhoneNumber(
        business_id=biz.id,
        phone_number="+14155550100",
        provider="twilio",
        active=True
    )
    db_session.add(caller)

    optout = OutboundOptOutNumber(
        business_id=biz.id,
        phone_e164="+18005550199",
        purpose_scope="all",
        active=True
    )
    db_session.add(optout)

    asset = OutboundVoicemailAsset(
        business_id=biz.id,
        name="promo.wav",
        script_text="Hello, this is a test voicemail message.",
        stored_filename="promo_123.wav",
        sha256="abc123sha456",
        mime_type="audio/wav",
        approval_status="APPROVED",
        approved_by="admin"
    )
    db_session.add(asset)
    db_session.flush()

    campaign = OutboundCampaign(
        business_id=biz.id,
        name="Spring Checkup",
        purpose="informational",
        seller_name="Dental Pro Clinic",
        caller_id=caller.phone_number,
        opt_out_number_id=optout.id,
        asset_id=asset.id,
        earliest_local_time="08:00",
        latest_local_time="20:00",
        daily_limit=100,
        max_attempts=2,
        calls_per_second=0.5,
        max_concurrent_calls=2
    )
    db_session.add(campaign)
    db_session.flush()

    contact = OutboundContact(
        business_id=biz.id,
        phone_e164="+14155552671",
        timezone_name="America/Los_Angeles",
        state_code="CA"
    )
    db_session.add(contact)
    db_session.flush()

    recipient = OutboundCampaignRecipient(
        business_id=biz.id,
        campaign_id=campaign.id,
        contact_id=contact.id,
        status="pending"
    )
    db_session.add(recipient)
    db_session.commit()

    # Query back
    saved_camp = db_session.query(OutboundCampaign).filter_by(id=campaign.id).first()
    assert saved_camp is not None
    assert saved_camp.name == "Spring Checkup"
    assert saved_camp.seller_name == "Dental Pro Clinic"


def test_assess_contact_blocks_suppressed(db_session):
    biz = Business(name="Apex Medical")
    db_session.add(biz)
    db_session.flush()

    optout = OutboundOptOutNumber(
        business_id=biz.id,
        phone_e164="+18005550188",
        purpose_scope="all",
        active=True
    )
    asset = OutboundVoicemailAsset(
        business_id=biz.id,
        name="test.wav",
        script_text="Test",
        stored_filename="test_123.wav",
        sha256="sha123",
        mime_type="audio/wav",
        approval_status="APPROVED"
    )
    db_session.add_all([optout, asset])
    db_session.flush()

    campaign = OutboundCampaign(
        business_id=biz.id,
        name="Checkup",
        purpose="informational",
        seller_name="Apex Medical",
        caller_id="+14155550100",
        opt_out_number_id=optout.id,
        asset_id=asset.id,
        earliest_local_time="08:00",
        latest_local_time="20:00",
        daily_limit=50,
        max_attempts=1,
        status="RUNNING",
    )
    contact = OutboundContact(
        business_id=biz.id,
        phone_e164="+14155559999",
        timezone_name="America/Los_Angeles",
        state_code="CA"
    )
    db_session.add_all([campaign, contact])
    db_session.flush()

    recipient = OutboundCampaignRecipient(
        business_id=biz.id,
        campaign_id=campaign.id,
        contact_id=contact.id,
        status="QUEUED",
    )
    db_session.add(recipient)
    db_session.flush()

    # Add suppression with non-null source
    suppression = OutboundSuppression(
        business_id=biz.id,
        phone_e164=contact.phone_e164,
        scope="all",
        reason="customer_opt_out",
        source="manual_entry"
    )
    db_session.add(suppression)
    db_session.commit()

    eligibility = assess_contact(db_session, campaign, contact)
    assert eligibility.eligible is False
    assert "suppress" in eligibility.reason.lower() or "opt" in eligibility.reason.lower()

    # The worker must suppress the queued recipient before creating a call attempt.
    assert _claim_one(db_session, datetime.now(timezone.utc)) is None
    db_session.refresh(recipient)
    assert recipient.status == "SUPPRESSED"
    assert db_session.query(OutboundCallAttempt).filter_by(recipient_id=recipient.id).count() == 0


def test_outbound_webhook_rejects_missing_signature(client):
    original_token = settings.twilio_auth_token
    original_base = settings.outbound_public_base_url
    settings.twilio_auth_token = "test-only-auth-token"
    settings.outbound_public_base_url = "https://test.domain.com"
    try:
        path = "/api/telephony/twilio/outbound/answer/att_123"
        missing = client.post(path, data={"AnsweredBy": "human"})
        invalid = client.post(
            path,
            data={"AnsweredBy": "human"},
            headers={"X-Twilio-Signature": "invalid-test-signature"},
        )
        assert missing.status_code == 403
        assert invalid.status_code == 403
    finally:
        settings.twilio_auth_token = original_token
        settings.outbound_public_base_url = original_base


def test_outbound_webhook_machine_beep_returns_twiml(client, db_session):
    orig_enabled = settings.outbound_enabled
    orig_base = settings.outbound_public_base_url
    settings.outbound_enabled = True
    settings.outbound_public_base_url = "https://test.domain.com"
    try:
        biz = Business(name="Sound Clinic")
        db_session.add(biz)
        db_session.flush()

        caller = BusinessPhoneNumber(
            business_id=biz.id,
            phone_number="+14155550111",
            provider="twilio",
            active=True
        )
        optout = OutboundOptOutNumber(
            business_id=biz.id,
            phone_e164="+18005550177",
            purpose_scope="all",
            active=True
        )
        asset = OutboundVoicemailAsset(
            business_id=biz.id,
            name="message.wav",
            script_text="Hello, here is your sound clinic message.",
            stored_filename="message_789.wav",
            sha256="123sha789",
            mime_type="audio/wav",
            approval_status="APPROVED",
            approved_by="tester"
        )
        db_session.add_all([caller, optout, asset])
        db_session.flush()

        campaign = OutboundCampaign(
            business_id=biz.id,
            name="Reminder",
            purpose="informational",
            seller_name="Sound Clinic",
            caller_id=caller.phone_number,
            opt_out_number_id=optout.id,
            asset_id=asset.id,
            earliest_local_time="08:00",
            latest_local_time="20:00",
            daily_limit=10,
            max_attempts=1,
            status="RUNNING"
        )
        contact = OutboundContact(business_id=biz.id, phone_e164="+14155552671", timezone_name="America/Los_Angeles", state_code="CA")
        db_session.add_all([campaign, contact])
        db_session.flush()

        # Add required consent
        consent = OutboundConsent(
            business_id=biz.id,
            contact_id=contact.id,
            phone_e164=contact.phone_e164,
            seller_name=campaign.seller_name,
            purpose=campaign.purpose,
            consent_type="express",
            evidence_reference="form_optin_123",
            granted_at=datetime.now(timezone.utc)
        )
        db_session.add(consent)
        db_session.flush()

        recip = OutboundCampaignRecipient(
            business_id=biz.id,
            campaign_id=campaign.id,
            contact_id=contact.id,
            status="pending"
        )
        db_session.add(recip)
        db_session.flush()

        attempt = OutboundCallAttempt(
            business_id=biz.id,
            campaign_id=campaign.id,
            recipient_id=recip.id,
            contact_id=contact.id,
            attempt_number=1,
            status="initiated",
            provider="twilio",
            provider_call_sid="CA_test_amd_123"
        )
        db_session.add(attempt)
        db_session.commit()

        with patch("app.routes.outbound_telephony._validated_form") as mock_validate:
            mock_validate.return_value = {
                "AnsweredBy": "machine_end_beep",
                "CallSid": "CA_test_amd_123",
                "CallStatus": "in-progress"
            }
            res = client.post(f"/api/telephony/twilio/outbound/answer/{attempt.id}")
            assert res.status_code == 200
            assert "application/xml" in res.headers["content-type"]
            root = ET.fromstring(res.text)
            assert root.tag == "Response"
            play_tags = root.findall(".//Play")
            assert len(play_tags) == 1
    finally:
        settings.outbound_enabled = orig_enabled
        settings.outbound_public_base_url = orig_base


def test_outbound_webhook_human_hangs_up_silently(client, db_session):
    orig_enabled = settings.outbound_enabled
    orig_base = settings.outbound_public_base_url
    settings.outbound_enabled = True
    settings.outbound_public_base_url = "https://test.domain.com"
    try:
        biz = Business(name="Silent Clinic")
        db_session.add(biz)
        db_session.flush()

        caller = BusinessPhoneNumber(
            business_id=biz.id,
            phone_number="+14155550111",
            provider="twilio",
            active=True
        )
        optout = OutboundOptOutNumber(
            business_id=biz.id,
            phone_e164="+18005550166",
            purpose_scope="all",
            active=True
        )
        asset = OutboundVoicemailAsset(
            business_id=biz.id,
            name="notice.wav",
            script_text="Notice",
            stored_filename="notice_456.wav",
            sha256="sha456",
            mime_type="audio/wav",
            approval_status="APPROVED"
        )
        db_session.add_all([caller, optout, asset])
        db_session.flush()

        campaign = OutboundCampaign(
            business_id=biz.id,
            name="Notice",
            purpose="informational",
            seller_name="Silent Clinic",
            caller_id=caller.phone_number,
            opt_out_number_id=optout.id,
            asset_id=asset.id,
            earliest_local_time="08:00",
            latest_local_time="20:00",
            daily_limit=10,
            max_attempts=1,
            status="RUNNING"
        )
        contact = OutboundContact(business_id=biz.id, phone_e164="+14155552671", timezone_name="America/Los_Angeles", state_code="CA")
        db_session.add_all([campaign, contact])
        db_session.flush()

        consent = OutboundConsent(
            business_id=biz.id,
            contact_id=contact.id,
            phone_e164=contact.phone_e164,
            seller_name=campaign.seller_name,
            purpose=campaign.purpose,
            consent_type="express",
            evidence_reference="human_answer_test_opt_in",
            granted_at=datetime.now(timezone.utc),
        )
        db_session.add(consent)
        db_session.flush()

        recip = OutboundCampaignRecipient(
            business_id=biz.id,
            campaign_id=campaign.id,
            contact_id=contact.id,
            status="pending"
        )
        db_session.add(recip)
        db_session.flush()

        attempt = OutboundCallAttempt(
            business_id=biz.id,
            campaign_id=campaign.id,
            recipient_id=recip.id,
            contact_id=contact.id,
            attempt_number=1,
            status="initiated",
            provider="twilio",
            provider_call_sid="CA_test_human_456"
        )
        db_session.add(attempt)
        db_session.commit()

        with patch("app.routes.outbound_telephony._validated_form") as mock_validate:
            mock_validate.return_value = {
                "AnsweredBy": "human",
                "CallSid": "CA_test_human_456",
                "CallStatus": "in-progress"
            }
            res = client.post(f"/api/telephony/twilio/outbound/answer/{attempt.id}")
            assert res.status_code == 200
            root = ET.fromstring(res.text)
            assert root.tag == "Response"
            # Human answer in voicemail-only pilot -> NO Play tag, immediate hangup
            assert len(root.findall(".//Play")) == 0
            assert len(root.findall(".//Hangup")) == 1
            db_session.refresh(attempt)
            assert attempt.status == "NO_MESSAGE_HUMAN"
    finally:
        settings.outbound_enabled = orig_enabled
        settings.outbound_public_base_url = orig_base
