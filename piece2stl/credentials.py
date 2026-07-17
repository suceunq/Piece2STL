from __future__ import annotations

"""Stockage des secrets dans le Gestionnaire d'identifiants Windows."""

import ctypes
from ctypes import wintypes
import sys


TARGET_NAME = "Piece2STL/MeshyAPI"
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def save_meshy_key(api_key: str) -> bool:
    if sys.platform != "win32" or not api_key.strip():
        return False
    value = api_key.strip().encode("utf-16-le")
    blob = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    credential = CREDENTIALW()
    credential.Type = CRED_TYPE_GENERIC
    credential.TargetName = TARGET_NAME
    credential.CredentialBlobSize = len(value)
    credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = "Meshy API"
    return bool(ctypes.windll.advapi32.CredWriteW(ctypes.byref(credential), 0))


def load_meshy_key() -> str:
    if sys.platform != "win32":
        return ""
    pointer = ctypes.POINTER(CREDENTIALW)()
    if not ctypes.windll.advapi32.CredReadW(
        TARGET_NAME, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)
    ):
        return ""
    try:
        credential = pointer.contents
        raw = ctypes.string_at(
            credential.CredentialBlob, credential.CredentialBlobSize
        )
        return raw.decode("utf-16-le")
    finally:
        ctypes.windll.advapi32.CredFree(pointer)


def delete_meshy_key() -> None:
    if sys.platform == "win32":
        ctypes.windll.advapi32.CredDeleteW(TARGET_NAME, CRED_TYPE_GENERIC, 0)
