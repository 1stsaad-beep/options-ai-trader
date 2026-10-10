"""Generate private local demo secrets, never credentials for a broker."""
from pathlib import Path
import secrets
import os
p = Path(__file__).resolve().parents[1] / 'infra' / '.env'
if p.exists():
    raise SystemExit('infra/.env already exists; refusing to overwrite')
fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write(f'OPTIONS_API_TOKEN={secrets.token_urlsafe(32)}\nPOSTGRES_PASSWORD={secrets.token_hex(24)}\n')
print('Created private infra/.env for mock deployment; read it locally only.')
