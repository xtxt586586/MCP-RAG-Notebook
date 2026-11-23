"""Create a local-only .env without printing secrets or overwriting one."""
import os
import secrets
from pathlib import Path

key = os.environ["DEEPSEEK_API_KEY"]
if any(char in key for char in "\r\n#'\""):
    raise SystemExit("DEEPSEEK_API_KEY contains unsupported characters")
values = {"POSTGRES_PASSWORD": secrets.token_hex(24), "MINIO_ROOT_PASSWORD": secrets.token_hex(24),
          "JWT_SECRET_KEY": secrets.token_hex(32), "MCP_AUDIT_TOKEN": secrets.token_hex(32),
          "DEEPSEEK_API_KEY": key}
for protocol in ("HTTP", "HTTPS"):
    proxy = os.environ.get(f"CONTAINER_{protocol}_PROXY")
    if proxy:
        if any(char in proxy for char in "\r\n#'\""):
            raise SystemExit(f"CONTAINER_{protocol}_PROXY contains unsupported characters")
        values[f"{protocol}_PROXY"] = proxy
lines = Path('.env.example').read_text(encoding='utf-8').splitlines()
with Path('.env').open('x', encoding='utf-8') as output:
    written = set()
    for line in lines:
        name = line.partition('=')[0]
        if name in values:
            if name not in written:
                output.write(f'{name}={values[name]}\n')
                written.add(name)
        else:
            output.write(line + '\n')
    for name in ('HTTP_PROXY', 'HTTPS_PROXY'):
        if name in values and name not in written:
            output.write(f'{name}={values[name]}\n')
try:
    os.chmod('.env', 0o600)
except OSError:
    pass
