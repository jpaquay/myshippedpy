# Bootstrapping GitHub Actions → Google Cloud

One-time setup so `.github/workflows/deploy.yml` can deploy without a service
account key. Run these yourself, as `jerome@netdev.be`.

## Why not a JSON key

The usual recipe is `gcloud iam service-accounts keys create` and paste the JSON
into a GitHub secret. Don't. That key is a permanent, exportable credential
sitting in a system Google does not control: it never expires, it survives
anyone leaving the team, it is trivially exfiltrated by a malicious dependency
in any workflow that runs in the same repo, and nothing about its use looks
unusual in the audit log.

Workload Identity Federation replaces it with an OIDC token GitHub mints per
run, valid for minutes, that Google exchanges for a short-lived access token.
Nothing long-lived exists to steal.

## The one thing people get wrong

The attribute condition below is **load-bearing**. Without it, the pool trusts
*any* GitHub Actions OIDC token — meaning any repository on GitHub can
impersonate your deploy service account. The failure is silent: your deploys
work perfectly, and so does everyone else's.

Scope it to this repository, and re-read that line before you run it.

```bash
export PROJECT_ID=netdev-firebase
export GITHUB_REPO=jpaquay/myshippedpy          # owner/repo — check this
export REGION=europe-west1

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

gcloud services enable \
  iamcredentials.googleapis.com sts.googleapis.com \
  cloudbuild.googleapis.com run.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com \
  firestore.googleapis.com firebasehosting.googleapis.com \
  --project "$PROJECT_ID"
```

### 1. Pool and provider

```bash
gcloud iam workload-identity-pools create github \
  --project "$PROJECT_ID" --location global \
  --display-name "GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc github-oidc \
  --project "$PROJECT_ID" --location global \
  --workload-identity-pool github \
  --display-name "GitHub OIDC" \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition "assertion.repository == '${GITHUB_REPO}'"
```

That last flag is the one that matters. Omit it and the pool is open to the
world.

> Tighten further if you want deploys only from `main`:
> `--attribute-condition "assertion.repository=='${GITHUB_REPO}' && assertion.ref=='refs/heads/main'"`
> Belt and braces alongside the branch filter in the workflow, and it holds even
> if someone edits the workflow on a branch.

### 2. Deploy service account

Separate from the Cloud Run *runtime* identity (`barogroove-api@`). The deployer
can create revisions; it must not be the thing serving traffic. Compromising one
should not hand over the other.

```bash
gcloud iam service-accounts create barogroove-deployer \
  --project "$PROJECT_ID" --display-name "Barogroove CI deployer"

DEPLOYER="barogroove-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
RUNTIME="barogroove-api@${PROJECT_ID}.iam.gserviceaccount.com"

for ROLE in \
  roles/cloudbuild.builds.editor \
  roles/run.admin \
  roles/artifactregistry.writer \
  roles/firebasehosting.admin \
  roles/datastore.indexAdmin \
  roles/firebaserules.admin \
  roles/logging.viewer
do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:${DEPLOYER}" --role "$ROLE" --condition=None
done

# actAs on the RUNTIME account specifically. Project-wide actAs would let the
# deployer impersonate every service account in the project.
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:${DEPLOYER}" \
  --role roles/iam.serviceAccountUser
```

Note what is **absent**: no `secretmanager.admin` (the deployer never reads
secrets — Cloud Run resolves those at runtime as the runtime SA), no `owner`, no
`datastore.user` (it manages indexes and rules, it does not read listener data).

### 3. Let the repo impersonate it

```bash
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER" \
  --project "$PROJECT_ID" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/${GITHUB_REPO}"
```

### 4. GitHub secrets

```bash
echo "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github-oidc"
echo "$DEPLOYER"
```

Repo → Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | the `projects/…/providers/github-oidc` string |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | `barogroove-deployer@netdev-firebase.iam.gserviceaccount.com` |

Neither is secret in the cryptographic sense — they are identifiers, useless
without a token from the allowed repo. They live in secrets to keep
infrastructure names out of a public repo.

### 5. Environment protection

Settings → Environments → **production**. Add yourself as a required reviewer,
and restrict the deployment branch to `main`.

Both deploy jobs declare `environment: production`, so the run will pause for
approval before it spends anything. Worth having on a pipeline that can write to
real users' Spotify accounts.

### 6. Branch protection

Settings → Branches → `main`: require the **CI** workflow to pass before merge.
`deploy.yml` re-runs the tests in its `gate` job anyway, but that is the last
line rather than the first.

## Verifying

Push a trivial commit to `main`. The run should:

1. pause for approval at `production`;
2. resolve the project number and confirm Firestore is in `europe-west1`;
3. build and roll out a Cloud Run revision;
4. smoke test — `/healthz` 200, and **unauthenticated `/mcp` 401**;
5. deploy rules and indexes *before* Hosting;
6. confirm `bg.netdev.be` serves, and `/legacy` still says `Hello World!!`.

Step 4 is the one to watch. If unauthenticated `/mcp` ever returns 200, the
deploy fails on purpose: the tools behind that endpoint spend real listeners'
credentials.

## Rotation

Nothing to rotate — that is the point. Review annually:

- the attribute condition still names only this repository;
- the deployer still holds no role it has stopped needing;
- `roles/iam.serviceAccountUser` is still scoped to `barogroove-api@` alone.
