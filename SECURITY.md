# Security policy

## Supported versions

Security fixes target the latest code on `main`. Older commits and releases do
not have a separate maintenance guarantee.

## Reporting a vulnerability

Do not disclose credentials or exploitable vulnerabilities in a public issue.
Use [GitHub's private vulnerability reporting form](https://github.com/SantiBilli/discordbot/security/advisories/new)
when it is enabled. If the form is unavailable, open an issue requesting a
private contact channel **without including the vulnerability details**.

Include the affected commit, impact, reproduction steps using fictitious
credentials, and a suggested mitigation if available. Reports are reviewed on
a best-effort basis; no response-time commitment is made.

## Handling credentials

- Keep `DISCORD_TOKEN` in an ignored `.env` file or deployment secret environment.
- `.env.example` must contain placeholders only.
- Do not include `.env`, runtime state, private logs, or tokens in attachments.
- If a token is exposed, revoke/rotate it in Discord and update the deployment.
  Deleting a file from the latest commit does not remove it from Git history.
- GitHub Actions runs Gitleaks with redacted output. Enable GitHub secret scanning
  and push protection where available as additional checks.

Radio configuration contains server/channel identifiers and station preferences.
Treat the persistent volume as deployment data and keep it out of the repository.
