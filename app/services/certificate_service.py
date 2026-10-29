import hmac
import hashlib
import json
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.exceptions import InvalidSignature

from app.models.certificate import Certificate
from app.services.audit_service import AuditService
from app.config import settings


# Derive deterministic backend Ed25519 signing key from secret
_ED25519_SEED = hashlib.sha256(b"PRAMAAN-ED25519-SIGNING-ROOT:" + settings.SECRET_KEY.encode("utf-8")).digest()
_ED25519_PRIVATE_KEY = ed25519.Ed25519PrivateKey.from_private_bytes(_ED25519_SEED)
_ED25519_PUBLIC_KEY = _ED25519_PRIVATE_KEY.public_key()
_ED25519_PUBLIC_KEY_HEX = _ED25519_PUBLIC_KEY.public_bytes_raw().hex()

ACTIVE_KEY_ID = "SENTINEL-ED25519-2026-V1"
LEGACY_HMAC_KEY_ID = "SENTINEL-TEST-ROOT-2026"
TEST_HMAC_KEY_ID = "SENTINEL-TEST-KEY"

KEY_REGISTRY: Dict[str, Dict[str, Any]] = {
    ACTIVE_KEY_ID: {
        "key_id": ACTIVE_KEY_ID,
        "algorithm": "Ed25519",
        "public_key_hex": _ED25519_PUBLIC_KEY_HEX,
        "status": "ACTIVE",
        "description": "PRAMAAN Ed25519 Institutional Root Key 2026 (Asymmetric Signature Standard)",
        "created_at": "2026-01-01T00:00:00Z",
    },
    LEGACY_HMAC_KEY_ID: {
        "key_id": LEGACY_HMAC_KEY_ID,
        "algorithm": "HMAC-SHA256",
        "public_key_hex": None,  # Symmetric key — no public key
        "status": "DEPRECATED_LEGACY",
        "description": "Legacy prototype symmetric HMAC signing key (Backward compatibility only)",
        "created_at": "2025-01-01T00:00:00Z",
    },
    TEST_HMAC_KEY_ID: {
        "key_id": TEST_HMAC_KEY_ID,
        "algorithm": "HMAC-SHA256",
        "public_key_hex": None,
        "status": "TEST_FIXTURE",
        "description": "Automated test fixture symmetric HMAC signing key",
        "created_at": "2025-01-01T00:00:00Z",
    },
}


class CertificateService:
    """
    Cryptographic digital credential issuance, asymmetric verification, and revocation service.
    Primary Algorithm: Ed25519 asymmetric cryptography (private key strictly retained on backend).
    Backward Compatibility: Preserves HMAC-SHA256 signature verification for legacy credentials.
    """

    SECRET_KEY = settings.SECRET_KEY.encode("utf-8")

    @classmethod
    def canonical_json(cls, payload: Dict[str, Any]) -> bytes:
        """Produce deterministic canonical JSON byte representation for signature computation."""
        return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode("utf-8")

    @classmethod
    def compute_ed25519_signature(cls, payload: Dict[str, Any]) -> str:
        """Sign canonical JSON payload using the backend private Ed25519 key."""
        canonical_bytes = cls.canonical_json(payload)
        sig_bytes = _ED25519_PRIVATE_KEY.sign(canonical_bytes)
        return sig_bytes.hex()

    @classmethod
    def compute_hmac_signature(cls, payload: Dict[str, Any]) -> str:
        """Legacy HMAC-SHA256 computation for backward compatibility."""
        canonical_bytes = cls.canonical_json(payload)
        return hmac.new(cls.SECRET_KEY, canonical_bytes, hashlib.sha256).hexdigest()

    @classmethod
    def compute_signature(cls, payload: Dict[str, Any], algorithm: str = "HMAC-SHA256") -> str:
        if algorithm == "Ed25519":
            return cls.compute_ed25519_signature(payload)
        return cls.compute_hmac_signature(payload)

    @classmethod
    def get_public_keys(cls) -> List[Dict[str, Any]]:
        return list(KEY_REGISTRY.values())

    @classmethod
    def get_public_key(cls, key_id: str) -> Optional[Dict[str, Any]]:
        return KEY_REGISTRY.get(key_id)

    @classmethod
    def issue_credential(
        cls,
        db: Session,
        student_ref: str,
        student_name: str,
        institution_id: str,
        institution_name: str,
        programme_id: str,
        programme_name: str,
        issue_date: str,
        completion_date: str,
        apaar_id: Optional[str] = None,
        algorithm: str = "Ed25519",
        issued_by: str = "Institutional Registrar",
    ) -> Certificate:
        cert_id = f"CERT-PRAMAAN-{uuid.uuid4().hex[:12].upper()}"

        # Minimal verifiable claim payload avoiding unnecessary personal data leakage
        payload = {
            "certificate_id": cert_id,
            "student_ref": student_ref,
            "student_name": student_name,
            "institution_id": institution_id,
            "institution_name": institution_name,
            "programme_id": programme_id,
            "programme_name": programme_name,
            "issue_date": issue_date,
            "completion_date": completion_date,
            "credential_type": "AICTE_VERIFIED_COMPLETION",
        }
        if apaar_id:
            payload["apaar_id"] = apaar_id

        if algorithm == "Ed25519":
            sig_hex = cls.compute_ed25519_signature(payload)
            key_id = ACTIVE_KEY_ID
        else:
            sig_hex = cls.compute_hmac_signature(payload)
            key_id = LEGACY_HMAC_KEY_ID

        cert = Certificate(
            certificate_id=cert_id,
            student_ref=student_ref,
            apaar_id=apaar_id or "EXEMPT-OR-UNSPECIFIED",
            student_name=student_name,
            institution_id=institution_id,
            institution_name=institution_name,
            programme_id=programme_id,
            programme_name=programme_name,
            issue_date=issue_date,
            completion_date=completion_date,
            status="VALID",
            signature_algorithm=algorithm,
            signature_hex=sig_hex,
            public_key_id=key_id,
            payload_json=payload,
            created_at=datetime.now(timezone.utc),
        )
        db.add(cert)
        db.commit()
        db.refresh(cert)

        AuditService.log_event(
            db=db,
            entity_type="CERTIFICATE",
            entity_id=cert.certificate_id,
            action="ISSUE_CREDENTIAL",
            performed_by=issued_by,
            details={
                "algorithm": algorithm,
                "public_key_id": key_id,
                "student_ref": student_ref,
                "institution_id": institution_id,
            },
        )
        return cert

    @classmethod
    def revoke_credential(
        cls,
        db: Session,
        certificate_id: str,
        reason: str,
        revoked_by: str,
    ) -> Dict[str, Any]:
        cert = db.query(Certificate).filter(Certificate.certificate_id == certificate_id).first()
        if not cert:
            raise ValueError(f"Certificate {certificate_id} not found.")

        if not reason or not reason.strip() or len(reason.strip()) < 5:
            raise ValueError("A substantive revocation reason of at least 5 characters is mandatory.")

        cert.status = "REVOKED"
        cert.revocation_reason = reason.strip()
        db.commit()
        db.refresh(cert)

        AuditService.log_event(
            db=db,
            entity_type="CERTIFICATE",
            entity_id=cert.certificate_id,
            action="REVOKE_CREDENTIAL",
            performed_by=revoked_by,
            details={"reason": reason.strip(), "institution_id": cert.institution_id},
        )
        return {
            "success": True,
            "certificate_id": cert.certificate_id,
            "status": "REVOKED",
            "revocation_reason": cert.revocation_reason,
            "revoked_by": revoked_by,
        }

    @classmethod
    def verify_certificate(
        cls,
        db: Session,
        certificate_id: str,
        tampered_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        cert = db.query(Certificate).filter(Certificate.certificate_id == certificate_id).first()
        if not cert:
            return {
                "certificate_id": certificate_id,
                "verification_status": "NOT_FOUND",
                "is_authentic": False,
                "signature_valid": False,
                "message": "Certificate record not found in institutional sentinel ledger."
            }

        payload_to_verify = tampered_payload if tampered_payload is not None else cert.payload_json
        canonical_bytes = cls.canonical_json(payload_to_verify)
        algorithm = cert.signature_algorithm

        # Key trust validation
        key_entry = KEY_REGISTRY.get(cert.public_key_id)
        if not key_entry:
            return {
                "certificate_id": cert.certificate_id,
                "student_ref": cert.student_ref,
                "apaar_id": cert.apaar_id,
                "student_name": cert.student_name,
                "institution_name": cert.institution_name,
                "programme_name": cert.programme_name,
                "verification_status": "UNTRUSTED_KEY",
                "is_authentic": False,
                "signature_valid": False,
                "status": cert.status,
                "algorithm": cert.signature_algorithm,
                "public_key_id": cert.public_key_id,
                "message": f"UNTRUSTED SIGNING KEY: Key ID '{cert.public_key_id}' is not in the Sentinel trusted key store.",
                "disclaimer": "DEMO PROTOTYPE ONLY — Key trust validation prevents unrecognized signer spoofing."
            }

        if key_entry.get("status") == "REVOKED":
            return {
                "certificate_id": cert.certificate_id,
                "student_ref": cert.student_ref,
                "apaar_id": cert.apaar_id,
                "student_name": cert.student_name,
                "institution_name": cert.institution_name,
                "programme_name": cert.programme_name,
                "verification_status": "SIGNING_KEY_REVOKED",
                "is_authentic": False,
                "signature_valid": False,
                "status": cert.status,
                "algorithm": cert.signature_algorithm,
                "public_key_id": cert.public_key_id,
                "message": f"SIGNING KEY REVOKED: Key ID '{cert.public_key_id}' has been revoked by institutional authority.",
                "disclaimer": "DEMO PROTOTYPE ONLY — Credential invalidated due to compromised signing key."
            }

        if key_entry.get("algorithm") != algorithm:
            return {
                "certificate_id": cert.certificate_id,
                "student_ref": cert.student_ref,
                "apaar_id": cert.apaar_id,
                "student_name": cert.student_name,
                "institution_name": cert.institution_name,
                "programme_name": cert.programme_name,
                "verification_status": "KEY_ALGORITHM_MISMATCH",
                "is_authentic": False,
                "signature_valid": False,
                "status": cert.status,
                "algorithm": cert.signature_algorithm,
                "public_key_id": cert.public_key_id,
                "message": f"Cryptographic algorithm mismatch: certificate specifies '{algorithm}' but key is '{key_entry.get('algorithm')}'.",
                "disclaimer": "DEMO PROTOTYPE ONLY — Key algorithm mismatch prevents algorithm confusion attacks."
            }

        # Verify signature based on algorithm
        signature_matches = False
        if algorithm == "Ed25519":
            try:
                sig_bytes = bytes.fromhex(cert.signature_hex)
                _ED25519_PUBLIC_KEY.verify(sig_bytes, canonical_bytes)
                signature_matches = True
            except (InvalidSignature, ValueError, TypeError):
                signature_matches = False
        elif algorithm == "HMAC-SHA256":
            expected_sig = cls.compute_hmac_signature(payload_to_verify)
            signature_matches = hmac.compare_digest(cert.signature_hex, expected_sig)
        else:
            return {
                "certificate_id": cert.certificate_id,
                "verification_status": "UNSUPPORTED_ALGORITHM",
                "is_authentic": False,
                "signature_valid": False,
                "status": cert.status,
                "message": f"Unsupported cryptographic signature algorithm: {algorithm}.",
            }

        if not signature_matches:
            return {
                "certificate_id": cert.certificate_id,
                "student_ref": cert.student_ref,
                "apaar_id": cert.apaar_id,
                "student_name": cert.student_name,
                "institution_name": cert.institution_name,
                "programme_name": cert.programme_name,
                "verification_status": "TAMPER_DETECTED",
                "is_authentic": False,
                "signature_valid": False,
                "status": cert.status,
                "algorithm": cert.signature_algorithm,
                "public_key_id": cert.public_key_id,
                "message": "CRYPTOGRAPHIC SIGNATURE MISMATCH: Payload has been modified or corrupted post-issuance.",
                "disclaimer": "DEMO PROTOTYPE ONLY — Mathematical tamper detection prevents forged credentials."
            }

        if cert.status == "REVOKED":
            return {
                "certificate_id": cert.certificate_id,
                "student_ref": cert.student_ref,
                "apaar_id": cert.apaar_id,
                "student_name": cert.student_name,
                "institution_name": cert.institution_name,
                "programme_name": cert.programme_name,
                "verification_status": "REVOKED",
                "is_authentic": False,
                "signature_valid": True,
                "status": "REVOKED",
                "algorithm": cert.signature_algorithm,
                "public_key_id": cert.public_key_id,
                "revocation_reason": cert.revocation_reason or "Institutional administrative revocation",
                "message": f"CERTIFICATE REVOKED: Record signature is mathematically valid, but status is revoked ({cert.revocation_reason}).",
                "disclaimer": "DEMO PROTOTYPE ONLY — Issuer revoked this credential."
            }

        return {
            "certificate_id": cert.certificate_id,
            "student_ref": cert.student_ref,
            "apaar_id": cert.apaar_id,
            "student_name": cert.student_name,
            "institution_id": cert.institution_id,
            "institution_name": cert.institution_name,
            "programme_id": cert.programme_id,
            "programme_name": cert.programme_name,
            "issue_date": cert.issue_date,
            "completion_date": cert.completion_date,
            "verification_status": "VALID",
            "is_authentic": True,
            "signature_valid": True,
            "status": cert.status,
            "algorithm": cert.signature_algorithm,
            "public_key_id": cert.public_key_id,
            "signature_hex": cert.signature_hex,
            "message": "VERIFIED: Cryptographic digital signature is valid and credential record is active.",
            "disclaimer": "DEMO — NOT AN OFFICIAL AICTE OR DIGILOCKER CERTIFICATE. Verification proves key integrity only."
        }
