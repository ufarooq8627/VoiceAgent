import sys
import pathlib
import bcrypt

def set_password(new_pass: str):
    if len(new_pass) < 8:
        print('ERROR: Password must be at least 8 characters.')
        sys.exit(1)
        
    hashed = bcrypt.hashpw(new_pass.encode('utf-8'), bcrypt.gensalt(12)).decode('utf-8')
    env_path = pathlib.Path('.env')
    if not env_path.exists():
        print('ERROR: .env file not found.')
        sys.exit(1)
        
    lines = env_path.read_text(encoding='utf-8').splitlines()
    found = False
    new_lines = []
    
    for line in lines:
        if line.startswith('ADMIN_PASSWORD_HASH='):
            new_lines.append(f'ADMIN_PASSWORD_HASH={hashed}')
            found = True
        else:
            new_lines.append(line)
            
    if not found:
        new_lines.append(f'ADMIN_PASSWORD_HASH={hashed}')
        
    env_path.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')
    print('SUCCESS: Admin password updated in .env successfully.')

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python scripts/set_admin_password.py YOUR_NEW_PASSWORD')
        sys.exit(1)
    set_password(sys.argv[1])
