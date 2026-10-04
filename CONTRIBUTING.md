# Contributing to AstraMusic

Bug reports, documentation improvements, and focused pull requests are welcome.
English and Spanish are both welcome in issues. Keep technical documentation in
English and update both README translations for user-facing changes.

## Development setup

Use Python 3.12 and a virtual environment:

```bash
git clone https://github.com/SantiBilli/discordbot.git
cd discordbot
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on Linux/macOS or
`.\.venv\Scripts\Activate.ps1` in Windows PowerShell, then run:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

No Discord token or external account is needed for the automated tests. To run
the bot, copy `.env.example` to `.env`, configure your own token, and install
FFmpeg, Opus, and Deno on your system. Docker includes these playback tools and
is the recommended way to test real audio across platforms.

```bash
python bot.py
```

Use a separate Discord application/server for manual testing. Never run a second
instance with the production token. See [deployment](docs/deployment.md) for the
manual radio verification checklist.

## Making a change

1. Fork the repository and create a descriptive branch.
2. Keep the change focused. Follow the existing Python style: four-space
   indentation, explicit async lifecycle handling, and clear error messages.
3. Add or adapt behavior tests when changing queueing, persistence, cancellation,
   voice recovery, or URL validation. Avoid real provider calls in unit tests.
4. Run the test suite and `git diff --check`.
5. Update both READMEs if commands, installation, or behavior change.
6. Open a pull request explaining the problem, resulting behavior, and validation.
   Include manual audio checks when relevant.

GitHub Actions checks Python tests, the Docker build, and secrets in both Git
history and an export of tracked files. To scan history locally with
[Gitleaks](https://github.com/gitleaks/gitleaks):

```bash
gitleaks git . --redact=100
```

Keep scans scoped to versioned files; do not publish your local `.env` or its contents.

## Reporting problems

Use the issue templates. Include reproduction steps, the affected commit or
release, Python/Docker versions, and sanitized logs. Redact tokens, webhooks,
private server/channel identifiers, and personal information.
Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## Dependency changes

Review dependency updates rather than automatically merging them. In particular,
voice removal handling relies on a private flag in discord.py 2.7.1. Verify that
behavior when updating it. See [architecture](docs/architecture.md).

Contributions are distributed under the project's [MIT license](LICENSE).
