#!/usr/bin/env python3
"""Static acceptance checks for both generated metal n8n exports."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "[FLUX-KLEIN-v2] Mockup Generator - Tezgah.json"
LOCAL = ROOT / "local-prod" / "workflow" / "metal-local-prod.json"
ROLLBACK = ROOT / "local-prod" / "workflow" / "metal-cloud-rollback-frozen.json"

LOCKED_JS = (
    "Parse_JSON",
    "Override_Metal_Prompts_r30",
    "Apply_r32_Surface_Shadow_Gates",
    "Build_Metal_Master_Req",
    "Build_Metal_HighFill_Master_Req",
    "Build_Fal_Req",
)
INFERENCE = (
    "HTTP_Fal_Flux_Edit",
    "HTTP_Metal_Master",
    "HTTP_Metal_HighFill_Master",
)
REMOVED_CLASSIFIERS = (
    "Metal_Prepare_Classify",
    "HTTP_Classify_Metal",
    "Metal_Build_Item",
    "MetalRev_Prepare_Classify",
    "HTTP_Classify_MetalRev",
    "MetalRev_Build_Item",
)
DRIVE_ENV_KEYS = (
    "DRIVE_METAL_UNPRINTED_INPUT_ID",
    "DRIVE_METAL_PRINTED_INPUT_ID",
    "DRIVE_METAL_REVISION_UNPRINTED_INPUT_ID",
    "DRIVE_METAL_REVISION_PRINTED_INPUT_ID",
    "DRIVE_METAL_OUTPUT_ID",
    "DRIVE_METAL_DONE_ID",
    "DRIVE_METAL_REVISION_OUTPUT_ID",
    "DRIVE_METAL_REVISION_DONE_ID",
)


def fail(message: str) -> None:
    raise AssertionError(message)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"{path.name}: invalid JSON: {exc}")
    if not isinstance(value, dict):
        fail(f"{path.name}: root must be an object")
    return value


def nodes_by_name(workflow: dict, label: str) -> dict[str, dict]:
    nodes = workflow.get("nodes") or []
    names = [node.get("name") for node in nodes]
    ids = [node.get("id") for node in nodes]
    if len(names) != len(set(names)):
        fail(f"{label}: duplicate node names")
    if len(ids) != len(set(ids)):
        fail(f"{label}: duplicate node IDs")
    return {node["name"]: node for node in nodes}


def validate_connections(workflow: dict, names: set[str], label: str) -> None:
    for source, typed in workflow.get("connections", {}).items():
        if source not in names:
            fail(f"{label}: connection source does not exist: {source}")
        for groups in typed.values():
            if not isinstance(groups, list):
                fail(f"{label}: malformed connection groups at {source}")
            for group in groups:
                for edge in group:
                    if edge.get("node") not in names:
                        fail(f"{label}: {source} targets missing node {edge.get('node')}")


def targets(workflow: dict, source: str, output: int = 0) -> list[str]:
    groups = workflow.get("connections", {}).get(source, {}).get("main", [])
    if output >= len(groups):
        return []
    return [edge["node"] for edge in groups[output]]


def compile_code_nodes(workflow: dict, label: str) -> None:
    code = [
        {"name": node["name"], "source": node.get("parameters", {}).get("jsCode", "")}
        for node in workflow["nodes"]
        if node.get("type") == "n8n-nodes-base.code"
    ]
    js = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
const nodes = JSON.parse(fs.readFileSync(0, 'utf8'));
for (const node of nodes) {
  try { new AsyncFunction(node.source); }
  catch (error) { console.error(node.name + ': ' + error.message); process.exitCode = 1; }
}
"""
    result = subprocess.run(
        ["node", "-e", js],
        input=json.dumps(code, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if result.returncode:
        fail(f"{label}: Code node syntax failed:\n{result.stderr.strip()}")


def validate_common(workflow: dict, source: dict, label: str) -> dict[str, dict]:
    if workflow.get("active") is not False:
        fail(f"{label}: import must remain active:false")
    nodes = nodes_by_name(workflow, label)
    validate_connections(workflow, set(nodes), label)
    compile_code_nodes(workflow, label)

    for name in REMOVED_CLASSIFIERS:
        if name in nodes:
            fail(f"{label}: classifier node was not removed: {name}")
    for required in (
        "Manual_Trigger",
        "Schedule_Every_5_Minutes",
        "Map_Categories",
        "Stamp_Files",
        "Build_Metal_Item",
        "Search_Staging_Folder",
        "Validate_Staged_Files",
        "Commit_Staging_Folder",
        "Validate_Source_Unchanged",
    ):
        if required not in nodes:
            fail(f"{label}: missing required node {required}")

    if targets(workflow, "Loop_Mockups", 0) != ["Search_Staged_Mockup"]:
        fail(f"{label}: idempotency lookup must run before scene inference")
    if targets(workflow, "If_Staged_Mockup_Exists", 0) != ["Skip_Existing_Staged_Mockup"]:
        fail(f"{label}: existing staged scene is not skipped")
    if targets(workflow, "If_Staged_Mockup_Exists", 1) != ["Build_Fal_Req"]:
        fail(f"{label}: only a missing staged scene may enter inference")
    if targets(workflow, "Strip_Metadata", 0) != ["GDrive_Upload_Mockups"]:
        fail(f"{label}: newly rendered scene does not upload directly")

    interval = nodes["Schedule_Every_5_Minutes"]["parameters"]["rule"]["interval"]
    if interval != [{"field": "minutes", "minutesInterval": 5}]:
        fail(f"{label}: schedule is not exactly every five minutes")

    map_js = nodes["Map_Categories"]["parameters"]["jsCode"]
    if map_js.count("kategori_adi:") != 4:
        fail(f"{label}: Map_Categories must contain exactly four entries")
    for env_key in DRIVE_ENV_KEYS:
        if env_key not in map_js:
            fail(f"{label}: missing Drive environment key {env_key}")
    for marker in ("Metal Baskısız", "Metal Baskılı", "Metal Revizyon Baskısız", "Metal Revizyon Baskılı"):
        if marker not in map_js:
            fail(f"{label}: missing explicit mapping {marker}")

    stamp_js = nodes["Stamp_Files"]["parameters"]["jsCode"]
    for marker in ("is_printed: category.is_printed === true", "output.sort", "createdTime", "md5Checksum", "modifiedTime"):
        if marker not in stamp_js:
            fail(f"{label}: Stamp_Files invariant missing: {marker}")

    source_nodes = nodes_by_name(source, "source")
    for name in LOCKED_JS:
        actual = nodes[name]["parameters"]["jsCode"]
        expected = source_nodes[name]["parameters"]["jsCode"]
        if actual != expected:
            fail(f"{label}: locked prompt/seed/size Code node changed: {name} ({sha(expected)} -> {sha(actual)})")

    for name in INFERENCE:
        if nodes[name]["parameters"].get("jsonBody") != source_nodes[name]["parameters"].get("jsonBody"):
            fail(f"{label}: request body changed at {name}")

    for node in workflow["nodes"]:
        parameters = node.get("parameters", {})
        is_drive = node.get("type") == "n8n-nodes-base.googleDrive" or parameters.get("nodeCredentialType") == "googleDriveOAuth2Api"
        if is_drive:
            credential = node.get("credentials", {}).get("googleDriveOAuth2Api", {})
            if credential != {"id": "LOCAL_GOOGLE_DRIVE_CREDENTIAL_ID", "name": "LOCAL PROD Google Drive"}:
                fail(f"{label}: {node['name']} is missing the secret-free LOCAL PROD Drive credential stub")
    serialized = json.dumps(workflow.get("nodes", []), ensure_ascii=False)
    for source_credential_id in ("tLpr3a8NYgzBnvoI", "n0D1ap0E9vZC9j1J", "xZGCYipnEtSRgld0"):
        if source_credential_id in serialized:
            fail(f"{label}: source instance credential ID remains: {source_credential_id}")
    if "HTTP Request" in nodes or "If_Is_Oldest_Running" in nodes:
        fail(f"{label}: hosted self-dedup nodes remain")
    return nodes


def main() -> int:
    source = load(SOURCE)
    local = load(LOCAL)
    rollback = load(ROLLBACK)
    local_nodes = validate_common(local, source, "local")
    rollback_nodes = validate_common(rollback, source, "rollback")

    local_text = LOCAL.read_text(encoding="utf-8").lower()
    for banned in ("fal.run", "api.openai.com", ".run.app", "n8n-662323208364", "x-n8n-api-key", "x-auth-token", "eyj"):
        if banned in local_text:
            fail(f"local: forbidden cloud endpoint/token marker remains: {banned}")
    for name in INFERENCE:
        node = local_nodes[name]
        if node["parameters"].get("url") != "http://gateway:8787/fal-ai/flux-2/klein/9b/base/edit":
            fail(f"local: {name} does not target the internal gateway")
        if node["parameters"].get("options", {}).get("timeout", 0) < 7_200_000:
            fail(f"local: {name} timeout is below two hours")
        if node.get("credentials"):
            fail(f"local: internal gateway node {name} must not require credentials")
    for name in ("HTTP_Rasterize_PDF", "HTTP_Rasterize_Metal_HighFill"):
        if local_nodes[name]["parameters"].get("url") != "http://pdf-raster:8080/":
            fail(f"local: {name} does not target local pdf-raster")

    rollback_text = ROLLBACK.read_text(encoding="utf-8").lower()
    if "api.openai.com" in rollback_text or "n8n-662323208364" in rollback_text or "x-auth-token" in rollback_text or "eyj" in rollback_text:
        fail("rollback: classifier, hosted n8n, or embedded token marker remains")
    if rollback_text.count("https://fal.run/fal-ai/flux-2/klein/9b/base/edit") != 3:
        fail("rollback: expected exactly three FAL inference endpoints")
    if rollback_text.count("https://pdf-to-img-662323208364.europe-west1.run.app") != 2:
        fail("rollback: expected exactly two Cloud Run PDF endpoints")
    for name in INFERENCE:
        if rollback_nodes[name]["parameters"].get("authentication") != "genericCredentialType":
            fail(f"rollback: {name} must expose a credential stub without embedding a secret")
        if rollback_nodes[name].get("credentials", {}).get("httpHeaderAuth") != {"id": "ROLLBACK_FAL_CREDENTIAL_ID", "name": "FROZEN ROLLBACK FAL"}:
            fail(f"rollback: {name} has the wrong FAL credential stub")
    for name in ("HTTP_Rasterize_PDF", "HTTP_Rasterize_Metal_HighFill"):
        if rollback_nodes[name].get("credentials", {}).get("httpHeaderAuth") != {"id": "ROLLBACK_PDF_CREDENTIAL_ID", "name": "FROZEN ROLLBACK PDF Raster"}:
            fail(f"rollback: {name} has the wrong PDF credential stub")

    for label, workflow in (("local", local), ("rollback", rollback)):
        names = {node["name"] for node in workflow["nodes"]}
        reachable = set()
        stack = ["Manual_Trigger", "Schedule_Every_5_Minutes"]
        while stack:
            name = stack.pop()
            if name in reachable:
                continue
            reachable.add(name)
            for groups in workflow.get("connections", {}).get(name, {}).values():
                for group in groups:
                    stack.extend(edge["node"] for edge in group)
        if reachable != names:
            fail(f"{label}: unreachable nodes: {sorted(names - reachable)}")

    print("OK: local and frozen rollback metal workflows passed all static checks.")
    for name in LOCKED_JS:
        source_node = next(node for node in source["nodes"] if node["name"] == name)
        print(f"  {name}: {sha(source_node['parameters']['jsCode'])}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
