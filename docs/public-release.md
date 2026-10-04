# Public release checklist

Maintainer notes for preparing the GitHub presentation. Committing these files
does not make the repository public. Keep the current repository/history and
complete the steps below in GitHub when ready.

## Before changing visibility

- Check the latest [CI run](https://github.com/SantiBilli/discordbot/actions/workflows/ci.yml):
  unit tests, Docker build, and secret scan must pass.
- Keep `.env`, other environment files, runtime data, and private logs out of Git.
- Review the author email shown in historical commits. Publishing the repository
  also publishes that metadata. A new commit or GitHub email setting does not
  change old commits; rewriting history is a separate decision.
- Use the [deployment checklist](deployment.md#manual-verification) to test real
  Discord audio. CI does not perform this check.
- Confirm the MIT license and copyright identity match your intended release.

## GitHub presentation

Recommended display name: **AstraMusic**. The current slug stays `discordbot` to
preserve the deployment source configuration.

Suggested About description:

> Self-hosted Discord music bot built with Python, featuring persistent 24/7 Radio Garden playback, per-server queues, and Docker deployment.

Suggested topics:

```text
discord-bot discord-py python music-bot radio-garden internet-radio
ffmpeg docker docker-compose self-hosted asyncio dokploy
```

1. In **Settings → General → Danger Zone**, change visibility to public when ready.
2. Check that the About description/topics are present. Keep the README's CI
   badge linked to the actual workflow.
3. Upload [social-preview.png](assets/social-preview.png) in the repository's
   **Settings → General → Social preview**. The image is 1280 × 640.
4. Enable **Private vulnerability reporting**, secret scanning/push protection,
   and Dependabot alerts where available in the security settings. SECURITY.md
   includes a fallback if private reporting is unavailable.
5. In your profile, use **Customize your pins** to pin this repository.

## First release and demo

After manual audio validation, publish `v0.1.0` targeting `main`. Use
[release-notes-v0.1.0.md](release-notes-v0.1.0.md) as the release text and move the
Unreleased changelog entry to a dated version section.

Capture a short real demo in your own test server: start radio, show status,
queue a song, show radio resuming, verify an empty channel, and stop playback.
Remove personal messages, tokens, and private infrastructure details. The banner
is a presentation graphic, not a screenshot of a live test.

Suggested profile description:

> Built AstraMusic, a self-hosted Discord music bot with asynchronous playback queues, persistent radio sessions, automatic recovery, and Docker deployment.

## Optional repository rename

If you later rename the slug to `astramusic`, update the local Git remote,
README clone commands/badge URLs, community links, and the Git source/webhook
configuration in Dokploy. Verify a deployment after the change. Explicit updates
keep configuration clear even where GitHub provides redirects.

References: [visibility](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility),
[social preview](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview),
[pinning](https://docs.github.com/en/account-and-profile/how-tos/profile-customization/pinning-items-to-your-profile),
[repository rename](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository).
