# Security Policy

## Supported release

Security fixes target the current `0.5.x` research release line. Earlier release-candidate snapshots may receive fixes only when the same defect affects the current line.

## Threat model

Cairn assumes external information can be hostile. Web pages, protocol documentation, governance posts, repositories, data-provider payloads, model outputs, and user-supplied files must not be trusted merely because they look authoritative.

The current application is deliberately **research-only**. It does not contain a live-order transport, signer, withdrawal-enabled key path, or wallet authority.

## Non-negotiable boundaries

Do not mount the following into an AI research worker:

- OKX private API keys;
- withdrawal credentials;
- wallet/private-key material;
- `.env` files;
- SSH keys;
- browser credential stores;
- the controller's SQLite database;
- task lease secrets;
- another analyst's blind first-pass output.

Model subprocess flags are not an OS sandbox. For adversarial research, use a dedicated OS user, container, VM, or host with explicit read-only mounts and network policy.

## Public OKX client

The `OKXPublicClient` is intentionally constrained to approved HTTPS hosts and public `/api/v5/` GET requests. Adding authenticated endpoints requires a separate architecture decision, security review, threat model, and test plan.

Do not weaken host/path restrictions for convenience, and do not add automatic cross-host fallback after a network failure.

## Secrets

Never commit secrets. `.env` is ignored. CI should use GitHub encrypted secrets only when a workflow genuinely needs them. The default test suite must remain fully deterministic and not require exchange or model credentials.

## Reporting a vulnerability

Please do **not** open a public issue for vulnerabilities that could expose credentials, execute arbitrary code, corrupt research state, or create unauthorized financial actions.

Until GitHub private vulnerability reporting is enabled for this repository, contact the repository owner privately through GitHub profile contact methods. Include:

- affected version / commit;
- reproduction steps;
- expected versus observed behavior;
- exploit preconditions;
- potential impact;
- suggested mitigation if known.

Do not include real private keys, exchange API keys, authentication tokens, or user account data in a report.

## Security-sensitive changes

Pull requests touching any future execution, authentication, secrets, deserialization, network allowlists, dependency loading, shell invocation, or state migration path require:

1. explicit threat analysis;
2. failure-mode tests;
3. rollback/recovery notes;
4. independent review before merge.

## Current safety status

Passing unit tests does not certify investment correctness or production security. Gates A–E remain separate from software test status.
