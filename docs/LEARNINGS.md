# Engineering Learnings & Operational Notes — `myshippedpy`

| Field | Value |
| :--- | :--- |
| **Module** | `Apps/myshippedpy` |
| **Primary Region** | `europe-west1` |
| **Author Identity** | `jpaquay+github@gmail.com` |
| **Last Audited** | `2026-11-04` |

---

## 1. Architecture & Operational Learnings

- **Documentation Standard**: Standardized on lowercase `docs/` (`docs/LEARNINGS.md`) and canonical `AGENTS.md` with relative `GEMINI.md -> AGENTS.md` and `CLAUDE.md -> AGENTS.md` symlinks under the 3-Tier Workspace Architecture.
- **Security & FinOps Baseline**: Enforces least-privilege IAM, Secret Manager credential loading, regional anchoring in `europe-west1`, and bounded query/API resource guards.
- **AI Model Baseline**: Targets `gemini-4-argon` for agentic reasoning and evaluation workflows and `gemini-3.8-live-avatar` for real-time multimodal synthesis where applicable.
