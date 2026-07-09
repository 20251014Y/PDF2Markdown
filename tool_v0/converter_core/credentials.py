from __future__ import annotations

import argparse
import ctypes
import getpass
import os
from ctypes import wintypes
from pathlib import Path


class CredentialError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _windows_crypto() -> tuple[object, object]:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_pointer = ctypes.POINTER(_DataBlob)
    crypt32.CryptProtectData.argtypes = [
        blob_pointer, wintypes.LPCWSTR, blob_pointer, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD, blob_pointer,
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        blob_pointer, ctypes.c_void_p, blob_pointer, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD, blob_pointer,
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _blob(data: bytes) -> tuple[_DataBlob, object]:
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise CredentialError("MinerU API 凭据加密目前仅支持 Windows。")
    source, source_buffer = _blob(data)
    output = _DataBlob()
    crypt32, kernel32 = _windows_crypto()
    if not crypt32.CryptProtectData(
        ctypes.byref(source), "PDF2Markdown MinerU API Token", None, None, None,
        0x01, ctypes.byref(output)
    ):
        raise CredentialError("Windows 无法加密 MinerU API Token。")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)
        del source_buffer


def _unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise CredentialError("MinerU API 凭据解密目前仅支持 Windows。")
    source, source_buffer = _blob(data)
    output = _DataBlob()
    crypt32, kernel32 = _windows_crypto()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0x01, ctypes.byref(output)
    ):
        raise CredentialError("Token 无法由当前 Windows 用户解密，请重新配置。")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)
        del source_buffer


def credential_path(workspace: Path) -> Path:
    return workspace / ".runtime-home" / "api" / "credentials.bin"


def bootstrap_path(workspace: Path) -> Path:
    return workspace / ".runtime-home" / "api" / "token-bootstrap.txt"


def save_api_token(workspace: Path, token: str) -> None:
    token = token.strip()
    if not token:
        raise CredentialError("Token 不能为空。")
    path = credential_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_protect(token.encode("utf-8")))


def load_api_token(workspace: Path) -> str:
    environment_token = os.environ.get("MINERU_API_TOKEN", "").strip()
    if environment_token:
        return environment_token
    path = credential_path(workspace)
    if not path.is_file():
        raise CredentialError("尚未配置 MinerU API Token。")
    token = _unprotect(path.read_bytes()).decode("utf-8").strip()
    if not token:
        raise CredentialError("保存的 MinerU API Token 为空，请重新配置。")
    return token


def ensure_api_token(workspace: Path, *, replace: bool = False) -> None:
    if not replace:
        try:
            load_api_token(workspace)
            print("MinerU API Token 已配置。")
            return
        except CredentialError:
            pass
    print("首次使用 MinerU API，需要输入一次 Token。输入内容不会显示。")
    token = getpass.getpass("MinerU API Token: ").strip()
    save_api_token(workspace, token)
    print("Token 已使用 Windows 当前用户加密并永久保存。")


def import_bootstrap_token(workspace: Path) -> None:
    """Import a one-time token under the interactive user's DPAPI context."""
    path = bootstrap_path(workspace)
    if not path.is_file():
        return
    token = path.read_text(encoding="utf-8").strip()
    try:
        save_api_token(workspace, token)
    finally:
        try:
            size = path.stat().st_size
            path.write_bytes(b"0" * size)
        finally:
            path.unlink(missing_ok=True)
    print("MinerU API Token 已自动迁移到当前 Windows 用户的加密凭据。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="配置 MinerU API Token")
    parser.add_argument("action", choices=("ensure", "replace", "bootstrap", "from-env"), nargs="?", default="ensure")
    args = parser.parse_args(argv)
    workspace = Path(__file__).resolve().parent.parent
    try:
        if args.action == "bootstrap":
            import_bootstrap_token(workspace)
        elif args.action == "from-env":
            token = os.environ.pop("PDF2MD_BOOTSTRAP_TOKEN", "")
            save_api_token(workspace, token)
            print("MinerU API Token 已加密保存。")
        else:
            ensure_api_token(workspace, replace=args.action == "replace")
    except (CredentialError, EOFError, KeyboardInterrupt) as exc:
        print(f"Token 配置失败：{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
