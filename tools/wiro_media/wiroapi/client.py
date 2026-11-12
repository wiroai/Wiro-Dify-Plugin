"""A small client for the Wiro AI Run API (https://api.wiro.ai/v1).

It covers what the tools need: the model catalog, file uploads, starting a run
and following its task until it ends. Every call goes to fixed Wiro AI hosts.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlparse

import requests

API_URL = "https://api.wiro.ai/v1"
USER_AGENT = "wiro-dify-plugin/0.2.0 (+https://github.com/wiroai/Wiro-Dify-Plugin)"

# Output files are served from Wiro AI's CDN. Nothing else is downloaded.
OUTPUT_HOST_SUFFIX = ".wiro.ai"

TERMINAL_STATUSES = {"task_postprocess_end", "task_cancel"}
REQUEST_TIMEOUT = (10, 60)
UPLOAD_TIMEOUT = (10, 300)
DOWNLOAD_TIMEOUT = (10, 300)
CATALOG_CACHE_SECONDS = 600
UPLOAD_MAX_BYTES = 100 * 1024 * 1024


class WiroError(Exception):
    """A Wiro AI call failed. The message is safe to show to the user."""


class TaskStillRunning(WiroError):
    """The task did not finish within the wait time. It keeps running on Wiro AI."""

    def __init__(self, task: Mapping[str, Any]) -> None:
        super().__init__("The task is still running.")
        self.task = dict(task)


class StillRunning(WiroError):
    """A workflow run or a Studio or agent turn outlived the wait. It keeps running on Wiro AI."""

    def __init__(self, state: Mapping[str, Any]) -> None:
        super().__init__("Still running.")
        self.state = dict(state)


WORKFLOW_FINAL = {"completed", "failed", "stopped", "cancelled"}
REPLY_FINAL = {"agent_end", "agent_error", "agent_cancel"}
TEXT_MAX_BYTES = 1024 * 1024


def poll_interval(elapsed: float) -> float:
    return 2 if elapsed < 15 else 5 if elapsed < 60 else 10


def _error_text(body: Any) -> str:
    if isinstance(body, dict):
        errors = body.get("errors") or []
        messages = [str(item.get("message")) for item in errors if isinstance(item, dict) and item.get("message")]
        if messages:
            return "; ".join(messages)
    return "no details"


class WiroClient:
    def __init__(self, credentials: Mapping[str, Any], session: requests.Session | None = None) -> None:
        self.api_key = str(credentials.get("api_key") or "").strip()
        self.api_secret = str(credentials.get("api_secret") or "").strip()
        if not self.api_key:
            raise WiroError("Enter the API key of your Wiro AI project.")
        self.session = session or requests.Session()

    # -- plumbing -------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"x-api-key": self.api_key, "User-Agent": USER_AGENT, "Accept": "application/json"}
        if self.api_secret:
            nonce = str(int(time.time() * 1000))
            signature = hmac.new(self.api_key.encode(), (self.api_secret + nonce).encode(), hashlib.sha256).hexdigest()
            headers.update({"x-nonce": nonce, "x-signature": signature})
        return headers

    def _post(self, path: str, body: Mapping[str, Any]) -> dict:
        try:
            response = self.session.post(
                f"{API_URL}{path}", json=body, headers=self._headers(), timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            raise WiroError("Could not reach Wiro AI. Check the network and try again.") from exc
        return self._read(response)

    @staticmethod
    def _read(response: requests.Response) -> dict:
        try:
            body = response.json()
        except ValueError as exc:
            raise WiroError(f"Wiro AI answered with HTTP {response.status_code} and no JSON body.") from exc
        if response.status_code >= 400:
            raise WiroError(f"Wiro AI answered with HTTP {response.status_code}: {_error_text(body)}")
        # HTTP 200 is not success on its own: Wiro reports failures as result: false.
        if isinstance(body, dict) and body.get("result") is False:
            raise WiroError(_error_text(body))
        return body

    # -- account --------------------------------------------------------

    def check_credentials(self) -> None:
        """Read one task row. It is free and fails when the key or signature is wrong."""
        try:
            response = self.session.post(
                f"{API_URL}/Task/List",
                json={"start": "0", "limit": "1"},
                headers=self._headers(),
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise WiroError("Could not reach Wiro AI. Check the network and try again.") from exc
        try:
            self._read(response)
        except WiroError as exc:
            raise WiroError(
                "Wiro AI did not accept these credentials. Check the API key, and add the API secret "
                "if your project uses signature authentication."
            ) from exc

    # -- catalog --------------------------------------------------------

    _detail_cache: dict[str, tuple[float, dict]] = {}
    _detail_lock = threading.Lock()

    def list_models(self, category: str | None = None, search: str | None = None, limit: int = 50) -> list[dict]:
        body: dict[str, Any] = {
            "start": "0",
            "limit": str(max(1, min(limit, 200))),
            "hideworkflows": True,
            "summary": True,
            "sort": "relevance",
            "order": "DESC",
        }
        if category:
            body["categories"] = [category]
        if search:
            body["search"] = search
        return list(self._post("/Tool/List", body).get("tool") or [])

    def model_detail(self, model_id: str) -> dict:
        owner, project = split_model_id(model_id)
        key = f"{owner}/{project}"
        now = time.monotonic()
        with self._detail_lock:
            cached = self._detail_cache.get(key)
            if cached and now - cached[0] < CATALOG_CACHE_SECONDS:
                return cached[1]
        body = self._post("/Tool/Detail", {"slugowner": owner, "slugproject": project})
        tools = body.get("tool") or []
        if not tools:
            raise WiroError(f"Wiro AI has no model called {key}. Find model IDs with Search Models.")
        detail = tools[0]
        with self._detail_lock:
            self._detail_cache[key] = (now, detail)
        return detail

    # -- files ----------------------------------------------------------

    def upload(self, filename: str, data: bytes, mime_type: str | None) -> str:
        """Upload a file to the project's Wiro AI storage and return its public URL."""
        if len(data) > UPLOAD_MAX_BYTES:
            raise WiroError(f"{filename} is larger than the 100 MB upload limit.")
        files = {"file": (filename, data, mime_type or "application/octet-stream")}
        try:
            response = self.session.post(
                f"{API_URL}/File/Upload", files=files, headers=self._headers(), timeout=UPLOAD_TIMEOUT
            )
        except requests.RequestException as exc:
            raise WiroError("Could not upload the file to Wiro AI. Check the network and try again.") from exc
        body = self._read(response)
        items = body.get("list") or []
        url = items[0].get("url") if items else None
        if not url:
            raise WiroError(f"Wiro AI accepted {filename} but returned no file URL.")
        return str(url)

    @staticmethod
    def is_output_url(url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and (host == "wiro.ai" or host.endswith(OUTPUT_HOST_SUFFIX))

    def download(self, url: str, max_bytes: int) -> bytes | None:
        """Download an output file from Wiro AI's CDN. Returns None when it is larger than max_bytes."""
        if not self.is_output_url(url):
            raise WiroError("The output file is not on a Wiro AI host, so it was not downloaded.")
        try:
            with self.session.get(
                url, stream=True, timeout=DOWNLOAD_TIMEOUT, headers={"User-Agent": USER_AGENT}
            ) as response:
                response.raise_for_status()
                declared = int(response.headers.get("Content-Length") or 0)
                if declared > max_bytes:
                    return None
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        return None
                    chunks.append(chunk)
                return b"".join(chunks)
        except requests.RequestException as exc:
            raise WiroError("Could not download the output file from Wiro AI.") from exc

    # -- runs -----------------------------------------------------------

    def run(self, model_id: str, parameters: Mapping[str, Any]) -> tuple[str, str]:
        owner, project = split_model_id(model_id)
        body = self._post(f"/Run/{owner}/{project}", parameters)
        taskid, token = body.get("taskid"), body.get("socketaccesstoken")
        if not token:
            raise WiroError(
                f"Wiro AI started task {taskid or '(no id)'} but returned no task token. "
                "Open the task in the Wiro AI dashboard instead of running it again."
            )
        return str(taskid or ""), str(token)

    def task(self, token: str | None = None, taskid: str | None = None) -> dict:
        body: dict[str, str] = {"tasktoken": token} if token else {"taskid": str(taskid or "")}
        tasks = self._post("/Task/Detail", body).get("tasklist") or []
        if not tasks:
            raise WiroError("Wiro AI has no task with this reference in your project.")
        return tasks[0]

    def wait(self, token: str, timeout_seconds: float) -> dict:
        """Poll Task/Detail until the task ends: every 2 s, then 5 s after 15 s, then 10 s after a minute."""
        started = time.monotonic()
        failures = 0
        while True:
            elapsed = time.monotonic() - started
            try:
                current = self.task(token=token)
                failures = 0
                if current.get("status") in TERMINAL_STATUSES:
                    return current
            except WiroError:
                failures += 1
                if failures >= 5:
                    raise
                current = {"socketaccesstoken": token, "status": "unknown"}
            if elapsed >= timeout_seconds:
                raise TaskStillRunning(current)
            interval = 2 if elapsed < 15 else 5 if elapsed < 60 else 10
            time.sleep(min(interval, max(0.5, timeout_seconds - elapsed)))

    # -- multipart and text --------------------------------------------

    def _post_form(self, path: str, data: Mapping[str, Any], files: list) -> dict:
        try:
            response = self.session.post(
                f"{API_URL}{path}", data=dict(data), files=files, headers=self._headers(), timeout=UPLOAD_TIMEOUT
            )
        except requests.RequestException as exc:
            raise WiroError("Could not reach Wiro AI. Check the network and try again.") from exc
        return self._read(response)

    def read_text(self, url: str, max_bytes: int = TEXT_MAX_BYTES) -> str | None:
        data = self.download(url, max_bytes)
        return None if data is None else data.decode("utf-8", "replace")

    def _wait(self, read: Callable[[], dict], done: Callable[[dict], bool], timeout_seconds: float) -> dict:
        started = time.monotonic()
        failures = 0
        state: dict = {}
        while True:
            elapsed = time.monotonic() - started
            try:
                state = read()
                failures = 0
                if done(state):
                    return state
            except WiroError:
                failures += 1
                if failures >= 5:
                    raise
            if elapsed >= timeout_seconds:
                raise StillRunning(state)
            time.sleep(min(poll_interval(elapsed), max(0.5, timeout_seconds - elapsed)))

    # -- workflows ------------------------------------------------------

    def list_workflows(self, limit: int = 200) -> list[dict]:
        body = self._post("/Workflow/List", {"scope": "my", "limit": limit, "sort": "updatetime", "order": "DESC"})
        return list(body.get("workflow") or [])

    def workflow_detail(self, slug: str) -> dict:
        rows = self._post("/Workflow/Detail", {"slug": slug}).get("workflow") or []
        if not rows:
            raise WiroError(f"Wiro AI has no workflow called {slug}.")
        return rows[0]

    def run_workflow(self, slug: str, inputs: Mapping[str, Any]) -> str:
        body: dict[str, Any] = {"slug": slug}
        if inputs:
            body["input"] = dict(inputs)
        token = self._post("/Workflow/Run", body).get("workflowtoken")
        if not token:
            raise WiroError("Wiro AI started the workflow but returned no run token. Check the run on wiro.ai.")
        return str(token)

    def workflow_run(self, token: str) -> dict:
        return self._post("/Workflow/RunDetail", {"workflowtoken": token})

    def wait_workflow(self, token: str, timeout_seconds: float) -> dict:
        return self._wait(
            lambda: self.workflow_run(token),
            lambda body: (body.get("workflowrun") or {}).get("status") in WORKFLOW_FINAL,
            timeout_seconds,
        )

    # -- Studio and agents ---------------------------------------------

    @staticmethod
    def _attachments(field: str, files: list[tuple[str, bytes, str]]) -> list:
        return [(field, (name, data, mime)) for name, data, mime in files]

    def studio_send(self, message: str, session: str, files: list | None = None, model: str | None = None) -> dict:
        data: dict[str, Any] = {"message": message, "sessionkey": session}
        if model:
            data["model"] = model
        if files:
            return self._post_form("/Studio/Message/SendForm", data, self._attachments("attachments", files))
        return self._post("/Studio/Message/Send", data)

    def studio_detail(self, agenttoken: str, session: str) -> dict:
        return self._post("/Studio/Message/Detail", {"agenttoken": agenttoken, "sessionkey": session}).get("data") or {}

    def studio_tasks(self, limit: int = 50) -> list[dict]:
        return list(self._post("/Studio/Tasks", {"limit": limit}).get("tasks") or [])

    def my_agents(self) -> list[dict]:
        return list(self._post("/UserAgent/MyAgents", {}).get("useragents") or [])

    def agent_send(self, agent: str, message: str, session: str, files: list | None = None) -> dict:
        data = {"useragentguid": agent, "message": message, "sessionkey": session}
        if files:
            return self._post_form("/UserAgent/Message/Send", data, self._attachments("attachments[]", files))
        return self._post("/UserAgent/Message/Send", data)

    def agent_detail(self, agenttoken: str, session: str) -> dict:
        body = self._post("/UserAgent/Message/Detail", {"agenttoken": agenttoken, "sessionkey": session})
        return body.get("data") or {}

    def wait_reply(self, read: Callable[[], dict], timeout_seconds: float) -> dict:
        return self._wait(read, lambda data: data.get("status") in REPLY_FINAL, timeout_seconds)


def split_model_id(model_id: str) -> tuple[str, str]:
    value = (model_id or "").strip().strip("/")
    owner, _, project = value.partition("/")
    if not owner or not project or "/" in project:
        raise WiroError(f'"{model_id}" is not a model ID. Use owner/model, for example google/nano-banana-2.')
    return owner, project
