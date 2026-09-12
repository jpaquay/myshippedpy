# Barogroove — service accounts and IAM

Two identities matter. One runs the container, one builds it. Neither is a
project editor, and neither ever should be.

Region for every resource: **`europe-west1`**.

---

## 1. The runtime identity

`barogroove-api@PROJECT_ID.iam.gserviceaccount.com`

This is the identity the Cloud Run container runs as. It is the identity that
reads your users' encrypted Spotify tokens out of Firestore. Scope it like it
matters, because it does.

### Create it

```bash
export PROJECT_ID="barogroove-prod"
export REGION="europe-west1"
export SA_NAME="barogroove-api"
export SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create "${SA_NAME}" \
  --project "${PROJECT_ID}" \
  --display-name="Barogroove API runtime" \
  --description="Least-privilege runtime identity for the Cloud Run service"
```

### Roles, and why each one

| Role | Why it is required | What breaks without it |
|---|---|---|
| `roles/datastore.user` | Read and write Firestore documents. This is the app's entire persistence layer: profiles, forges, feedback, the almanac delta, and the token vault. | Every Firestore call returns `PERMISSION_DENIED`. The app still serves playlists — the almanac degrades to empty by design — but nothing is ever remembered. |
| `roles/secretmanager.secretAccessor` | Read secret **values** at instance start and runtime. Cloud Run resolves `secretKeyRef` env vars using this identity before the container starts. | The instance does not start at all. Cloud Run treats a failed env-var secret resolution as a fatal startup error, so the revision never becomes ready. |
| `roles/secretmanager.secretVersionManager` | Write new secret versions (`add_secret_version`) when an administrator/user configures live Spotify or Last.fm API credentials directly through the in-app pairing setup UI. Does not allow deleting secrets (`secretmanager.admin` is withheld). | Submitting live OAuth credentials in the pairing setup UI fails with `PERMISSION_DENIED`. |
| `roles/firebaseauth.viewer` | Let the Admin SDK verify Firebase ID tokens and look up user records. Signature verification itself is offline against Google's public certs, but the SDK also reads project configuration, and `check_revoked=True` (should you ever enable it) needs the Auth backend. | Token verification falls back to the pure-JWT path in `firebase/auth.py`, which still works. This role buys you revocation checks and clearer errors, not basic function. Grant it anyway; the alternative is a fallback path nobody tests. |
| `roles/logging.logWriter` | Write structured logs to Cloud Logging. | Logs vanish. You will find out during your first incident, which is the worst possible time. |
| `roles/monitoring.metricWriter` | Write custom metrics — forge latency, upstream failure rates, degradation-ledger counts. | No dashboards, no alerts. |
| `roles/cloudtrace.agent` | Write trace spans. A forge fans out to several upstreams; traces are how you find which one is slow. | No distributed tracing. Debugging a slow forge becomes guesswork with a stopwatch. |

```bash
for role in \
  roles/datastore.user \
  roles/secretmanager.secretAccessor \
  roles/secretmanager.secretVersionManager \
  roles/firebaseauth.viewer \
  roles/logging.logWriter \
  roles/monitoring.metricWriter \
  roles/cloudtrace.agent
do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${role}" \
    --condition=None
done
```

### Prefer per-secret grants

`roles/secretmanager.secretAccessor` at the project level lets this service
read **every** secret in the project — including ones belonging to unrelated
applications that happen to share it. Grant it per secret instead. It is five
extra commands and it means a compromised Barogroove container cannot read your
other apps' credentials.

```bash
for secret in \
  barogroove-token-encryption-key \
  barogroove-firebase-web-api-key \
  barogroove-lastfm-api-key \
  barogroove-spotify-client-id \
  barogroove-spotify-client-secret
do
  gcloud secrets add-iam-policy-binding "${secret}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --project "${PROJECT_ID}"
done
```

If you do this, drop the project-level `secretAccessor` binding. `deploy.sh`
currently grants both; the project-level one is the safety net for a first
deploy and should be removed once the per-secret bindings are confirmed:

```bash
gcloud projects remove-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor"
```

### Roles this identity must **not** have

| Role | Why not |
|---|---|
| `roles/editor` | The default Compute SA gets this, which is why the default Compute SA must not run this service. It can delete your Firestore database and read every secret in the project. |
| `roles/datastore.owner` | Includes index and database *administration*. The app queries data; it does not manage schemas. Index changes go through `firebase deploy`, as a reviewed config change. |
| `roles/secretmanager.admin` | Lets the runtime create, modify and **destroy** secrets. It only needs to read them. A container that can delete its own credentials is a container that can cause an outage it cannot recover from. |
| `roles/firebaseauth.admin` | Lets the runtime create, modify and delete user accounts. Barogroove never does this. Sign-up happens client-side against Identity Platform. |
| `roles/iam.serviceAccountTokenCreator` | Token impersonation. Nothing here needs it, and it is a lateral-movement primitive. |

### Attach it to the service

`deploy/cloudrun.yaml` sets `serviceAccountName`. Verify after deploy:

```bash
gcloud run services describe barogroove-api \
  --region "${REGION}" --project "${PROJECT_ID}" \
  --format='value(spec.template.spec.serviceAccountName)'
```

If this prints `PROJECT_NUMBER-compute@developer.gserviceaccount.com`, the
manifest did not apply and you are running as project editor. Fix it before
anything else.

---

## 2. The build identity

Cloud Build runs as `PROJECT_NUMBER@cloudbuild.gserviceaccount.com` (or a
custom SA on newer projects — check `gcloud builds describe` output).

| Role | Why | What breaks without it |
|---|---|---|
| `roles/artifactregistry.writer` | Push the built image to `europe-west1-docker.pkg.dev`. | The `push` step fails with `denied: permission_denied`. |
| `roles/run.admin` | Run `gcloud run services replace`. | The `deploy` step fails. Note this is admin on Cloud Run *only*, not on the project. |
| `roles/iam.serviceAccountUser` **on the runtime SA** | Deploy a service that *runs as* another identity. Google requires `actAs` on the target SA, precisely so that anyone with build access cannot silently escalate to an arbitrary identity. | `PERMISSION_DENIED: iam.serviceAccounts.actAs`. The single most common first-deploy failure, and the error message does not explain itself. |
| `roles/logging.logWriter` | Write build logs. Required when `options.logging: CLOUD_LOGGING_ONLY`. | The build fails immediately with a logging-configuration error. |

```bash
export PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
export CB_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

for role in roles/run.admin roles/artifactregistry.writer roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${CB_SA}" --role="${role}" --condition=None
done

# actAs on the runtime SA specifically — not project-wide.
gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --member="serviceAccount:${CB_SA}" \
  --role="roles/iam.serviceAccountUser" \
  --project "${PROJECT_ID}"
```

---

## 3. Public invocation

```bash
gcloud run services add-iam-policy-binding barogroove-api \
  --region "${REGION}" --project "${PROJECT_ID}" \
  --member="allUsers" --role="roles/run.invoker"
```

This looks alarming. It is correct, and here is the reasoning.

Firebase Hosting rewrites arrive at Cloud Run **unauthenticated** — Hosting
does not mint an identity token on your behalf. So the service has to accept
anonymous connections at the transport layer or the rewrite returns 403 for
everyone.

Authorisation happens one layer up, in the application: every endpoint that
touches user data depends on `firebase.auth.current_user`, which verifies a
Firebase ID token against Google's public certificates and 401s otherwise. The
only routes reachable without a token are `/healthz` (dependency-free by
design) and the OpenAPI schema.

"Public at the network layer, authenticated at the application layer" is the
standard Firebase Hosting + Cloud Run posture. If that trade is unacceptable
for your threat model, the alternative is a global external Application Load
Balancer with IAP in front of Cloud Run — more control, considerably more
moving parts, and a monthly bill for the load balancer.

---

## 4. Verifying the result

```bash
# Which roles does the runtime identity actually hold?
gcloud projects get-iam-policy "${PROJECT_ID}" \
  --flatten='bindings[].members' \
  --filter="bindings.members:serviceAccount:${SA_EMAIL}" \
  --format='table(bindings.role)'

# Which identity is the service running as?
gcloud run services describe barogroove-api \
  --region "${REGION}" --project "${PROJECT_ID}" \
  --format='value(spec.template.spec.serviceAccountName)'

# Can it actually read a secret? (Runs as you, impersonating it.)
gcloud secrets versions access latest \
  --secret=barogroove-token-encryption-key \
  --project "${PROJECT_ID}" \
  --impersonate-service-account="${SA_EMAIL}" >/dev/null && echo "secret access OK"
```

The impersonation check needs `roles/iam.serviceAccountTokenCreator` **for
you**, not for the service account. Grant it to yourself temporarily, run the
check, revoke it. Do not leave it in place.

---

## 5. Key rotation

Never create service-account **key files**. Cloud Run supplies credentials
through the metadata server; a downloaded JSON key is a long-lived credential
with no expiry that ends up in a `.env`, then in a commit, then in a scraper's
index.

What does need rotating is the Fernet key in
`barogroove-token-encryption-key`. Rotating it invalidates every stored
provider token, because envelopes sealed with the old key cannot be opened with
the new one — `TokenVault.get()` logs a decryption failure and returns `None`,
and users re-run the Spotify pairing flow. That is a deliberate, recoverable
failure mode, not data loss, but it is user-visible. Do it on purpose, at a
quiet hour, and announce it.

```bash
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' \
  | gcloud secrets versions add barogroove-token-encryption-key \
      --data-file=- --project "${PROJECT_ID}"

# Env-var secrets resolve at instance start, so existing instances keep the old
# key until they are replaced. Force a new revision:
gcloud run services update barogroove-api \
  --region "${REGION}" --project "${PROJECT_ID}" \
  --update-env-vars="BG_ROTATION_STAMP=$(date +%s)"
```

The envelope's `key_id` field records an 8-hex fingerprint of the key that
sealed it, so you can tell at a glance which documents are stale without
attempting a decrypt.
