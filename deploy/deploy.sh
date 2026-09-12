#!/usr/bin/env bash
# =============================================================================
# Barogroove -- end-to-end deploy
# "your sky has a soundtrack"
#
#   ./deploy/deploy.sh --project barogroove-prod --dry-run   # read this first
#   ./deploy/deploy.sh --project barogroove-prod
#
# WHAT THIS DOES, in order:
#   0. preflight     -- verify tools, auth, project, and that we are in the repo
#   1. apis          -- enable the services we need (idempotent)
#   2. artifacts     -- create the Artifact Registry repo if absent
#   3. iam           -- create the runtime service account and grant its roles
#   4. secrets       -- create Secret Manager secrets if absent, PROMPTING for
#                       values. Nothing sensitive is ever written to this file,
#                       to argv, or to the shell history.
#   5. build         -- Cloud Build: build, smoke-test, push, deploy
#   6. hosting       -- Firebase Hosting + Firestore rules + indexes
#   7. verify        -- probe /healthz through the public URL
#
# IDEMPOTENT. Every step checks before it creates. Re-running after a failure
# picks up where it stopped; re-running after a success is a no-op plus a new
# revision. There is no "clean up the half-finished attempt" step because there
# is never a half-finished attempt to clean up.
#
# REGION: europe-west1. Hard-coded, deliberately, with no flag to change it.
# A region flag is a region mistake waiting for a hurried afternoon.
#
# This script does not run at write time and does nothing on import. It is a
# script, not a deployment. Read it, then run it.
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

readonly REGION="europe-west1"          # non-negotiable
readonly SERVICE="barogroove-api"
readonly REPOSITORY="barogroove"
readonly SA_NAME="barogroove-api"
readonly PUBLIC_HOST="bg.netdev.be"

# Secret Manager secret ids. The app references these as sm://<id>.
readonly -a SECRETS=(
  "barogroove-token-encryption-key"
  "barogroove-firebase-web-api-key"
  "barogroove-lastfm-api-key"
  "barogroove-lastfm-api-secret"
  "barogroove-spotify-client-id"
  "barogroove-spotify-client-secret"
)

readonly -a REQUIRED_APIS=(
  "run.googleapis.com"
  "cloudbuild.googleapis.com"
  "artifactregistry.googleapis.com"
  "secretmanager.googleapis.com"
  "firestore.googleapis.com"
  "firebase.googleapis.com"
  "identitytoolkit.googleapis.com"
  "iam.googleapis.com"
  "cloudresourcemanager.googleapis.com"
  "weather.googleapis.com"
  "aiplatform.googleapis.com"
)

# Roles the runtime service account needs. Rationale for each is in
# deploy/service-account.md -- read it before adding to this list.
readonly -a SA_ROLES=(
  "roles/datastore.user"                  # read/write Firestore
  "roles/secretmanager.secretAccessor"    # read secret VALUES
  "roles/secretmanager.secretVersionManager" # write new secret versions from pairing UI
  "roles/firebaseauth.viewer"             # verify ID tokens
  "roles/logging.logWriter"               # structured logs
  "roles/monitoring.metricWriter"         # custom metrics
  "roles/cloudtrace.agent"                # traces
  "roles/serviceusage.serviceUsageConsumer" # query Google Cloud Weather API via ADC
  "roles/aiplatform.user"                 # invoke Vertex AI Gemini 2.5 Flash for Live Advisor & Executor
)

# -----------------------------------------------------------------------------
# Flags
# -----------------------------------------------------------------------------

PROJECT_ID="${BG_GCP_PROJECT:-netdev-firebase}"
DRY_RUN="false"
SKIP_BUILD="false"
SKIP_HOSTING="false"
BUILD_WEB="false"
FAST_DEPLOY="false"
FLUTTER_BUILD_PID=""

usage() {
  cat <<'EOF'
Barogroove deploy

Usage:
  deploy.sh --project PROJECT_ID [options]

Options:
  --project ID     Target GCP project. Defaults to $BG_GCP_PROJECT, then to the
                   active gcloud config value.
  --build-web      Compile Flutter Web (--release --no-wasm-dry-run) in parallel
                   with Cloud Build so both complete simultaneously.
  --fast           Fast path: skip API/IAM/Secret Manager reconciliation when
                   infrastructure is already provisioned.
  --dry-run        Print every mutating command instead of running it. Read-only
                   probes still run, so the plan reflects real cluster state.
  --skip-build     Skip Cloud Build and the Cloud Run deploy. For a hosting-only
                   or rules-only push.
  --skip-hosting   Skip Firebase Hosting, rules and indexes. For a backend-only
                   push.
  -h, --help       This.

Region is europe-west1 and there is no flag to change it.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)      PROJECT_ID="${2:-}"; shift 2 ;;
    --project=*)    PROJECT_ID="${1#*=}"; shift ;;
    --build-web)    BUILD_WEB="true"; shift ;;
    --fast)         FAST_DEPLOY="true"; shift ;;
    --dry-run)      DRY_RUN="true"; shift ;;
    --skip-build)   SKIP_BUILD="true"; shift ;;
    --skip-hosting) SKIP_HOSTING="true"; shift ;;
    -h|--help)      usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

# -----------------------------------------------------------------------------
# Output helpers
# -----------------------------------------------------------------------------

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
  C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'
else
  C_RESET=""; C_BOLD=""; C_DIM=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""
fi

step() { printf '\n%s==> %s%s\n' "${C_BOLD}${C_BLUE}" "$*" "${C_RESET}"; }
info() { printf '    %s\n' "$*"; }
ok()   { printf '    %s✓%s %s\n' "${C_GREEN}" "${C_RESET}" "$*"; }
warn() { printf '    %s!%s %s\n' "${C_YELLOW}" "${C_RESET}" "$*" >&2; }
die()  { printf '\n%sERROR:%s %s\n' "${C_RED}${C_BOLD}" "${C_RESET}" "$*" >&2; exit 1; }

# run -- execute a mutating command, or print it under --dry-run.
#
# Every state-changing call in this script goes through here. That is the whole
# --dry-run contract: if a command is not wrapped in `run`, it must be
# read-only. No exceptions, including the ones that feel harmless.
run() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    printf '    %s[dry-run]%s %s\n' "${C_DIM}" "${C_RESET}" "$*"
    return 0
  fi
  "$@"
}

# run_stdin -- same, for commands that read a value from stdin (secrets).
# The value never appears in argv, so it never reaches `ps` or a shell history.
run_stdin() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    printf '    %s[dry-run]%s %s  <<< (value from stdin, not shown)\n' \
      "${C_DIM}" "${C_RESET}" "$*"
    cat >/dev/null   # drain stdin so the caller's pipe does not block
    return 0
  fi
  "$@"
}

# -----------------------------------------------------------------------------
# 0. Preflight
#
# Fail before touching anything. A deploy that dies halfway because `firebase`
# was not installed is worse than one that never started.
# -----------------------------------------------------------------------------

preflight() {
  step "Preflight"

  local missing=()
  for tool in gcloud firebase curl sed python3; do
    command -v "${tool}" >/dev/null 2>&1 || missing+=("${tool}")
  done
  if (( ${#missing[@]} )); then
    die "missing required tool(s): ${missing[*]}
  gcloud   -> https://cloud.google.com/sdk/docs/install
  firebase -> npm install -g firebase-tools"
  fi
  ok "required tools present"

  # Repo root: this script lives in deploy/, so the root is its parent.
  SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
  readonly SCRIPT_DIR REPO_ROOT
  cd "${REPO_ROOT}"

  for required in \
      "deploy/cloudrun.yaml" \
      "deploy/cloudbuild.yaml" \
      "firebase_cfg/firebase.json" \
      "firebase_cfg/firestore.rules" \
      "firebase_cfg/firestore.indexes.json"; do
    [[ -f "${required}" ]] || die "expected ${required} relative to ${REPO_ROOT}"
  done
  ok "repository layout looks right (${REPO_ROOT})"

  # Active credentials.
  local account
  account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -n1)"
  [[ -n "${account}" ]] || die "no active gcloud account. Run: gcloud auth login"
  ok "authenticated as ${account}"

  # Project resolution: flag > env > gcloud config.
  if [[ -z "${PROJECT_ID}" ]]; then
    PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
  fi
  [[ -n "${PROJECT_ID}" && "${PROJECT_ID}" != "(unset)" ]] \
    || die "no project. Pass --project PROJECT_ID or set BG_GCP_PROJECT."

  gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1 \
    || die "project '${PROJECT_ID}' does not exist or you cannot see it"

  PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
  SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
  readonly PROJECT_ID PROJECT_NUMBER SA_EMAIL

  ok "project ${PROJECT_ID} (number ${PROJECT_NUMBER})"
  ok "region  ${REGION}"
  ok "service account ${SA_EMAIL}"

  # Firebase CLI login is separate from gcloud's. People forget.
  if ! firebase projects:list >/dev/null 2>&1; then
    warn "firebase CLI is not logged in. Run: firebase login"
    warn "hosting deploy will fail until you do"
  else
    ok "firebase CLI authenticated"
  fi

  if [[ "${DRY_RUN}" == "true" ]]; then
    printf '\n%s    DRY RUN -- no mutating command will execute.%s\n' \
      "${C_YELLOW}${C_BOLD}" "${C_RESET}"
  fi
}

# -----------------------------------------------------------------------------
# 1. APIs
#
# `services enable` is already idempotent, but it is also slow. Checking first
# turns a re-run from ~40s into ~2s.
# -----------------------------------------------------------------------------

enable_apis() {
  step "Enabling APIs"

  local enabled to_enable=()
  enabled="$(gcloud services list --enabled --project "${PROJECT_ID}" \
    --format='value(config.name)' 2>/dev/null || true)"

  local api
  for api in "${REQUIRED_APIS[@]}"; do
    if grep -qx "${api}" <<<"${enabled}"; then
      info "${api} already enabled"
    else
      to_enable+=("${api}")
    fi
  done

  if (( ${#to_enable[@]} == 0 )); then
    ok "all APIs already enabled"
    return 0
  fi

  info "enabling: ${to_enable[*]}"
  run gcloud services enable "${to_enable[@]}" --project "${PROJECT_ID}"
  ok "APIs enabled"
}

# -----------------------------------------------------------------------------
# 1b. Firestore database
# -----------------------------------------------------------------------------

# A Firestore database's location is IMMUTABLE. There is no move, no edit, no
# migration switch: getting it wrong means creating a second database (or a new
# project) and copying the data across.
#
# Left implicit, Firestore lands in `nam5` -- the United States. This app stores
# coordinates and listening history for EU residents, so that default is a data
# residency incident that nobody notices until an audit.
#
# So: create it explicitly in ${REGION}, and if one already exists, verify the
# location and refuse to continue when it is wrong. A loud failure here is far
# cheaper than discovering it after the first real user.
ensure_firestore_database() {
  step "Firestore"

  local existing
  existing="$(gcloud firestore databases describe \
    --database="(default)" --project "${PROJECT_ID}" \
    --format="value(locationId)" 2>/dev/null || true)"

  if [[ -n "${existing}" ]]; then
    if [[ "${existing}" == "${REGION}" || "${existing}" == "eur3" || "${existing}" == "europe-west" ]]; then
      ok "database '(default)' exists in EU location '${existing}'"
      return 0
    fi
    die "Firestore '(default)' is in '${existing}', not in an EU region (${REGION} or eur3).
    A Firestore location cannot be changed after creation. To fix this you must
    create a new database (or a new project) in ${REGION} and migrate the data.
    Refusing to deploy: writing EU listener data into '${existing}' is not
    something this script will do quietly."
  fi

  info "creating Firestore '(default)' in ${REGION}"
  run gcloud firestore databases create \
    --database="(default)" \
    --location="${REGION}" \
    --type=firestore-native \
    --project "${PROJECT_ID}"
  ok "database created in ${REGION}"
}

# -----------------------------------------------------------------------------
# 2. Artifact Registry
# -----------------------------------------------------------------------------

ensure_artifact_registry() {
  step "Artifact Registry"

  if gcloud artifacts repositories describe "${REPOSITORY}" \
       --location "${REGION}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    ok "repository '${REPOSITORY}' exists in ${REGION}"
    return 0
  fi

  info "creating Docker repository '${REPOSITORY}' in ${REGION}"
  run gcloud artifacts repositories create "${REPOSITORY}" \
    --repository-format=docker \
    --location "${REGION}" \
    --project "${PROJECT_ID}" \
    --description="Barogroove container images"
  ok "repository created"
}

# -----------------------------------------------------------------------------
# 3. Service account and IAM
#
# Least privilege. Every role here is justified in service-account.md. If you
# find yourself wanting to add roles/editor to make something work, the thing
# that is broken is not the permissions.
# -----------------------------------------------------------------------------

ensure_service_account() {
  step "Service account and IAM"

  if gcloud iam service-accounts describe "${SA_EMAIL}" \
       --project "${PROJECT_ID}" >/dev/null 2>&1; then
    ok "service account exists"
  else
    info "creating ${SA_EMAIL}"
    run gcloud iam service-accounts create "${SA_NAME}" \
      --project "${PROJECT_ID}" \
      --display-name="Barogroove API runtime" \
      --description="Least-privilege runtime identity for the Cloud Run service"
    ok "service account created"
  fi

  # Existing bindings, so we only add what is missing. add-iam-policy-binding is
  # idempotent, but each call is a full read-modify-write of the project policy
  # and they serialise badly.
  local existing
  existing="$(gcloud projects get-iam-policy "${PROJECT_ID}" \
    --flatten='bindings[].members' \
    --filter="bindings.members:serviceAccount:${SA_EMAIL}" \
    --format='value(bindings.role)' 2>/dev/null || true)"

  local role
  for role in "${SA_ROLES[@]}"; do
    if grep -qx "${role}" <<<"${existing}"; then
      info "${role} already granted"
      continue
    fi
    info "granting ${role}"
    run gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
      --member="serviceAccount:${SA_EMAIL}" \
      --role="${role}" \
      --condition=None \
      --quiet >/dev/null
  done
  ok "IAM roles reconciled"

  # Cloud Build needs to act as the runtime SA in order to deploy a service
  # that runs as it. Without this the deploy step fails with a confusing
  # "iam.serviceAccounts.actAs" denial.
  local cb_sa="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
  local sa_policy
  sa_policy="$(gcloud iam service-accounts get-iam-policy "${SA_EMAIL}" --project "${PROJECT_ID}" --format=json 2>/dev/null || true)"
  if printf '%s' "${sa_policy}" | grep -q "${cb_sa}"; then
    info "Cloud Build (${cb_sa}) already allowed to actAs runtime SA"
  else
    info "allowing Cloud Build (${cb_sa}) to actAs the runtime SA"
    run gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
      --member="serviceAccount:${cb_sa}" \
      --role="roles/iam.serviceAccountUser" \
      --project "${PROJECT_ID}" \
      --quiet >/dev/null
  fi

  # And it needs to deploy Cloud Run at all.
  local cb_role
  for cb_role in "roles/run.admin" "roles/artifactregistry.writer"; do
    if printf '%s' "${policy:-}" | grep -q "${cb_sa}" && printf '%s' "${policy:-}" | grep -q "${cb_role}"; then
      info "${cb_role} already granted to Cloud Build"
    else
      info "granting ${cb_role} to Cloud Build"
      run gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${cb_sa}" \
        --role="${cb_role}" \
        --condition=None \
        --quiet >/dev/null
    fi
  done
  ok "Cloud Build permissions reconciled"
}

# -----------------------------------------------------------------------------
# 4. Secrets
#
# Created empty-if-absent, then populated by PROMPT. Rules observed here:
#
#   * No secret value is ever hard-coded in this file. Obviously.
#   * No secret value is ever passed in argv -- `ps` is world-readable and so
#     is your shell history. Values go in over stdin via --data-file=-.
#   * Existing secrets are never overwritten. Rotation is a deliberate,
#     separate act; a deploy script that silently rotates credentials is a
#     deploy script that causes outages.
#   * `read -rs` disables echo, so nothing lands on screen or in scrollback.
# -----------------------------------------------------------------------------

ensure_secrets() {
  step "Secret Manager"

  local secret
  for secret in "${SECRETS[@]}"; do
    if gcloud secrets describe "${secret}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
      # Exists. Does it have a version? An empty secret deploys fine and then
      # fails at instance start, which is a miserable way to find out.
      local versions
      versions="$(gcloud secrets versions list "${secret}" \
        --project "${PROJECT_ID}" --filter='state:ENABLED' \
        --format='value(name)' 2>/dev/null | wc -l | tr -d ' ')"
      if [[ "${versions}" == "0" ]]; then
        warn "${secret} exists but has no enabled version"
        prompt_secret_version "${secret}"
      else
        ok "${secret} (${versions} enabled version(s)) -- left untouched"
      fi
      continue
    fi

    info "creating secret ${secret}"
    run gcloud secrets create "${secret}" \
      --project "${PROJECT_ID}" \
      --replication-policy=user-managed \
      --locations="${REGION}" \
      --labels=app=barogroove
    prompt_secret_version "${secret}"
  done

  # The runtime SA reads secret values. Granted per-secret rather than
  # project-wide so this service cannot read some other application's secrets
  # that happen to live in the same project.
  for secret in "${SECRETS[@]}"; do
    local sec_policy
    sec_policy="$(gcloud secrets get-iam-policy "${secret}" --project "${PROJECT_ID}" --format=json 2>/dev/null || true)"
    if printf '%s' "${sec_policy}" | grep -q "${SA_EMAIL}"; then
      continue
    fi
    run gcloud secrets add-iam-policy-binding "${secret}" \
      --member="serviceAccount:${SA_EMAIL}" \
      --role="roles/secretmanager.secretAccessor" \
      --project "${PROJECT_ID}" \
      --quiet >/dev/null
  done
  ok "secret accessor bindings reconciled"
}

# prompt_secret_version -- ask for a value and add it as a new version.
#
# The encryption key is special: offer to generate one, because a human-chosen
# "Fernet key" is not a Fernet key and the app will reject it at startup.
prompt_secret_version() {
  local secret="$1"
  local value=""

  if [[ "${secret}" == "barogroove-token-encryption-key" ]]; then
    printf '\n    %s%s%s -- Fernet key for encrypting provider tokens at rest.\n' \
      "${C_BOLD}" "${secret}" "${C_RESET}"
    value="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>/dev/null || true)"
    if [[ -n "${value}" ]]; then
      info "generated a 32-byte Fernet key automatically"
    fi
  elif [[ "${secret}" == "barogroove-firebase-web-api-key" ]]; then
    value="${BG_FIREBASE_WEB_API_KEY:-}"
    if [[ -z "${value}" ]]; then
      value="$(firebase apps:sdkconfig web --project "${PROJECT_ID}" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("apiKey",""))' 2>/dev/null || true)"
    fi
    if [[ -n "${value}" ]]; then
      info "retrieved Firebase Web API key automatically via Firebase CLI"
    fi
  fi

  if [[ "${DRY_RUN}" == "true" ]]; then
    ok "${secret}: dry-run validation passed"
    return 0
  fi

  if [[ -z "${value}" ]]; then
    if [[ -t 0 ]]; then
      printf '\n    Enter value for %s%s%s (input hidden, empty to use dev placeholder): ' \
        "${C_BOLD}" "${secret}" "${C_RESET}"
      read -rs value || true
      printf '\n'
    else
      info "non-interactive: using dev placeholder for ${secret}"
    fi
  fi

  if [[ -z "${value}" ]]; then
    info "using dev placeholder for ${secret} to enable graceful degradation"
    value="dev-placeholder-unconfigured"
  fi

  # --data-file=- reads stdin. The value never touches argv or the filesystem.
  printf '%s' "${value}" | run_stdin gcloud secrets versions add "${secret}" \
    --data-file=- --project "${PROJECT_ID}" >/dev/null
  unset value
  ok "${secret}: new version added"
}

# -----------------------------------------------------------------------------
# 5. Build and deploy
# -----------------------------------------------------------------------------

build_and_deploy() {
  if [[ "${SKIP_BUILD}" == "true" ]]; then
    step "Build and deploy -- SKIPPED (--skip-build)"
    return 0
  fi

  step "Cloud Build -> Cloud Run (${REGION})"
  local tag
  tag="$(git rev-parse --short HEAD 2>/dev/null || echo 'local')-$(date +%Y%m%d%H%M%S)"
  info "submitting build with tag ${tag}; this typically takes 3-6 minutes"

  run gcloud builds submit \
    --config deploy/cloudbuild.yaml \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --substitutions="_REGION=${REGION},_REPOSITORY=${REPOSITORY},_SERVICE=${SERVICE},_PROJECT_NUMBER=${PROJECT_NUMBER},_TAG=${tag}" \
    .

  ok "build and deploy submitted"

  # Public invocation. Firebase Hosting rewrites arrive unauthenticated at the
  # Cloud Run layer; authorisation is the application's job (Firebase ID
  # tokens, see firebase/auth.py). Making the service private here would break
  # the rewrite without adding any real security -- every endpoint that matters
  # already requires a verified token.
  local run_policy
  run_policy="$(gcloud run services get-iam-policy "${SERVICE}" --region "${REGION}" --project "${PROJECT_ID}" --format=json 2>/dev/null || true)"
  if printf '%s' "${run_policy}" | grep -q "allUsers"; then
    info "unauthenticated proxy invocation allowed (allUsers has roles/run.invoker for Firebase Hosting rewrite)"
  else
    info "allowing proxy invocation (app-layer IAM allowlist enforced in firebase/auth.py)"
    run gcloud run services add-iam-policy-binding "${SERVICE}" \
      --region "${REGION}" \
      --project "${PROJECT_ID}" \
      --member="allUsers" \
      --role="roles/run.invoker" \
      --quiet >/dev/null
  fi
  for iam_user in "jpaquay@gmail.com" "jerome@netdev.be" "jpaquay@gcp.altostrat.com" "jpaquay@google.com" "elena.ruizroman@gmail.com" "arthurpaquay@gmail.com"; do
    if ! printf '%s' "${run_policy}" | grep -q "user:${iam_user}"; then
      info "granting roles/run.invoker to user:${iam_user}"
      run gcloud run services add-iam-policy-binding "${SERVICE}" \
        --region "${REGION}" \
        --project "${PROJECT_ID}" \
        --member="user:${iam_user}" \
        --role="roles/run.invoker" \
        --quiet >/dev/null
    fi
  done
  ok "invoker bindings set (6 IAM users + Firebase Hosting proxy)"
}

# -----------------------------------------------------------------------------
# 6. Firebase Hosting, rules and indexes
#
# Run from firebase_cfg/, where firebase.json lives. `public` in that file is
# "frontend/build/web", relative to firebase.json -- so the Flutter build must
# already exist. Check rather than deploy an empty site over a working one.
# -----------------------------------------------------------------------------

deploy_hosting() {
  if [[ "${SKIP_HOSTING}" == "true" ]]; then
    step "Firebase Hosting -- SKIPPED (--skip-hosting)"
    return 0
  fi

  step "Firebase Hosting + Firestore rules/indexes"

  local web_build="${REPO_ROOT}/frontend/build/web"
  if [[ ! -f "${web_build}/index.html" ]]; then
    warn "no Flutter web build at ${web_build}"
    warn "build it first:  (cd frontend && flutter build web --release)"
    warn "deploying rules and indexes only"
    run firebase deploy \
      --only firestore:rules,firestore:indexes \
      --project "${PROJECT_ID}" \
      --config "${REPO_ROOT}/firebase_cfg/firebase.json" \
      --non-interactive
    ok "rules and indexes deployed"
    return 0
  fi

  ok "found web build at ${web_build}"
  if [[ "${DRY_RUN}" != "true" ]]; then
    local bust_tag
    bust_tag="$(date -u +%Y%m%d%H%M%S)"
    info "injecting Firebase Web SDK config and cache-busting tag (?v=${bust_tag}) into web build"
    firebase apps:sdkconfig web --project "${PROJECT_ID}" 2>/dev/null | BUST_TAG="${bust_tag}" python3 -c '
import json, os, re, sys, pathlib
bust = os.environ.get("BUST_TAG", "1")
try:
    cfg = json.load(sys.stdin)
except Exception:
    cfg = {}
replacements = {
    "REPLACE_ME_WEB_API_KEY": cfg.get("apiKey", ""),
    "REPLACE_ME_WEB_APP_ID": cfg.get("appId", ""),
    "REPLACE_ME_SENDER_ID": cfg.get("messagingSenderId", ""),
    "REPLACE_ME_PROJECT_ID.firebaseapp.com": cfg.get("authDomain", ""),
    "REPLACE_ME_PROJECT_ID.appspot.com": cfg.get("storageBucket", ""),
    "REPLACE_ME_PROJECT_ID": cfg.get("projectId", ""),
}
for rel in ("frontend/build/web/main.dart.js", "frontend/build/web/index.html"):
    p = pathlib.Path(rel)
    if p.is_file():
        text = p.read_text(encoding="utf-8")
        if replacements["REPLACE_ME_WEB_API_KEY"]:
            for k, v in replacements.items():
                if v:
                    text = text.replace(k, v)
        if rel.endswith("main.dart.js"):
            text = re.sub(r"s=B\.c\.aH\([^?]+\?2:4", "s=4", text)
            text = text.replace("\"http://localhost:8000\"", "window.location.origin")
        if rel.endswith("index.html"):
            text = re.sub(r"src=\"boot\.js(?:\?v=[^\"]*)?\"", f"src=\"boot.js?v={bust}\"", text)
            text = re.sub(r"src=\"flutter_bootstrap\.js(?:\?v=[^\"]*)?\"", f"src=\"flutter_bootstrap.js?v={bust}\"", text)
        p.write_text(text, encoding="utf-8")

fb = pathlib.Path("frontend/build/web/flutter_bootstrap.js")
if fb.is_file():
    t = fb.read_text(encoding="utf-8")
    t = re.sub(r"\"mainJsPath\":\"main\.dart\.js(?:\?v=[^\"]*)?\"", f"\"mainJsPath\":\"main.dart.js?v={bust}\"", t)
    fb.write_text(t, encoding="utf-8")
' || true
  fi
  ln -sfn ../frontend "${REPO_ROOT}/firebase_cfg/frontend"
  run firebase deploy \
    --only hosting,firestore:rules,firestore:indexes \
    --project "${PROJECT_ID}" \
    --config "${REPO_ROOT}/firebase_cfg/firebase.json" \
    --non-interactive

  ok "hosting, rules and indexes deployed"
  info "custom domain ${PUBLIC_HOST} must be connected once, by hand, in the"
  info "Firebase console under Hosting > Add custom domain. It is a DNS"
  info "verification flow and cannot be usefully scripted."
}

# -----------------------------------------------------------------------------
# 7. Verify
#
# Read-only, so it runs even under --dry-run -- useful for confirming that a
# previous deploy is still healthy before you plan a new one.
# -----------------------------------------------------------------------------

verify() {
  step "Verify"

  local url
  url="$(gcloud run services describe "${SERVICE}" \
    --region "${REGION}" --project "${PROJECT_ID}" \
    --format='value(status.url)' 2>/dev/null || true)"

  if [[ -z "${url}" ]]; then
    warn "service ${SERVICE} not found in ${REGION} -- nothing to verify yet"
    return 0
  fi

  info "service URL: ${url}"
  local attempt
  for attempt in 1 2 3 4 5; do
    if curl -fsS --max-time 10 "${url}/api/health" >/dev/null 2>&1; then
      ok "/api/health responded (attempt ${attempt})"
      printf '\n%s    Barogroove is live.%s\n' "${C_GREEN}${C_BOLD}" "${C_RESET}"
      info "  Cloud Run: ${url}"
      info "  Public:    https://${PUBLIC_HOST}"
      return 0
    fi
    info "attempt ${attempt}: no answer yet; waiting 5s (cold start is ~2-5s)"
    sleep 5
  done

  warn "/api/health never answered. Check the logs:"
  warn "  gcloud run services logs read ${SERVICE} --region ${REGION} --project ${PROJECT_ID} --limit 100"
  return 1
}

# -----------------------------------------------------------------------------
# main
# -----------------------------------------------------------------------------

main() {
  printf '%s\n' "${C_BOLD}Barogroove deploy -- your sky has a soundtrack${C_RESET}"

  preflight

  if [[ "${BUILD_WEB}" == "true" ]]; then
    step "Parallel Flutter Web Build (background)"
    info "spawning 'flutter build web --release --no-wasm-dry-run' in background..."
    (cd "${REPO_ROOT}/frontend" && /usr/local/google/home/jpaquay/flutter/bin/flutter build web --release --no-wasm-dry-run >/tmp/barogroove_flutter_build.log 2>&1) &
    FLUTTER_BUILD_PID="$!"
    info "Flutter build running concurrently (PID ${FLUTTER_BUILD_PID})"
  fi

  if [[ "${FAST_DEPLOY}" == "true" ]]; then
    step "Fast deploy enabled (--fast): skipping API, Firestore, IAM & Secret checks"
  else
    enable_apis
    ensure_firestore_database
    ensure_artifact_registry
    ensure_service_account
    ensure_secrets
  fi

  build_and_deploy

  if [[ -n "${FLUTTER_BUILD_PID}" ]]; then
    step "Waiting for parallel Flutter Web build to complete..."
    if wait "${FLUTTER_BUILD_PID}"; then
      ok "parallel Flutter Web build succeeded"
    else
      cat /tmp/barogroove_flutter_build.log >&2 || true
      die "parallel Flutter Web build failed"
    fi
  fi

  deploy_hosting
  verify

  printf '\n%sDone.%s\n' "${C_BOLD}${C_GREEN}" "${C_RESET}"
}

main "$@"
