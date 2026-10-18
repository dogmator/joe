# DeepSeek profile

Joe can use Codex CLI as the tool and sandbox engine for the DeepSeek API.
This is a separate logical provider, `deepseek`; ordinary `codex` and `claude`
connections retain their accounts and settings. No additional agent SDK or
agent loop is installed.

## Local file contract

The profile lives under `${XDG_CONFIG_HOME:-~/.config}/joe/deepseek/`:

| File | Purpose |
| --- | --- |
| `credentials.json` | JSON object with an `api_key` string; never commit this file. |
| `codex/config.toml` | Isolated Codex configuration. |
| `codex/models.json` | Codex-compatible local catalogue containing the supported DeepSeek models. |

Use private directories (`0700`). On POSIX, credentials must be a regular file
owned by the current user with exactly `0600` permissions. Symlinks, special
files, oversized or malformed JSON, and invalid tokens are rejected. On
Windows, protect the file with the current user's ACL; POSIX mode and ownership
checks do not apply. `joe doctor` checks setup without a paid call. Unsafe
credentials prevent execution even if Codex is installed.

Supported model ids are `deepseek-flash` and `deepseek-v4-pro`; reasoning
levels are `low`, `high`, and `max`. Defaults are Flash and `high`. The catalogue
must match the installed Codex schema. Joe validates the supported model slugs;
CLI/schema compatibility is also required, and setup validation alone does not
prove a live API connection.

The child receives a separate `CODEX_HOME` and `DEEPSEEK_API_KEY`. Joe removes
OpenAI key and base-URL overrides from that child's environment and pins the
DeepSeek provider to `https://api.deepseek.com` using the Responses transport.
The parent environment and ordinary Codex configuration are unchanged. The key
is never placed in argv. Stream events, results, and process diagnostics redact
known secrets, including JSON-escaped and URL-encoded forms.

## Explicit roles

Select **DeepSeek** in **Agent** to use it as executor, or in **Reviewer** to
have it review another provider. Selecting a reviewer switches to REVIEW. The
executor's model and reasoning level never configure the reviewer; DeepSeek
review defaults remain Flash/high. An explicit reviewer is not silently
replaced on failure. Codex and DeepSeek may occupy the two distinct roles.

Merely mentioning DeepSeek in a prompt does not enable it. Automatic primary
and reviewer selection, fallback, classification, arbitration, compaction, and
the general `doctor --live` probe exclude manual-only providers. Explicit saved
automation choices remain explicit choices and may spend API balance.

## Errors, usage and verification

DeepSeek health is separate from Codex health. Diagnostics preserve 401, 402,
429, and 503 causes. Quota status remains `quota_unknown` without fabricated
session windows or automatic quota pauses. Insufficient balance has no guessed
reset time. A reported 429 retry delay is retained; otherwise user action is
required before retrying.

Usage is extracted from captured terminal JSONL events before final-answer
extraction. Cached input is already included in input tokens, and reasoning
output is already included in output tokens. Neither is added a second time.
Costs are dated, labelled DeepSeek API estimates using reference rates; they
are not an account balance, invoice, or spending cap.

The default pytest suite hides host provider CLIs and blocks attempts to launch
them. Tests use synthetic keys, Python JSONL subprocesses and loopback HTTP.
They cover concurrent profile isolation, REVIEW in both directions, failures,
cancellation, credential permissions, and redaction. `JOE_LIVE_SMOKE=1` is an
explicit opt-in to the separate live smoke test and can consume quota; do not
set it in ordinary CI.
