"""Create private configuration without printing secrets or overwriting existing values."""
import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / '.env'
if path.exists():
    print('.env already exists; kept existing configuration.')
else:
    content = (root / '.env.example').read_text().replace('LAB_API_KEY=\n',
                                                       f'LAB_API_KEY={secrets.token_urlsafe(32)}\n', 1)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        handle.write(content)
    print('Created .env (mode 600). Add ElevenLabs key/voice ID privately.')
