#!/usr/bin/env bash
# =============================================================================
# set-secrets.sh -- Rotate Spotify & Last.fm credentials in GCP Secret Manager
# =============================================================================
# Prompts without terminal echo (read -rs) and pipes secrets via stdin
# (--data-file=-) so values never appear in process lists or shell history.
# Triggers a zero-downtime Cloud Run revision rollout after updating secrets.
# =============================================================================
set -euo pipefail

readonly PROJECT_ID="${1:-netdev-firebase}"
readonly REGION="europe-west1"
readonly SERVICE="barogroove-api"

prompt_and_set() {
  local secret_name="$1"
  local prompt_text="$2"
  local val=""

  printf '\n==> %s (%s)\n' "${secret_name}" "${prompt_text}"
  printf '    Enter new value (leave blank to skip): '
  read -rs val
  printf '\n'

  if [[ -z "${val}" ]]; then
    printf '    [skipped]\n'
    return 0
  fi

  printf '%s' "${val}" | gcloud secrets versions add "${secret_name}" \
    --project "${PROJECT_ID}" \
    --data-file=- >/dev/null
  printf '    ✓ Added new enabled version to %s\n' "${secret_name}"
}

printf '=====================================================================\n'
printf 'BAROGROOVE -- Secret Manager Credential Setup (%s)\n' "${PROJECT_ID}"
printf '=====================================================================\n'

prompt_and_set "barogroove-spotify-client-id"     "Spotify Developer App Client ID"
prompt_and_set "barogroove-spotify-client-secret" "Spotify Developer App Client Secret"
prompt_and_set "barogroove-lastfm-api-key"        "Last.fm API Key"
prompt_and_set "barogroove-lastfm-api-secret"     "Last.fm Shared Secret"

printf '\n==> Rolling out new Cloud Run revision to pick up updated secrets...\n'
gcloud run services update "${SERVICE}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --update-env-vars="BG_SECRET_REFRESH_TS=$(date -u +%Y%m%d%H%M%S)" \
  --quiet

printf '\n✓ Done! Verify status at: https://bg.netdev.be/api/pair/status\n'
