# Metal workflow exports

`metal-local-prod.json` is the inactive metal-only workflow for the local
Compose stack. `metal-cloud-rollback-frozen.json` is an inactive, frozen cloud
rollback with the same four explicit input folders and unchanged r39
prompt/seed/size code.

Before importing, set the eight `DRIVE_*` variables from the root
`local-prod/.env.example`. After import, map every credential named
`LOCAL PROD Google Drive` to the local n8n Google Drive OAuth credential.
The placeholder ID is deliberately invalid and contains no secret.

For the frozen rollback only, also map:

- `FROZEN ROLLBACK FAL` to an HTTP Header Auth credential with the FAL key.
- `FROZEN ROLLBACK PDF Raster` to an HTTP Header Auth credential with the
  Cloud Run raster service token.

Both exports stay `active:false` on import. Activate only one metal consumer at
a time. The local workflow schedules every five minutes and also has a manual
trigger; production concurrency must still be set to `1` in n8n.

The workflow writes first to `_LOCAL_STAGING__<Drive source id>`. It validates
the exact expected filenames, rechecks the source checksum and modified time,
checks that no final-name collision appeared, and only then renames the staging
folder and moves the source to Done. A rerun skips an already-staged filename;
the final manifest gate rejects missing or duplicate files.

Regenerate and validate:

```powershell
python -B local-prod\workflow\build_metal_workflows.py
python -B local-prod\workflow\validate_metal_workflows.py
```

The validator checks JSON/connection integrity, every Code-node syntax,
credential stubs, four category mappings, absence of cloud endpoints from the
local export, and byte-identical hashes for the r39 prompt/seed/size Code nodes.
