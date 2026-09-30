# Chatto 0.5-beta.10 API upgrade

## Goal and agreed behavior

Upgrade Chatto RSS Bridge to work with Chatto `0.5-beta.10`. Make the necessary
changes to the bridge's Chatto integration while preserving its documented
room commands, RSS delivery, authorization, and recovery behavior.

The existing [integration contract](../2026-09-25-room-managed-feeds/integration-contract.md)
was verified against Chatto `0.5.0-beta.6`. Before planning implementation,
verify the target release's API and compare every interface used by the bridge
with that contract and the current code. Record the exact upstream release
identifier and evidence; do not infer endpoints, payloads, or protocol changes
from the version number.

## US-1: Make the necessary changes to match the new API

As an operator, I want the bridge to support Chatto `0.5-beta.10` so that room
commands and RSS delivery continue to work after the Chatto server upgrade.

Acceptance criteria:

- The epic records a verified integration contract for the target release,
  covering bot authentication and viewer identity, user role lookup, message
  creation and thread replies, message search and room event pagination, and
  realtime subscription, mentions, and resume behavior.
- The bridge uses the target release's verified request, response, and
  realtime wire formats for all affected interfaces.
- Direct mentions in the configured room still trigger the documented
  commands, replies appear in the command's thread, and management commands
  require the sender's current membership in `BOT_BRIDGE_ROLE`. A failed or
  malformed authorization lookup denies the command.
- RSS articles still appear as root messages, and saved feeds, delivery
  history, pending posts, and command deduplication remain effective across
  restarts. Reconciliation never retries an uncertain post on incomplete
  evidence; reconnects and expired cursors retain the documented recovery
  behavior under the new API.
- Controlled fixtures matching the verified target API cover affected
  behavior and failures without network access. Automated tests never post
  to a live Chatto room or configure a live service or cron job.
- `README.md` identifies the supported Chatto version and documents any
  required changes to bot permissions, configuration, or operation.
- The required Ruff, formatting, type, and test checks pass before the
  implementation is shared.
