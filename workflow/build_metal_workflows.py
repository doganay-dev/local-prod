#!/usr/bin/env python3
"""Build isolated metal-only n8n exports from the r39 source workflow.

The source export is read-only.  The generated LOCAL PROD workflow targets the
Compose-only gateway/pdf-raster services.  The frozen cloud rollback workflow
uses the same four explicit Drive inputs and the same prompt/seed/size logic,
but points the three metal inference calls back to FAL.
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "[FLUX-KLEIN-v2] Mockup Generator - Tezgah.json"
OUT_DIR = ROOT / "local-prod" / "workflow"
LOCAL_OUT = OUT_DIR / "metal-local-prod.json"
ROLLBACK_OUT = OUT_DIR / "metal-cloud-rollback-frozen.json"

GATEWAY_URL = "http://gateway:8787/fal-ai/flux-2/klein/9b/base/edit"
LOCAL_PDF_URL = "http://pdf-raster:8080/"
FAL_URL = "https://fal.run/fal-ai/flux-2/klein/9b/base/edit"
CLOUD_PDF_URL = "https://pdf-to-img-662323208364.europe-west1.run.app"

METAL_INFERENCE_NODES = {
    "HTTP_Fal_Flux_Edit",
    "HTTP_Metal_Master",
    "HTTP_Metal_HighFill_Master",
}
DRIVE_CREDENTIAL = {
    "googleDriveOAuth2Api": {
        "id": "LOCAL_GOOGLE_DRIVE_CREDENTIAL_ID",
        "name": "LOCAL PROD Google Drive",
    }
}
FAL_CREDENTIAL = {
    "httpHeaderAuth": {
        "id": "ROLLBACK_FAL_CREDENTIAL_ID",
        "name": "FROZEN ROLLBACK FAL",
    }
}
PDF_CREDENTIAL = {
    "httpHeaderAuth": {
        "id": "ROLLBACK_PDF_CREDENTIAL_ID",
        "name": "FROZEN ROLLBACK PDF Raster",
    }
}
PROMPT_LOCK_NODES = {
    "Parse_JSON",
    "Override_Metal_Prompts_r30",
    "Apply_r32_Surface_Shadow_Gates",
    "Build_Metal_Master_Req",
    "Build_Metal_HighFill_Master_Req",
    "Build_Fal_Req",
}

KEEP_SOURCE_NODES = {
    "Loop_Files",
    "GDrive_Download",
    "GDrive_Upload_Mockups",
    "GDrive_Move_Original",
    "Search_Files",
    "Parse_JSON",
    "Loop_Mockups",
    "Build_Fal_Req",
    "HTTP_Fal_Flux_Edit",
    "Fal_Response_To_URL",
    "HTTP_Download_Fal_Result",
    "If_Has_Prompts",
    "Done",
    "Strip_Metadata",
    "Limit",
    "If_Is_PDF",
    "HTTP_Rasterize_PDF",
    "If_Metal_Needs_Master",
    "Build_Metal_Master_Req",
    "HTTP_Metal_Master",
    "Metal_Master_URL_Metadata",
    "HTTP_Download_Metal_Master",
    "Override_Metal_Prompts_r30",
    "Apply_r32_Surface_Shadow_Gates",
    "Prepare_Metal_HighFill_Source",
    "If_Metal_HighFill_Is_PDF",
    "HTTP_Rasterize_Metal_HighFill",
    "Build_Metal_HighFill_Master_Req",
    "HTTP_Metal_HighFill_Master",
    "Capture_HighFill_And_Restore_Standard_Input",
}


MAP_CATEGORIES_JS = r"""// LOCAL PROD: folder IDs are supplied only through the n8n container environment.
// Four distinct input folders remove the GPT printed/unprinted classifier entirely.
function requiredEnv(name) {
  const value = String($env[name] || '').trim();
  if (!value || value.startsWith('__')) throw new Error('Missing required environment variable: ' + name);
  return value;
}

const normalDone = requiredEnv('DRIVE_METAL_DONE_ID');
const normalOutput = requiredEnv('DRIVE_METAL_OUTPUT_ID');
const revisionDone = requiredEnv('DRIVE_METAL_REVISION_DONE_ID');
const revisionOutput = requiredEnv('DRIVE_METAL_REVISION_OUTPUT_ID');

const categories = [
  {
    kategori_adi: 'Metal Baskısız',
    yapilacaklar_ID: requiredEnv('DRIVE_METAL_UNPRINTED_INPUT_ID'),
    yapildi_ID: normalDone,
    mockuplar_ID: normalOutput,
    product_direction: '',
    product_type: 'metal wall art',
    is_printed: false
  },
  {
    kategori_adi: 'Metal Baskılı',
    yapilacaklar_ID: requiredEnv('DRIVE_METAL_PRINTED_INPUT_ID'),
    yapildi_ID: normalDone,
    mockuplar_ID: normalOutput,
    product_direction: '',
    product_type: 'metal wall art',
    is_printed: true
  },
  {
    kategori_adi: 'Metal Revizyon Baskısız',
    yapilacaklar_ID: requiredEnv('DRIVE_METAL_REVISION_UNPRINTED_INPUT_ID'),
    yapildi_ID: revisionDone,
    mockuplar_ID: revisionOutput,
    product_direction: '',
    product_type: 'metal revizyon',
    is_printed: false
  },
  {
    kategori_adi: 'Metal Revizyon Baskılı',
    yapilacaklar_ID: requiredEnv('DRIVE_METAL_REVISION_PRINTED_INPUT_ID'),
    yapildi_ID: revisionDone,
    mockuplar_ID: revisionOutput,
    product_direction: '',
    product_type: 'metal revizyon',
    is_printed: true
  }
];

const inputs = categories.map(c => c.yapilacaklar_ID);
if (new Set(inputs).size !== 4) throw new Error('The four metal input folder IDs must be distinct.');
const sinks = new Set(categories.flatMap(c => [c.yapildi_ID, c.mockuplar_ID]));
for (const input of inputs) {
  if (sinks.has(input)) throw new Error('An input folder cannot also be a Done/output folder: ' + input);
}
return categories.map(json => ({ json }));"""


STAMP_FILES_JS = r"""// Flatten the four Drive responses, stamp the explicit printed flag, then select globally oldest first.
const categories = $('Map_Categories').all().map(item => item.json);
const byInputFolder = Object.fromEntries(categories.map(category => [category.yapilacaklar_ID, category]));
const MAX_IMAGE_MB = 45;
const MAX_PDF_MB = 25;

function baseName(name) { return String(name || '').replace(/\.[^/.]+$/, ''); }
const output = [];
for (const response of $input.all()) {
  for (const file of (response.json?.files || [])) {
    if (!file?.id) continue;
    const category = (file.parents || []).map(id => byInputFolder[id]).find(Boolean);
    if (!category) continue;
    const isPdf = String(file.mimeType || '') === 'application/pdf';
    const sizeMb = Number(file.size || 0) / (1024 * 1024);
    const maxMb = isPdf ? MAX_PDF_MB : MAX_IMAGE_MB;
    if (sizeMb > maxMb) {
      console.log('ATLANDI - dosya çok büyük (' + sizeMb.toFixed(1) + 'MB > ' + maxMb + 'MB): ' + file.name);
      continue;
    }
    output.push({
      json: {
        id: file.id,
        name: file.name,
        mimeType: file.mimeType,
        size: file.size || '',
        createdTime: file.createdTime || '',
        modifiedTime: file.modifiedTime || '',
        md5Checksum: file.md5Checksum || '',
        kategori_adi: category.kategori_adi,
        yapilacaklar_ID: category.yapilacaklar_ID,
        yapildi_ID: category.yapildi_ID,
        mockuplar_ID: category.mockuplar_ID,
        product_type: category.product_type,
        product_direction: '',
        is_printed: category.is_printed === true,
        output_folder_name: baseName(file.name),
        staging_folder_name: '_LOCAL_STAGING__' + file.id,
        variation: '',
        primary_shape: ''
      },
      pairedItem: { item: 0 }
    });
  }
}
output.sort((a, b) => String(a.json.createdTime).localeCompare(String(b.json.createdTime)) || String(a.json.id).localeCompare(String(b.json.id)));
return output;"""


BUILD_METAL_ITEM_JS = r"""// Printed/unprinted is an explicit property of the input folder; no AI classifier is used.
const input = $input.first();
const source = $('Loop_Files').item.json;
if (!input?.binary?.data) throw new Error('Metal source binary is missing.');
const folder = $('Resolve_Folder').item.json.output_folder_id;
return [{
  json: {
    ...source,
    output_folder_id: folder,
    is_printed: source.is_printed === true
  },
  binary: { data: input.binary.data },
  pairedItem: input.pairedItem || { item: 0 }
}];"""


RESOLVE_STAGING_JS = r"""const response = $input.first()?.json || {};
const existing = Array.isArray(response.files) ? response.files : [];
if (existing.length > 1) throw new Error('Multiple staging folders exist for this source ID.');
const folder = existing[0] || response;
if (!folder.id) throw new Error('Staging folder could not be resolved.');
const source = $('Loop_Files').item.json;
const props = folder.appProperties || {};
if (existing.length && Object.keys(props).length) {
  if (String(props.sourceFileId || '') !== String(source.id)) throw new Error('Staging folder belongs to another source.');
  if (String(props.sourceMd5 || '') !== String(source.md5Checksum || '')) throw new Error('Source changed since the staging folder was created.');
  if (String(props.sourceModified || '') !== String(source.modifiedTime || '')) throw new Error('Source modifiedTime changed since staging began.');
}
return [{ json: { output_folder_id: folder.id } }];"""


RESOLVE_EXISTING_FINAL_JS = r"""const files = $input.first()?.json?.files || [];
if (files.length !== 1) throw new Error('Expected exactly one existing final folder; found ' + files.length + '.');
const folder = files[0];
const source = $('Loop_Files').item.json;
const expected = source.product_type === 'metal revizyon' ? 3 : (source.is_printed === true ? 15 : 18);
const props = folder.appProperties || {};
if (props.pipeline !== 'metal-local-prod-v1' || String(props.sourceFileId || '') !== String(source.id)) {
  throw new Error('Final folder name collision: folder is not committed by this pipeline for this source.');
}
if (String(props.sourceMd5 || '') !== String(source.md5Checksum || '') || String(props.sourceModified || '') !== String(source.modifiedTime || '')) {
  throw new Error('Final folder source fingerprint does not match the current source file.');
}
if (Number(props.expectedMockups) !== expected || props.state !== 'committed') {
  throw new Error('Existing final folder commit metadata is incomplete or inconsistent.');
}
return [{ json: { existing_final_folder_id: folder.id } }];"""


VALIDATE_FILES_JS = r"""const files = $input.first()?.json?.files || [];
const source = $('Loop_Files').item.json;
const indices = source.product_type === 'metal revizyon'
  ? [1, 2, 15]
  : Array.from({ length: source.is_printed === true ? 15 : 18 }, (_, i) => i + 1);
const expected = indices.map(i => source.output_folder_name + '_mockup_' + i + '.png').sort();
const actual = files.map(file => String(file.name || '')).sort();
if (files.length !== expected.length || new Set(actual).size !== actual.length || JSON.stringify(actual) !== JSON.stringify(expected)) {
  throw new Error('Mockup commit gate failed. Expected [' + expected.join(', ') + '] but found [' + actual.join(', ') + '].');
}
return [{ json: { verified_mockup_count: expected.length } }];"""


VALIDATE_SOURCE_JS = r"""const current = $input.first()?.json || {};
const source = $('Loop_Files').item.json;
if (current.trashed === true) throw new Error('Source was trashed during rendering.');
if (String(current.md5Checksum || '') !== String(source.md5Checksum || '')) throw new Error('Source checksum changed during rendering.');
if (String(current.modifiedTime || '') !== String(source.modifiedTime || '')) throw new Error('Source modifiedTime changed during rendering.');
if (!(current.parents || []).includes(source.yapilacaklar_ID)) throw new Error('Source left its expected input folder before commit.');
return [{ json: { source_unchanged: true } }];"""


GUARD_NO_FINAL_JS = r"""const files = $input.first()?.json?.files || [];
if (files.length) throw new Error('A final folder appeared during rendering; refusing to commit over it.');
return [{ json: { final_name_available: true } }];"""


FAIL_NO_PROMPTS_JS = r"""throw new Error('Metal prompt generation returned no scenes; source and staging are intentionally left untouched.');"""


def uid() -> str:
    return str(uuid.uuid4())


def code_node(name: str, js: str, pos: tuple[int, int]) -> dict:
    return {
        "parameters": {"jsCode": js},
        "id": uid(),
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": list(pos),
    }


def http_node(name: str, url: str, pos: tuple[int, int], *, method: str = "GET") -> dict:
    parameters: dict = {"url": url, "options": {}}
    if method != "GET":
        parameters["method"] = method
    return {
        "parameters": parameters,
        "id": uid(),
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": list(pos),
    }


def if_node(name: str, left: str, operation: str, right, pos: tuple[int, int]) -> dict:
    operator = {"type": "number", "operation": operation}
    return {
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                "conditions": [{
                    "id": uid(),
                    "leftValue": left,
                    "rightValue": right,
                    "operator": operator,
                }],
                "combinator": "and",
            },
            "options": {},
        },
        "id": uid(),
        "name": name,
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "position": list(pos),
    }


def drive_search(name: str, q: str, fields: str, pos: tuple[int, int], page_size: int = 1000) -> dict:
    node = http_node(name, "https://www.googleapis.com/drive/v3/files", pos)
    node["alwaysOutputData"] = True
    node["parameters"].update({
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "googleDriveOAuth2Api",
        "sendQuery": True,
        "queryParameters": {"parameters": [
            {"name": "q", "value": q},
            {"name": "fields", "value": fields},
            {"name": "pageSize", "value": str(page_size)},
            {"name": "supportsAllDrives", "value": "true"},
            {"name": "includeItemsFromAllDrives", "value": "true"},
        ]},
    })
    return node


def drive_get(name: str, url: str, fields: str, pos: tuple[int, int]) -> dict:
    node = http_node(name, url, pos)
    node["parameters"].update({
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "googleDriveOAuth2Api",
        "sendQuery": True,
        "queryParameters": {"parameters": [
            {"name": "fields", "value": fields},
            {"name": "supportsAllDrives", "value": "true"},
        ]},
    })
    return node


def drive_patch(name: str, url: str, body: str, pos: tuple[int, int]) -> dict:
    node = http_node(name, url, pos, method="PATCH")
    node["parameters"].update({
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "googleDriveOAuth2Api",
        "sendQuery": True,
        "queryParameters": {"parameters": [{"name": "supportsAllDrives", "value": "true"}]},
        "sendBody": True,
        "contentType": "json",
        "specifyBody": "json",
        "jsonBody": body,
    })
    return node


def connect(connections: dict, source: str, target: str, output: int = 0) -> None:
    groups = connections.setdefault(source, {}).setdefault("main", [])
    while len(groups) <= output:
        groups.append([])
    groups[output].append({"node": target, "type": "main", "index": 0})


def build(mode: str) -> dict:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    source_nodes = {node["name"]: copy.deepcopy(node) for node in source["nodes"]}
    nodes = [source_nodes[name] for name in KEEP_SOURCE_NODES]
    by_name = {node["name"]: node for node in nodes}

    # Re-purpose the source Drive folder nodes for deterministic staging.
    search_files = by_name["Search_Files"]
    search_files["parameters"]["queryParameters"]["parameters"] = [
        {"name": "q", "value": "={{ \"'\" + $json.yapilacaklar_ID + \"' in parents and (mimeType contains 'image/' or mimeType = 'application/pdf') and trashed = false\" }}"},
        {"name": "fields", "value": "files(id,name,mimeType,parents,size,createdTime,modifiedTime,md5Checksum)"},
        {"name": "pageSize", "value": "1000"},
        {"name": "orderBy", "value": "createdTime asc"},
        {"name": "supportsAllDrives", "value": "true"},
        {"name": "includeItemsFromAllDrives", "value": "true"},
    ]

    upload = by_name["GDrive_Upload_Mockups"]
    upload["parameters"]["folderId"]["value"] = "={{ $('Resolve_Folder').item.json.output_folder_id }}"
    upload["parameters"]["name"] = "={{ $json.source_base_name }}_mockup_{{ $json.mockup_index }}.png"

    move = by_name["GDrive_Move_Original"]
    move["parameters"]["fileId"]["value"] = "={{ $('Loop_Files').item.json.id }}"
    move["parameters"]["folderId"]["value"] = "={{ $('Loop_Files').item.json.yapildi_ID }}"

    # Local services are intentionally internal-only and unauthenticated.  The
    # frozen rollback leaves credential attachment to the importing n8n instance.
    inference_url = GATEWAY_URL if mode == "local" else FAL_URL
    for name in METAL_INFERENCE_NODES:
        node = by_name[name]
        node["parameters"]["url"] = inference_url
        node["parameters"].pop("authentication", None)
        node["parameters"].pop("genericAuthType", None)
        node.pop("credentials", None)
        node["parameters"].setdefault("options", {})["timeout"] = 7_200_000
        node.pop("retryOnFail", None)
        node.pop("maxTries", None)
        node.pop("waitBetweenTries", None)
        if mode == "rollback":
            node["parameters"]["authentication"] = "genericCredentialType"
            node["parameters"]["genericAuthType"] = "httpHeaderAuth"
            node["credentials"] = copy.deepcopy(FAL_CREDENTIAL)

    for name in ("HTTP_Rasterize_PDF", "HTTP_Rasterize_Metal_HighFill"):
        node = by_name[name]
        node["parameters"]["url"] = LOCAL_PDF_URL if mode == "local" else CLOUD_PDF_URL
        node["parameters"].pop("sendHeaders", None)
        node["parameters"].pop("headerParameters", None)
        node.pop("onError", None)  # A raster error must stop; never silently skip/move.
        node.pop("credentials", None)
        node["parameters"].setdefault("options", {}).setdefault("response", {"response": {"responseFormat": "file", "outputPropertyName": "data"}})
        node["parameters"]["options"]["timeout"] = 600_000
        if mode == "rollback":
            node["parameters"]["authentication"] = "genericCredentialType"
            node["parameters"]["genericAuthType"] = "httpHeaderAuth"
            node["credentials"] = copy.deepcopy(PDF_CREDENTIAL)

    by_name["HTTP_Download_Metal_Master"]["parameters"].setdefault("options", {})["timeout"] = 600_000
    by_name["HTTP_Download_Fal_Result"]["parameters"].setdefault("options", {})["timeout"] = 600_000

    # New triggers and Drive transaction/guard nodes.
    manual = {
        "parameters": {}, "id": uid(), "name": "Manual_Trigger",
        "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [-1800, 80],
    }
    schedule = {
        "parameters": {"rule": {"interval": [{"field": "minutes", "minutesInterval": 5}]}},
        "id": uid(), "name": "Schedule_Every_5_Minutes",
        "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2, "position": [-1800, 240],
    }
    map_node = code_node("Map_Categories", MAP_CATEGORIES_JS, (-1580, 160))
    stamp_node = code_node("Stamp_Files", STAMP_FILES_JS, (-1160, 160))
    build_item = code_node("Build_Metal_Item", BUILD_METAL_ITEM_JS, (700, 400))

    final_q = r"""={{ "name = '" + $('Loop_Files').item.json.output_folder_name.replace(/'/g, "\\'") + "' and '" + $('Loop_Files').item.json.mockuplar_ID + "' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false" }}"""
    staging_q = "={{ \"name = '\" + $('Loop_Files').item.json.staging_folder_name + \"' and '\" + $('Loop_Files').item.json.mockuplar_ID + \"' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false\" }}"
    search_final = drive_search("Search_Final_Folder", final_q, "files(id,name,appProperties)", (-400, 80), 10)
    if_final = if_node("If_Final_Folder_Exists", "={{ $json.files.length }}", "gt", 0, (-180, 80))
    resolve_final = code_node("Resolve_Existing_Final", RESOLVE_EXISTING_FINAL_JS, (40, -80))
    search_final_files = drive_search(
        "Search_Existing_Final_Files",
        "={{ \"'\" + $json.existing_final_folder_id + \"' in parents and trashed = false\" }}",
        "files(id,name,size,md5Checksum)",
        (260, -80),
    )
    validate_final = code_node("Validate_Existing_Final_Files", VALIDATE_FILES_JS, (480, -80))

    search_staging = drive_search("Search_Staging_Folder", staging_q, "files(id,name,appProperties)", (40, 200), 10)
    if_staging = if_node("If_Staging_Folder_Exists", "={{ $json.files.length }}", "gt", 0, (260, 200))
    create_staging = copy.deepcopy(source_nodes["GDrive_Create_Output_Folder"])
    create_staging["id"] = uid()
    create_staging["name"] = "GDrive_Create_Staging_Folder"
    create_staging["position"] = [480, 300]
    create_staging["parameters"]["name"] = "={{ $('Loop_Files').item.json.staging_folder_name }}"
    create_staging["parameters"]["folderId"]["value"] = "={{ $('Loop_Files').item.json.mockuplar_ID }}"
    create_staging.pop("credentials", None)
    resolve_staging = code_node("Resolve_Folder", RESOLVE_STAGING_JS, (700, 200))

    init_body = "={{ JSON.stringify({ appProperties: { pipeline: 'metal-local-prod-v1', state: 'staging', sourceFileId: String($('Loop_Files').item.json.id), sourceMd5: String($('Loop_Files').item.json.md5Checksum || ''), sourceModified: String($('Loop_Files').item.json.modifiedTime || '') } }) }}"
    init_staging = drive_patch(
        "Initialize_Staging_Metadata",
        "={{ 'https://www.googleapis.com/drive/v3/files/' + $('Resolve_Folder').item.json.output_folder_id }}",
        init_body,
        (920, 200),
    )

    mockup_q = r"""={{ "name = '" + $('Loop_Mockups').item.json.source_base_name.replace(/'/g, "\\'") + "_mockup_" + $('Loop_Mockups').item.json.prompt_index + ".png' and '" + $('Resolve_Folder').item.json.output_folder_id + "' in parents and trashed = false" }}"""
    search_mockup = drive_search("Search_Staged_Mockup", mockup_q, "files(id,name,size,md5Checksum)", (1120, 520), 10)
    if_mockup = if_node("If_Staged_Mockup_Exists", "={{ $json.files.length }}", "gt", 0, (1340, 520))
    skip_mockup = {
        "parameters": {}, "id": uid(), "name": "Skip_Existing_Staged_Mockup",
        "type": "n8n-nodes-base.noOp", "typeVersion": 1, "position": [2540, 540],
    }

    staged_files = drive_search(
        "Search_Staged_Files",
        "={{ \"'\" + $('Resolve_Folder').item.json.output_folder_id + \"' in parents and trashed = false\" }}",
        "files(id,name,size,md5Checksum)",
        (1200, 840),
    )
    validate_staged = code_node("Validate_Staged_Files", VALIDATE_FILES_JS, (1420, 840))
    get_source = drive_get(
        "Get_Source_Metadata_Before_Commit",
        "={{ 'https://www.googleapis.com/drive/v3/files/' + $('Loop_Files').item.json.id }}",
        "id,md5Checksum,modifiedTime,parents,trashed",
        (1640, 840),
    )
    validate_source = code_node("Validate_Source_Unchanged", VALIDATE_SOURCE_JS, (1860, 840))
    search_final_before_commit = drive_search(
        "Search_Final_Before_Commit",
        final_q,
        "files(id,name,appProperties)",
        (2080, 840),
        10,
    )
    guard_no_final = code_node("Guard_No_Final_Before_Commit", GUARD_NO_FINAL_JS, (2300, 840))
    commit_body = "={{ JSON.stringify({ name: $('Loop_Files').item.json.output_folder_name, appProperties: { pipeline: 'metal-local-prod-v1', state: 'committed', sourceFileId: String($('Loop_Files').item.json.id), sourceMd5: String($('Loop_Files').item.json.md5Checksum || ''), sourceModified: String($('Loop_Files').item.json.modifiedTime || ''), expectedMockups: String($('Validate_Staged_Files').item.json.verified_mockup_count) } }) }}"
    commit = drive_patch(
        "Commit_Staging_Folder",
        "={{ 'https://www.googleapis.com/drive/v3/files/' + $('Resolve_Folder').item.json.output_folder_id }}",
        commit_body,
        (2520, 840),
    )
    fail_no_prompts = code_node("Fail_No_Metal_Prompts", FAIL_NO_PROMPTS_JS, (900, 1040))

    nodes.extend([
        manual, schedule, map_node, stamp_node, build_item,
        search_final, if_final, resolve_final, search_final_files, validate_final,
        search_staging, if_staging, create_staging, resolve_staging, init_staging,
        search_mockup, if_mockup, skip_mockup,
        staged_files, validate_staged, get_source, validate_source,
        search_final_before_commit, guard_no_final, commit, fail_no_prompts,
    ])

    if mode == "rollback":
        for node in nodes:
            parameters = node.get("parameters", {})
            for key in ("jsCode", "jsonBody"):
                if isinstance(parameters.get(key), str):
                    parameters[key] = parameters[key].replace("metal-local-prod-v1", "metal-cloud-rollback-v1")

    # Credential stubs contain no secret. They make import-time remapping explicit
    # instead of leaving Drive/FAL/PDF nodes silently unconfigured.
    for node in nodes:
        parameters = node.get("parameters", {})
        if (
            node.get("type") == "n8n-nodes-base.googleDrive"
            or parameters.get("nodeCredentialType") == "googleDriveOAuth2Api"
        ):
            node["credentials"] = copy.deepcopy(DRIVE_CREDENTIAL)

    connections: dict = {}
    connect(connections, "Manual_Trigger", "Map_Categories")
    connect(connections, "Schedule_Every_5_Minutes", "Map_Categories")
    connect(connections, "Map_Categories", "Search_Files")
    connect(connections, "Search_Files", "Stamp_Files")
    connect(connections, "Stamp_Files", "Limit")
    connect(connections, "Limit", "Loop_Files")
    connect(connections, "Loop_Files", "Search_Final_Folder", 0)
    connect(connections, "Loop_Files", "Done", 1)
    connect(connections, "Search_Final_Folder", "If_Final_Folder_Exists")
    connect(connections, "If_Final_Folder_Exists", "Resolve_Existing_Final", 0)
    connect(connections, "If_Final_Folder_Exists", "Search_Staging_Folder", 1)
    connect(connections, "Resolve_Existing_Final", "Search_Existing_Final_Files")
    connect(connections, "Search_Existing_Final_Files", "Validate_Existing_Final_Files")
    connect(connections, "Validate_Existing_Final_Files", "GDrive_Move_Original")
    connect(connections, "Search_Staging_Folder", "If_Staging_Folder_Exists")
    connect(connections, "If_Staging_Folder_Exists", "Resolve_Folder", 0)
    connect(connections, "If_Staging_Folder_Exists", "GDrive_Create_Staging_Folder", 1)
    connect(connections, "GDrive_Create_Staging_Folder", "Resolve_Folder")
    connect(connections, "Resolve_Folder", "Initialize_Staging_Metadata")
    connect(connections, "Initialize_Staging_Metadata", "GDrive_Download")
    connect(connections, "GDrive_Download", "If_Is_PDF")
    connect(connections, "If_Is_PDF", "HTTP_Rasterize_PDF", 0)
    connect(connections, "If_Is_PDF", "Build_Metal_Item", 1)
    connect(connections, "HTTP_Rasterize_PDF", "Build_Metal_Item")
    connect(connections, "Build_Metal_Item", "If_Metal_Needs_Master")
    connect(connections, "If_Metal_Needs_Master", "Prepare_Metal_HighFill_Source", 0)
    connect(connections, "If_Metal_Needs_Master", "Parse_JSON", 1)
    connect(connections, "Prepare_Metal_HighFill_Source", "If_Metal_HighFill_Is_PDF")
    connect(connections, "If_Metal_HighFill_Is_PDF", "HTTP_Rasterize_Metal_HighFill", 0)
    connect(connections, "If_Metal_HighFill_Is_PDF", "Build_Metal_HighFill_Master_Req", 1)
    connect(connections, "HTTP_Rasterize_Metal_HighFill", "Build_Metal_HighFill_Master_Req")
    connect(connections, "Build_Metal_HighFill_Master_Req", "HTTP_Metal_HighFill_Master")
    connect(connections, "HTTP_Metal_HighFill_Master", "Capture_HighFill_And_Restore_Standard_Input")
    connect(connections, "Capture_HighFill_And_Restore_Standard_Input", "Build_Metal_Master_Req")
    connect(connections, "Build_Metal_Master_Req", "HTTP_Metal_Master")
    connect(connections, "HTTP_Metal_Master", "Metal_Master_URL_Metadata")
    connect(connections, "Metal_Master_URL_Metadata", "HTTP_Download_Metal_Master")
    connect(connections, "HTTP_Download_Metal_Master", "Parse_JSON")
    connect(connections, "Parse_JSON", "Override_Metal_Prompts_r30")
    connect(connections, "Override_Metal_Prompts_r30", "Apply_r32_Surface_Shadow_Gates")
    connect(connections, "Apply_r32_Surface_Shadow_Gates", "If_Has_Prompts")
    connect(connections, "If_Has_Prompts", "Loop_Mockups", 0)
    connect(connections, "If_Has_Prompts", "Fail_No_Metal_Prompts", 1)
    connect(connections, "Loop_Mockups", "Search_Staged_Mockup", 0)
    connect(connections, "Loop_Mockups", "Search_Staged_Files", 1)
    connect(connections, "Search_Staged_Mockup", "If_Staged_Mockup_Exists")
    connect(connections, "If_Staged_Mockup_Exists", "Skip_Existing_Staged_Mockup", 0)
    connect(connections, "If_Staged_Mockup_Exists", "Build_Fal_Req", 1)
    connect(connections, "Skip_Existing_Staged_Mockup", "Loop_Mockups")
    connect(connections, "Build_Fal_Req", "HTTP_Fal_Flux_Edit")
    connect(connections, "HTTP_Fal_Flux_Edit", "Fal_Response_To_URL")
    connect(connections, "Fal_Response_To_URL", "HTTP_Download_Fal_Result")
    connect(connections, "HTTP_Download_Fal_Result", "Strip_Metadata")
    connect(connections, "Strip_Metadata", "GDrive_Upload_Mockups")
    connect(connections, "GDrive_Upload_Mockups", "Loop_Mockups")
    connect(connections, "Search_Staged_Files", "Validate_Staged_Files")
    connect(connections, "Validate_Staged_Files", "Get_Source_Metadata_Before_Commit")
    connect(connections, "Get_Source_Metadata_Before_Commit", "Validate_Source_Unchanged")
    connect(connections, "Validate_Source_Unchanged", "Search_Final_Before_Commit")
    connect(connections, "Search_Final_Before_Commit", "Guard_No_Final_Before_Commit")
    connect(connections, "Guard_No_Final_Before_Commit", "Commit_Staging_Folder")
    connect(connections, "Commit_Staging_Folder", "GDrive_Move_Original")
    connect(connections, "GDrive_Move_Original", "Loop_Files")

    return {
        "name": "[LOCAL PROD] Metal Mockup Generator" if mode == "local" else "[FROZEN ROLLBACK] Cloud Metal Mockup Generator",
        "nodes": nodes,
        "pinData": {},
        "connections": connections,
        "active": False,
        "settings": {
            "executionOrder": "v1",
            "binaryMode": "separate",
            "availableInMCP": False,
            "timezone": "Europe/Istanbul",
        },
        "versionId": uid(),
        "meta": {"templateCredsSetupCompleted": False},
        "tags": [],
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_OUT.write_text(json.dumps(build("local"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ROLLBACK_OUT.write_text(json.dumps(build("rollback"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(LOCAL_OUT.relative_to(ROOT))
    print(ROLLBACK_OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
