from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import BinaryIO

import requests
import httpx

from ..credentials import CredentialError, load_api_token
from ..mineru import MinerUResult, _normalize, _quality_check, referenced_figure_names
from ..progress import emit_progress
from .base import ProviderConfig


class MinerUApiError(RuntimeError):
    pass


class _ProgressReader:
    def __init__(self, stream: BinaryIO, total: int) -> None:
        self.stream = stream
        self.total = max(total, 1)
        self.current = 0

    def read(self, size: int = -1) -> bytes:
        data = self.stream.read(size)
        self.current += len(data)
        emit_progress(
            "上传 PDF", 0.12 + 0.16 * min(1.0, self.current / self.total),
            phase="上传 PDF", current=self.current, total=self.total,
            unit="bytes", is_page_progress=False,
        )
        return data

    def __len__(self) -> int:
        return self.total


class MinerUApiProvider:
    def __init__(self, config: ProviderConfig, workspace: Path) -> None:
        self.config = config
        self.workspace = workspace
        self.base_url = (config.base_url or "https://mineru.net/api/v4").rstrip("/")
        try:
            self.token = load_api_token(workspace)
        except CredentialError as exc:
            raise MinerUApiError(str(exc)) from exc
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.token}", "Accept": "*/*"})

    @staticmethod
    def _document_key(pdf: Path) -> str:
        digest = hashlib.sha256()
        with pdf.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _api_json(self, response: requests.Response, action: str) -> dict:
        if response.status_code == 401:
            raise MinerUApiError("MinerU API Token 无效或已过期，请重新配置。")
        if response.status_code == 429:
            raise MinerUApiError("MinerU API 请求过于频繁，请稍后重试。")
        try:
            payload = response.json()
        except ValueError as exc:
            detail = re.sub(r"<[^>]+>", " ", response.text or "")
            detail = re.sub(r"\s+", " ", detail).strip()[:240]
            suffix = f"：{detail}" if detail else ""
            raise MinerUApiError(
                f"{action}失败：服务器未返回有效 JSON（HTTP {response.status_code}）{suffix}"
            ) from exc
        if response.status_code >= 400 or payload.get("code") != 0:
            code = payload.get("code", response.status_code)
            message = str(payload.get("msg") or "未知错误")
            known = {
                "A0202": "Token 错误",
                "A0211": "Token 已过期",
                "-60005": "文件超过 200 MB 限制",
                "-60006": "PDF 超过 600 页限制",
                "-60007": "模型服务暂时不可用",
                "-60009": "任务队列已满",
                "-60018": "今日解析任务额度已用完",
            }
            explanation = known.get(str(code), message)
            raise MinerUApiError(f"{action}失败：{explanation}（错误码 {code}）。")
        return payload

    def _get_with_retry(self, url: str, *, stream: bool = False,
                        authenticated: bool = True) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                client = self.session if authenticated else requests
                response = client.get(url, timeout=(20, 60), stream=stream)
                if response.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                    return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt == 2:
                    break
            time.sleep(1.5 * (attempt + 1))
        raise MinerUApiError(f"网络请求失败：{last_error or 'MinerU API 暂时不可用'}")

    def _submit(self, pdf: Path, document_key: str, max_pages: int | None) -> tuple[str, str]:
        emit_progress("获取安全上传地址", 0.06, phase="申请安全上传地址")
        # The signed-upload service occasionally rejects non-ASCII names even
        # though the source PDF itself is valid.  The original name remains in
        # our output; only the temporary remote object uses this stable name.
        remote_name = f"document-{document_key[:20]}.pdf"
        file_spec: dict[str, object] = {
            "name": remote_name,
            "is_ocr": False,
        }
        if max_pages:
            file_spec["page_ranges"] = f"1-{max_pages}"
        payload = {
            "files": [file_spec],
            "model_version": "vlm",
            "enable_formula": True,
            "enable_table": True,
            "language": "en",
        }
        endpoint = f"{self.base_url}/file-urls/batch"
        api_headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        try:
            # Use the same HTTP stack as the official mineru-open-sdk for task
            # creation.  MinerU's edge gateway has rejected otherwise valid
            # requests from some requests/urllib3 combinations with a plain
            # HTTP 400 before the application can return JSON.
            response = httpx.post(endpoint, headers=api_headers, json=payload, timeout=60.0)
            if response.status_code == 400:
                # Keep a compatibility fallback matching MinerU's smallest
                # official example. Formula and table recognition default to
                # enabled and OCR defaults to disabled on the service.
                minimal_file = {"name": remote_name}
                if max_pages:
                    minimal_file["page_ranges"] = f"1-{max_pages}"
                response = httpx.post(
                    endpoint, headers=api_headers,
                    json={"files": [minimal_file], "model_version": "vlm"},
                    timeout=60.0,
                )
        except (requests.RequestException, httpx.HTTPError) as exc:
            raise MinerUApiError(f"获取上传地址失败：{exc}") from exc
        result = self._api_json(response, "获取上传地址")
        data = result.get("data") or {}
        urls = data.get("file_urls") or []
        batch_id = str(data.get("batch_id") or "")
        if not batch_id or not urls:
            raise MinerUApiError("MinerU API 未返回 batch_id 或上传地址。")
        return batch_id, str(urls[0])

    def _upload(self, pdf: Path, upload_url: str) -> None:
        emit_progress("上传 PDF", 0.10, phase="开始上传 PDF")
        try:
            with pdf.open("rb") as stream:
                reader = _ProgressReader(stream, pdf.stat().st_size)
                response = requests.put(upload_url, data=reader, timeout=(30, 600))
        except requests.RequestException as exc:
            raise MinerUApiError(f"PDF 上传失败：{exc}") from exc
        if response.status_code not in (200, 201, 204):
            raise MinerUApiError(f"PDF 上传失败（HTTP {response.status_code}）。")

    def _poll(self, batch_id: str, deadline: float) -> str:
        state_names = {
            "waiting-file": "等待服务器接收文件",
            "pending": "云端排队中",
            "running": "云端逐页解析",
            "converting": "云端整理输出格式",
        }
        while time.monotonic() < deadline:
            response = self._get_with_retry(f"{self.base_url}/extract-results/batch/{batch_id}")
            payload = self._api_json(response, "查询解析进度")
            results = (payload.get("data") or {}).get("extract_result") or []
            if not results:
                emit_progress("云端排队并逐页解析", 0.31, phase="等待任务进入队列")
                time.sleep(2)
                continue
            item = results[0]
            state = str(item.get("state") or "pending")
            if state == "done":
                url = str(item.get("full_zip_url") or "")
                if not url:
                    raise MinerUApiError("任务已完成，但服务器未返回结果下载地址。")
                return url
            if state == "failed":
                raise MinerUApiError(f"云端解析失败：{item.get('err_msg') or '未知原因'}")
            progress = item.get("extract_progress") or {}
            current = int(progress.get("extracted_pages") or 0)
            total = int(progress.get("total_pages") or 0)
            ratio = min(1.0, current / total) if total else 0.0
            emit_progress(
                "云端排队并逐页解析", 0.30 + 0.52 * ratio,
                phase=state_names.get(state, f"云端状态：{state}"),
                current=current, total=total, document_pages=total,
                is_page_progress=bool(total),
            )
            time.sleep(2 if state == "running" else 3)
        raise MinerUApiError(f"MinerU API 任务超过 {self.config.timeout} 秒仍未完成。")

    def _download(self, url: str, target: Path) -> None:
        emit_progress("下载并解压识别结果", 0.84, phase="下载结果 ZIP")
        # full_zip_url points at a CDN.  Never forward the MinerU bearer token
        # to that different host; the URL itself authorizes this download.
        response = self._get_with_retry(url, stream=True, authenticated=False)
        if response.status_code >= 400:
            raise MinerUApiError(f"下载识别结果失败（HTTP {response.status_code}）。")
        total = int(response.headers.get("Content-Length") or 0)
        current = 0
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as stream:
            for chunk in response.iter_content(1024 * 1024):
                if not chunk:
                    continue
                stream.write(chunk)
                current += len(chunk)
                ratio = min(1.0, current / total) if total else 0.5
                emit_progress(
                    "下载并解压识别结果", 0.84 + 0.07 * ratio,
                    phase="下载结果 ZIP", current=current, total=total,
                    unit="bytes", is_page_progress=False,
                )

    @staticmethod
    def _safe_extract(archive: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        root = destination.resolve()
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                target = (destination / member.filename).resolve()
                if os.path.commonpath((str(root), str(target))) != str(root):
                    raise MinerUApiError("结果 ZIP 包含不安全路径，已停止解压。")
            zipped.extractall(destination)

    def convert(self, pdf: Path, output: Path, *, max_pages: int | None = None) -> MinerUResult:
        document_key = self._document_key(pdf)
        api_root = self.workspace / ".runtime-home" / "api"
        state_dir = api_root / "tasks"
        work_dir = api_root / "work" / document_key[:12]
        state_path = state_dir / f"{document_key[:24]}.json"
        state_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        batch_id = ""
        if state_path.is_file():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if state.get("sha256") == document_key and state.get("uploaded") is True:
                    batch_id = str(state.get("batch_id") or "")
            except (OSError, ValueError):
                batch_id = ""
        if not batch_id:
            batch_id, upload_url = self._submit(pdf, document_key, max_pages)
            state_path.write_text(
                json.dumps({"sha256": document_key, "batch_id": batch_id, "file": pdf.name,
                            "uploaded": False}, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                self._upload(pdf, upload_url)
            except Exception:
                state_path.unlink(missing_ok=True)
                raise
            state_path.write_text(
                json.dumps({"sha256": document_key, "batch_id": batch_id, "file": pdf.name,
                            "uploaded": True}, ensure_ascii=False),
                encoding="utf-8",
            )
        else:
            emit_progress("云端排队并逐页解析", 0.30, phase="继续查询已提交任务")
        result_url = self._poll(batch_id, time.monotonic() + self.config.timeout)
        archive = work_dir / "result.zip"
        extracted = work_dir / "extracted"
        if extracted.exists():
            shutil.rmtree(extracted)
        self._download(result_url, archive)
        self._safe_extract(archive, extracted)
        markdown_files = list(extracted.rglob("full.md")) or list(extracted.rglob("*.md"))
        if not markdown_files:
            raise MinerUApiError("MinerU API 结果中没有 Markdown 文件。")
        source_root = markdown_files[0].parent
        raw = markdown_files[0].read_text(encoding="utf-8")
        normalized = _normalize(raw)
        errors, warnings, formula_count = _quality_check(normalized)
        if errors:
            raise MinerUApiError("API 输出未通过质量检查：" + "; ".join(errors))
        image_target = output / "assets" / "figures"
        image_target.mkdir(parents=True, exist_ok=True)
        references = referenced_figure_names(normalized)
        image_count = 0
        for image_dir in source_root.rglob("images"):
            if not image_dir.is_dir():
                continue
            for image in image_dir.iterdir():
                if image.is_file() and image.name in references and not (image_target / image.name).exists():
                    shutil.copy2(image, image_target / image.name)
                    image_count += 1
        tags = re.findall(r"\\tag\s*\{\s*([^}]+?)\s*\}", normalized)
        diagnostics = api_root / "diagnostics" / output.name
        diagnostics.mkdir(parents=True, exist_ok=True)
        (diagnostics / "api-raw.md").write_text(raw, encoding="utf-8")
        state_path.unlink(missing_ok=True)
        shutil.rmtree(work_dir, ignore_errors=True)
        return MinerUResult(normalized, formula_count, tags, image_count, warnings)
