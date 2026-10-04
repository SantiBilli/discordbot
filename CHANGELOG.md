# Changelog

Notable changes are recorded here. Dates use YYYY-MM-DD.

## Unreleased

### Added

- English and Spanish READMEs and deployment guides.
- MIT license, contribution/security policies, and issue/pull request templates.
- GitHub Actions for Python tests, Docker builds, and redacted secret scans.
- Dependabot configuration for Python, GitHub Actions, and Docker dependencies.
- Architecture documentation, presentation assets, and public-release checklist.

### Existing functionality included in the first public release

- Individual YouTube playback and Spotify track metadata lookup through YouTube.
- Independent queues with up to 50 pending tracks per Discord server.
- Persistent Radio Garden playback, including empty voice channels.
- Music interruptions followed by automatic radio resumption.
- Radio stream retries and transient voice recovery.
- Radio shutdown and saved-state removal after external voice/server removal.
- Docker Compose deployment with a non-root user and persistent radio volume.

The first public release has not been tagged yet. Move this entry to a dated
`0.1.0` section when publishing the release.
