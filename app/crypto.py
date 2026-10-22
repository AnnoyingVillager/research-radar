from __future__ import annotations

import ipaddress
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

SECRET_SETTING_FIELDS = ("openalex_api_key", "llm_api_key", "smtp_password")
ENCRYPTED_VALUE_PREFIX = "enc:v1:"


class SecretStorageError(RuntimeError):
    """Raised when an encrypted value cannot be read safely."""


class SecretCipher:
    def __init__(self, key: bytes):
        self._fernet = Fernet(key)

    @classmethod
    def from_key_file(cls, path: Path) -> SecretCipher:
        return cls(_read_or_create_key(path))

    def encrypt(self, value: str) -> str:
        if not value:
            return value
        token = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        return f"{ENCRYPTED_VALUE_PREFIX}{token}"

    def decrypt(self, value: str) -> str:
        if not value or not value.startswith(ENCRYPTED_VALUE_PREFIX):
            return value
        token = value.removeprefix(ENCRYPTED_VALUE_PREFIX)
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise SecretStorageError(
                "无法解密数据库中的敏感设置，请检查 radar-secrets 卷和设置加密密钥。"
            ) from exc


def read_or_create_secret(path: Path, *, byte_count: int = 32) -> str:
    if path.exists():
        _secure_private_file(path)
        value = path.read_text(encoding="ascii").strip()
        if value:
            return value

    generated = secrets.token_urlsafe(byte_count)
    if _create_private_file(path, (generated + "\n").encode("ascii")):
        return generated

    # Another process may have won the initial creation race.
    for _ in range(20):
        value = path.read_text(encoding="ascii").strip()
        if value:
            return value
        time.sleep(0.01)
    raise SecretStorageError(f"无法初始化敏感文件：{path}")


def rotate_secret(path: Path, *, byte_count: int = 32) -> str:
    generated = secrets.token_urlsafe(byte_count)
    _replace_private_file(path, (generated + "\n").encode("ascii"))
    return generated


def delete_private_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def ensure_self_signed_certificate(
    cert_path: Path,
    key_path: Path,
    hostnames: str,
) -> tuple[Path, Path]:
    hosts = _normalize_hostnames(hostnames)
    manifest_path = cert_path.with_suffix(".hosts")
    manifest = "\n".join(hosts)

    if _certificate_is_current(cert_path, key_path, manifest_path, manifest):
        _secure_private_file(key_path)
        return cert_path, key_path

    private_key = ec.generate_private_key(ec.SECP256R1())
    common_name = hosts[0]
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    alternative_names: list[x509.GeneralName] = []
    for host in hosts:
        try:
            alternative_names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            alternative_names.append(x509.DNSName(host))

    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=397))
        .add_extension(x509.SubjectAlternativeName(alternative_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_bytes = certificate.public_bytes(serialization.Encoding.PEM)
    _replace_private_file(key_path, key_bytes)
    _replace_private_file(cert_path, cert_bytes, mode=0o644)
    _replace_private_file(manifest_path, manifest.encode("utf-8"), mode=0o644)
    return cert_path, key_path


def _read_or_create_key(path: Path) -> bytes:
    if path.exists():
        _secure_private_file(path)
        encoded = path.read_bytes().strip()
    else:
        encoded = Fernet.generate_key()
        if not _create_private_file(path, encoded + b"\n"):
            encoded = path.read_bytes().strip()
    try:
        decoded = Fernet(encoded)
    except (ValueError, TypeError) as exc:
        raise SecretStorageError(f"设置加密密钥格式无效：{path}") from exc
    del decoded
    return encoded


def _certificate_is_current(
    cert_path: Path,
    key_path: Path,
    manifest_path: Path,
    expected_manifest: str,
) -> bool:
    if not cert_path.exists() or not key_path.exists() or not manifest_path.exists():
        return False
    try:
        certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
        manifest = manifest_path.read_text(encoding="utf-8")
    except (ValueError, OSError):
        return False
    return (
        manifest == expected_manifest
        and certificate.not_valid_after_utc > datetime.now(UTC) + timedelta(days=7)
    )


def _normalize_hostnames(value: str) -> list[str]:
    hosts = {"localhost", "127.0.0.1"}
    hosts.update(
        item.strip().lower()
        for item in value.split(",")
        if item.strip()
    )
    return sorted(hosts, key=lambda item: (item != "localhost", item))


def _create_private_file(path: Path, data: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise
    return True


def _secure_private_file(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        # The container entrypoint also repairs volume permissions before startup.
        pass


def _replace_private_file(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        mode,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
