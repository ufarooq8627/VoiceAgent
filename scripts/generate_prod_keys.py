"""
Production Key & Password Hash Generator for VoiceAgent.
Run this script to generate secure keys for your production .env file:
    python scripts/generate_prod_keys.py [optional_admin_password]
"""
import sys
import secrets
import bcrypt

def generate():
    # 1. Cryptographically secure 64-char hex session secret key
    secret_key = secrets.token_hex(32)

    # 2. Telephony webhook token
    telephony_token = secrets.token_urlsafe(24)

    # 3. Admin password hash
    if len(sys.argv) > 1:
        admin_pass = sys.argv[1]
    else:
        admin_pass = secrets.token_urlsafe(12)
        print(f"Generated Temporary Admin Password: {admin_pass}")

    hashed = bcrypt.hashpw(admin_pass.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    print("\n" + "=" * 65)
    print("PRODUCTION .ENV SECURITY CONFIGURATION")
    print("=" * 65)
    print(f"APP_SECRET_KEY={secret_key}")
    print(f"ADMIN_USERNAME=admin")
    print(f"ADMIN_PASSWORD_HASH={hashed}")
    print(f"TELEPHONY_WEBHOOK_TOKEN={telephony_token}")
    print(f"ENVIRONMENT=production")
    print("=" * 65)
    print("Copy the above lines into your production .env file.")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    generate()
