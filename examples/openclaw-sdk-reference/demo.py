"""Standalone AgentSphere + official OpenClaw example. See README.md.

No dependency on demo-studio modules. No credentials are embedded or printed.
"""
import argparse
import importlib.metadata
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path


EXPECTED = {
    "e2b": "2.42.0",
    "e2b-code-interpreter": "2.9.1",
    "agentsphere-e2b-patch": "0.2.0",
}


def load_sdk():
    for package, expected in EXPECTED.items():
        actual = importlib.metadata.version(package)
        if actual != expected:
            raise RuntimeError(f"{package}: expected {expected}, installed {actual}")
    # Import the Huawei documentation's patch BEFORE importing E2B.
    import agentsphere_e2b_patch  # noqa: F401
    from e2b import Sandbox, Template
    if not getattr(Sandbox.__init__, "_agentsphere_e2b_patched", False):
        raise RuntimeError("AgentSphere patch was not loaded")
    return Sandbox, Template


def required_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Set environment variable {name}; see README.md")
    return value


def https_url(value, label):
    from urllib.parse import urlsplit
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise ValueError(f"{label} must be an HTTPS origin, e.g. https://host")
    return value.rstrip("/")


def safe_text(value):
    text = str(value)
    # Exceptions may include request details. Mask known credentials and token fields.
    for name, secret in os.environ.items():
        if secret and any(k in name.upper() for k in ("KEY", "TOKEN", "PASSWORD")):
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"e2b_[A-Za-z0-9]+", "[REDACTED]", text)
    text = re.sub(
        r'(?i)((?:envdAccessToken|trafficAccessToken|x-access-token|'
        r'e2b-traffic-access-token|X-API-Key)[\"\s:=]+)[^\s,\"}]+',
        r"\1[REDACTED]", text,
    )
    return text


def require_success(response, operation):
    status = int(response.status_code)
    print(f"{operation}: HTTP {status}", flush=True)
    if not 200 <= status < 300:
        # Do not dump raw response objects containing access tokens.
        raise RuntimeError(f"{operation} failed: HTTP {status}; "
                           + safe_text(response.content.decode(errors="replace")))


def create_and_build(client, Template, options, gateway_id, image, wait_seconds, record):
    from e2b.api.client.api.templates import (
        post_v3_templates,
        post_v_2_templates_template_id_builds_build_id,
    )
    from e2b.api.client.models import TemplateBuildRequestV3, TemplateBuildStartV2
    from e2b.template.types import BuildInfo

    name = "official-openclaw-sdk-" + uuid.uuid4().hex[:8]
    body = TemplateBuildRequestV3(name=name, cpu_count=2, memory_mb=8192)
    # Huawei fields use the generated model's additional properties.
    body["gatewayID"] = gateway_id
    body["arch"] = "x86_64"
    response = post_v3_templates.sync_detailed(client=client, body=body)
    require_success(response, "POST /v3/templates")
    data = json.loads(response.content)
    template_id, build_id = data["templateID"], data["buildID"]
    template_ref = template_id + ":" + build_id
    record.update(template_ref=template_ref, template_created=True)
    print(f"Template ID: {template_id}\nBuild ID: {build_id}", flush=True)

    payload = {
        "fromImage": image,
        "steps": [],
        # Check injected envd, NOT OpenClaw business readiness.
        "readyCmd": "curl -fsS --max-time 5 http://127.0.0.1:49983/health >/dev/null",
        "networkConfiguration": {"networkMode": "public"},
        "invoke": {"protocol": "HTTP", "port": 49983},
        "storageConfig": {},
    }
    response = post_v_2_templates_template_id_builds_build_id.sync_detailed(
        template_id, build_id, client=client,
        body=TemplateBuildStartV2.from_dict(payload),
    )
    require_success(response, "POST /v2/templates/{templateID}/builds/{buildID}")

    info = BuildInfo(template_id=template_id, build_id=build_id,
                     name=name, alias=name, tags=[])
    deadline = time.monotonic() + wait_seconds
    seen = set()
    while time.monotonic() < deadline:
        # Public SDK method supplies structured Build logs.
        result = Template.get_build_status(info, **options)
        for entry in result.log_entries:
            line = f"{entry.timestamp} [{entry.level}] {entry.message}"
            if line not in seen:
                seen.add(line)
                print(safe_text(line), flush=True)
        # Preserve Huawei-specific fields/status via the SDK authenticated client.
        detail = client.get_httpx_client().get(
            f"/templates/{template_id}/builds/{build_id}")
        detail.raise_for_status()
        status = str(detail.json().get("status", "")).lower()
        print(f"Build status: {status}", flush=True)
        if status == "ready":
            return template_ref
        if status in ("error", "failed", "cancelled"):
            raise RuntimeError(f"Build {build_id} ended with {status}; see logs above")
        time.sleep(min(20, max(0, deadline - time.monotonic())))
    raise TimeoutError(f"Build not ready within {wait_seconds}s; "
                       f"template retained: {template_ref}")


def exercise_sandbox(sb, options, record, timeout):
    def run(label, code, user="root"):
        started = time.perf_counter()
        result = sb.commands.run(code, user=user, cwd="/app",
                                 timeout=90, request_timeout=110)
        row = dict(case=label, user=user, command=code,
                   elapsed_s=round(time.perf_counter() - started, 3),
                   exit_code=result.exit_code, stdout=safe_text(result.stdout),
                   stderr=safe_text(result.stderr))
        row["status"] = "PASS" if result.exit_code == 0 else "FAIL"
        record["cases"].append(row)
        print(json.dumps(row, ensure_ascii=False, indent=2), flush=True)
        if result.exit_code != 0:
            raise RuntimeError(f"{label}: exit code {result.exit_code}")

    run("commands_run_root", "echo official-openclaw-sdk-ok; id; pwd; node --version")
    original_id = sb.sandbox_id
    started = time.perf_counter()
    # Instance connect retains the metadata returned by create. No recreation.
    sb = sb.connect(timeout=timeout, **options)
    if sb.sandbox_id != original_id:
        raise RuntimeError("connect returned a different sandbox")
    row = dict(case="connect_running_sandbox", status="PASS", sandbox_id=original_id,
               elapsed_s=round(time.perf_counter() - started, 3))
    record["cases"].append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)
    run("commands_run_after_connect", "echo official-openclaw-after-connect-ok; id")
    run("official_openclaw_version", "node /app/openclaw.mjs --version")
    run("commands_run_node_user",
        "echo official-openclaw-node-user-ok; id; node /app/openclaw.mjs --version",
        user="node")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Check installed SDK versions only")
    mode.add_argument("--template-ref", help="Existing ready templateID:buildID")
    mode.add_argument("--build", action="store_true", help="Create a template and build first")
    parser.add_argument("--timeout", type=int, default=3600, help="Sandbox lifetime seconds")
    parser.add_argument("--build-wait", type=int, default=2400, help="Max Build wait seconds")
    parser.add_argument("--report", type=Path, help="Write a credential-free JSON result")
    args = parser.parse_args()
    if args.timeout <= 0 or args.build_wait <= 0:
        parser.error("timeout and build-wait must be positive")
    record = {"status": "FAIL", "sdk": EXPECTED, "cases": []}
    client = None
    try:
        Sandbox, Template = load_sdk()
        if args.check:
            print(json.dumps({"versions": EXPECTED, "patch_loaded": True}, indent=2))
            return 0
        from e2b.api.client_sync import get_api_client
        from e2b.connection_config import ConnectionConfig
        api_url = https_url(os.environ.get("AGENTSPHERE_API_URL",
            "https://agentsandbox.cn-southwest-2.myhuaweicloud.com"), "API URL")
        gateway_url = https_url(required_env("AGENTSPHERE_GATEWAY_URL"), "Gateway URL")
        options = {"api_key": required_env("E2B_API_KEY"), "api_url": api_url,
                   "request_timeout": 45}
        sandbox_options = {**options, "sandbox_url": gateway_url,
                           "headers": {"X-API-Key": options["api_key"]}}
        template_ref = args.template_ref
        if args.build:
            gateway_id = required_env("AGENTSPHERE_GATEWAY_ID")
            image = required_env("AGENTSPHERE_IMAGE")
            client = get_api_client(ConnectionConfig(**options))
            template_ref = create_and_build(client, Template, options, gateway_id,
                                           image, args.build_wait, record)
        else:
            parts = template_ref.split(":")
            if len(parts) != 2 or not all(parts):
                raise ValueError("--template-ref must be templateID:buildID")
        record.update(template_ref=template_ref, api_url=api_url, gateway_url=gateway_url)
        started = time.perf_counter()
        sb = Sandbox.create(template_ref, timeout=args.timeout,
                            lifecycle={"on_timeout": "kill"},
                            metadata={"example": "official-openclaw-sdk"},
                            **sandbox_options)
        record["sandbox_id"] = sb.sandbox_id
        record["cases"].append(dict(case="create_sandbox", status="PASS",
                                    elapsed_s=round(time.perf_counter() - started, 3)))
        print(f"Sandbox ID: {sb.sandbox_id}", flush=True)
        exercise_sandbox(sb, sandbox_options, record, args.timeout)
        record["status"] = "PASS"
        print("PASS: create -> commands.run -> connect same running sandbox -> commands.run")
        return 0
    except Exception as exc:
        record["error"] = safe_text(f"{type(exc).__name__}: {exc}")
        print(record["error"], file=sys.stderr, flush=True)
        return 1
    finally:
        if client is not None:
            client.get_httpx_client().close()
        if not args.check:
            if record.get("template_created"):
                print(f"Template retained: {record['template_ref']}", flush=True)
            if record.get("sandbox_id"):
                print(f"Sandbox retained: {record['sandbox_id']}; "
                      f"timeout={args.timeout}s, on_timeout=kill", flush=True)
            if args.report:
                args.report.write_text(json.dumps(record, ensure_ascii=False, indent=2),
                                       encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
