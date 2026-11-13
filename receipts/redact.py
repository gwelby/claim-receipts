"""redact — keep secrets out of the ledger without losing command identity.

Why this module exists
----------------------
`ledger.py` records terminal command text as evidence. That text is whatever the user typed, which
includes `export GITHUB_TOKEN=...`, `curl -H "Authorization: Bearer ..."`, `--password=...`. Keeping
it verbatim puts credentials in a plaintext file under the plugin data dir, where they outlive the
session and are readable by anything that can read that directory.

Why not simply redact the text
------------------------------
The judge decides whether a failing check was re-run by comparing command text (`judge._same_check`).
Redact `Bearer AAA` and `Bearer BBB` to the same `Bearer [REDACTED]` and the judge would treat a
DIFFERENT command as the identical failing one re-run — destroying rule C3, which several audit
rounds were spent hardening. So redaction is only safe alongside a digest of the exact original:
the display string loses the secret, the digest keeps identity exact.

The two together
----------------
  redact_command(raw) -> the string that may be stored and shown
  command_digest(raw) -> sha256 of the exact original, for identity only

Callers store both. `_same_check` compares digests when both records have one, compares text only
when neither does (legacy pair, both raw), and abstains when exactly one does — because in that case
the redacted side may be hiding a difference the digest would have caught.

Precision over coverage
-----------------------
Every pattern here is anchored to a shape that is a secret, not a guess: a named credential
assignment, an auth header, a known token prefix, a URL password. A pattern that redacted ordinary
words would quietly damage the path and verb parsing the judge depends on, which would be a worse
bug than the exposure it prevents. Redaction is fail-open: a command it cannot parse is stored as
typed rather than dropped.
"""
from __future__ import annotations

import hashlib
import re

REDACTED = "[REDACTED]"

# (a) headers: Authorization: Bearer xyz / Proxy-Authorization: Basic xyz
_AUTH_HEADER = re.compile(
    r"(?i)\b((?:proxy-)?authorization\s*:\s*(?:bearer|basic|token)\s+)([^\s\"'\\]+)")

# (b) a standalone bearer/basic token, e.g. `curl -H 'Bearer abc123...'`
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+([A-Za-z0-9._~+/=-]{16,})")

# (c) NAME=value where NAME names a credential. Keeps the NAME so the command stays readable.
_CRED_ASSIGN = re.compile(
    r"(?i)\b([A-Za-z0-9_]*"
    r"(?:TOKEN|SECRET|PASSWORD|PASSWD|APIKEY|API_KEY|PRIVATE_KEY|ACCESS_KEY|CREDENTIAL)"
    r"[A-Za-z0-9_]*)"
    r"(\s*=\s*)"
    r"('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|[^\s;&|]+)")

# (d) flags that carry a credential as their value
_CRED_FLAG = re.compile(
    r"(?i)(--(?:password|passwd|token|api-key|apikey|secret|auth-token)(?:=|\s+))(\S+)")

# (e) well-known token prefixes. `sk-` is split out at a longer minimum: at 8 characters it matched
# a filename like `sk-learn.py`, and a redactor that eats ordinary words damages the path parsing the
# judge depends on.
_KNOWN_PREFIX = re.compile(
    r"\b(gh[pousr]_|github_pat_|glpat-|xox[baprs]-|AKIA|AIza|npm_|dop_v1_)([A-Za-z0-9_-]{8,})")
_SK_PREFIX = re.compile(r"\b(sk-)([A-Za-z0-9_-]{20,})")

# (f) URL userinfo with a password: scheme://user:pass@host
_URL_PASSWORD = re.compile(r"(://)([^/\s:@]+):([^/\s@]+)@")


def redact_command(cmd: str) -> str:
    """Return the command with credential values replaced. Never raises; unparsed input is returned
    unchanged (fail-open, matching the rest of this plugin)."""
    if not isinstance(cmd, str):
        return ""
    if not cmd:
        return cmd
    try:
        out = _AUTH_HEADER.sub(r"\1" + REDACTED, cmd)
        out = _BEARER.sub(lambda m: f"{m.group(1)} {REDACTED}", out)
        out = _CRED_ASSIGN.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", out)
        out = _CRED_FLAG.sub(lambda m: f"{m.group(1)}{REDACTED}", out)
        out = _KNOWN_PREFIX.sub(lambda m: f"{m.group(1)}{REDACTED}", out)
        out = _SK_PREFIX.sub(lambda m: f"{m.group(1)}{REDACTED}", out)
        out = _URL_PASSWORD.sub(lambda m: f"{m.group(1)}{m.group(2)}:{REDACTED}@", out)
        return out
    except Exception:
        return cmd


def command_digest(cmd: str) -> str:
    """sha256 of the EXACT original command text. Identity, not display: this is what makes a
    redacted ledger still able to answer 'was this the same command run again?'."""
    if not isinstance(cmd, str):
        cmd = ""
    return hashlib.sha256(cmd.encode("utf-8", "surrogatepass")).hexdigest()

