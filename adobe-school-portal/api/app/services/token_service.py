"""액세스 토큰 생성·검증 — 6자리 평문은 DB에 저장(관리자 조회·재발급)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccessToken, School

BCRYPT_ROUNDS = 4
TOKEN_LENGTH = 6
# 6자리 안내용 — 0/O, 1/I/L 혼동 제외
TOKEN_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
# 하위 호환
PHONE_TOKEN_ALPHABET = TOKEN_ALPHABET


def generate_plain_token(length: int = TOKEN_LENGTH) -> str:
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(length))


def normalize_token_input(raw: str) -> str:
    """로그인 입력 정규화 — 공백·하이픈 제거, 대문자."""
    cleaned = "".join(ch for ch in raw.strip().upper() if ch.isalnum())
    return cleaned


def token_lookup_digest(plain: str) -> str:
    return hashlib.sha256(normalize_token_input(plain).encode("utf-8")).hexdigest()


def hash_access_token(plain: str) -> str:
    normalized = normalize_token_input(plain)
    return bcrypt.hashpw(normalized.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_access_token(plain: str, token_hash: str) -> bool:
    try:
        normalized = normalize_token_input(plain)
        return bcrypt.checkpw(normalized.encode("utf-8"), token_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def access_token_is_active(row: AccessToken, *, now: datetime | None = None) -> bool:
    if row.revoked_at is not None:
        return False
    if row.expires_at is not None:
        ts = now or datetime.now(timezone.utc)
        exp = row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= ts:
            return False
    return True


async def _lookup_digest_taken(session: AsyncSession, digest: str) -> bool:
    result = await session.execute(
        select(AccessToken.id).where(AccessToken.lookup_digest == digest).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def create_unique_access_token(
    session: AsyncSession,
    school_id: int,
    *,
    label: str | None = None,
) -> tuple[str, AccessToken]:
    """학교용 6자리 토큰 생성 — lookup_digest 충돌 시 재시도."""
    for _ in range(40):
        plain = generate_plain_token()
        digest = token_lookup_digest(plain)
        if await _lookup_digest_taken(session, digest):
            continue
        row = AccessToken(
            school_id=school_id,
            token_hash=hash_access_token(plain),
            lookup_digest=digest,
            plain_token=normalize_token_input(plain),
            label=label,
        )
        session.add(row)
        await session.flush()
        return plain, row
    raise RuntimeError("고유 토큰을 생성하지 못했습니다. 다시 시도해 주세요.")


async def revoke_active_tokens_for_school(
    session: AsyncSession,
    school_id: int,
    *,
    now: datetime | None = None,
) -> int:
    ts = now or datetime.now(timezone.utc)
    rows = await list_active_tokens_for_school(session, school_id)
    revoked = 0
    for row in rows:
        if row.revoked_at is None and access_token_is_active(row, now=ts):
            row.revoked_at = ts
            revoked += 1
    return revoked


async def find_school_by_access_token(
    session: AsyncSession,
    plain: str,
) -> tuple[School, AccessToken] | None:
    """유효한 액세스 토큰 → (학교, 토큰 행). legacy 토큰은 bcrypt 검증 후 lookup_digest 백필."""
    token = normalize_token_input(plain)
    if not token:
        return None

    now = datetime.now(timezone.utc)
    digest = token_lookup_digest(token)

    result = await session.execute(
        select(AccessToken, School)
        .join(School, School.id == AccessToken.school_id)
        .where(AccessToken.lookup_digest == digest)
    )
    row = result.first()
    if row is not None:
        access_row, school = row
        if not access_token_is_active(access_row, now=now):
            return None
        if access_row.plain_token:
            if normalize_token_input(access_row.plain_token) != token:
                return None
        elif not verify_access_token(token, access_row.token_hash):
            return None
        return school, access_row

    legacy = await session.execute(
        select(AccessToken, School)
        .join(School, School.id == AccessToken.school_id)
        .where(
            AccessToken.lookup_digest.is_(None),
            AccessToken.revoked_at.is_(None),
        )
    )
    for access_row, school in legacy.all():
        if not access_token_is_active(access_row, now=now):
            continue
        if verify_access_token(token, access_row.token_hash):
            access_row.lookup_digest = digest
            if not access_row.plain_token:
                access_row.plain_token = token
            await session.flush()
            return school, access_row

    return None


async def reissue_access_token_for_school(
    session: AsyncSession,
    school_id: int,
    *,
    label: str | None = "6자리",
) -> tuple[str, AccessToken]:
    """기존 활성 토큰 폐기 후 새 6자리 토큰 1개 발급."""
    await revoke_active_tokens_for_school(session, school_id)
    return await create_unique_access_token(session, school_id, label=label)


async def list_active_tokens_for_school(
    session: AsyncSession,
    school_id: int,
) -> list[AccessToken]:
    result = await session.execute(
        select(AccessToken)
        .where(AccessToken.school_id == school_id)
        .order_by(AccessToken.created_at.desc())
    )
    return list(result.scalars().all())
