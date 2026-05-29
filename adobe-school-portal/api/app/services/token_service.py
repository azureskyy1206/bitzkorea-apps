"""액세스 토큰 bcrypt 해시·검증 (평문은 발급 시 1회만 노출)."""

import secrets

import bcrypt

BCRYPT_ROUNDS = 12


def generate_plain_token() -> str:
    return secrets.token_urlsafe(32)


def hash_access_token(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_access_token(plain: str, token_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), token_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
