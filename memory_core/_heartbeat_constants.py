"""Upstream heartbeat, monitor-scratch and automation-migration constants.

Extracted by scripts/extract_upstream_constants.py.
Generated from OpenClaw eb377ac59e6c9fd6c7705028034812becf00271b:
src/auto-reply/tokens.ts,
src/auto-reply/heartbeat.ts,
src/auto-reply/heartbeat-filter.ts,
src/auto-reply/heartbeat-tool-response.ts,
src/cron/scratch-contract.ts,
src/infra/heartbeat-runner-prompt.ts,
src/infra/heartbeat-wake.ts,
src/cron/system-owned-declaration.ts,
packages/ai/src/replay-turn-classification.ts,
src/commands/doctor-heartbeat-task-migration.ts,
src/commands/doctor-heartbeat-scratch-migration.ts.
Do not edit by hand: re-run the script; tests/integration/test_extracted_upstream_constants.py
checks these values against the source.
Template texts are str.format templates; their fields stand for upstream
template expressions (HEARTBEAT_TEMPLATE_FIELDS in the script). The doctor
texts name 'openclaw doctor'; memory_core.heartbeat_migration substitutes its own
helper names where they are shown (documented deviation).
"""

from __future__ import annotations

HEARTBEAT_TOKEN = 'HEARTBEAT_OK'
SILENT_REPLY_TOKEN = 'NO_REPLY'
HEARTBEAT_CRON_TASK_GUIDANCE = 'Recurring tasks are automations; create or change their schedules with the automations tool, not heartbeat scratch.'
HEARTBEAT_CONTEXT_PROMPT = 'Follow the heartbeat monitor scratch context when provided. Recurring tasks are automations; create or change their schedules with the automations tool, not heartbeat scratch. Do not infer or repeat old tasks from prior chats.'
HEARTBEAT_PROMPT = 'Follow the heartbeat monitor scratch context when provided. Recurring tasks are automations; create or change their schedules with the automations tool, not heartbeat scratch. Do not infer or repeat old tasks from prior chats. If nothing needs attention, reply NO_REPLY.'
HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS = "Use heartbeat_respond to report the wake outcome. Set notify=false when nothing needs the user's attention. Set notify=true with notificationText only when the user should be interrupted."
HEARTBEAT_RESPONSE_TOOL_FALLBACK_INSTRUCTIONS = "If the heartbeat_respond tool is not available in this run, reply NO_REPLY when nothing needs the user's attention; when the user should be interrupted, reply with only the alert text instead of a prose report."
HEARTBEAT_RESPONSE_TOOL_PROMPT = "Follow the heartbeat monitor scratch context when provided. Recurring tasks are automations; create or change their schedules with the automations tool, not heartbeat scratch. Do not infer or repeat old tasks from prior chats. Use heartbeat_respond to report the wake outcome. Set notify=false when nothing needs the user's attention. Set notify=true with notificationText only when the user should be interrupted. If the heartbeat_respond tool is not available in this run, reply NO_REPLY when nothing needs the user's attention; when the user should be interrupted, reply with only the alert text instead of a prose report."
HEARTBEAT_RESPONSE_TOOL_NAME = 'heartbeat_respond'
INTERNAL_WAKE_TRANSCRIPT_PROMPTS: tuple[tuple[str, str], ...] = (
    ('heartbeat', '[OpenClaw heartbeat poll]'),
    ('exec', '[OpenClaw exec completion]\nDisable automatic completion turns with tools.exec.notifyOnExit=false; check per-agent overrides. Background exec and process poll remain available.'),
    ('legacyExec', '[OpenClaw exec completion]'),
    ('cron', '[OpenClaw cron wake]'),
    ('event', '[OpenClaw session event]'),
)
DEFAULT_HEARTBEAT_EVERY = '30m'
DEFAULT_HEARTBEAT_ACK_MAX_CHARS = 300
CRON_JOB_SCRATCH_MAX_BYTES = 262144
HEARTBEAT_SKIP_NO_PENDING_EVENT = 'no-pending-event'
HEARTBEAT_TASK_PROMPT_PREFIX = 'Run the following periodic tasks (only those due based on their intervals):'
HEARTBEAT_TASKS_COMPLETION = 'After completing all due tasks, reply NO_REPLY.'
HEARTBEAT_TASKS_RESPONSE_TOOL_COMPLETION = "After completing all due tasks:\nUse heartbeat_respond to report the wake outcome. Set notify=false when nothing needs the user's attention. Set notify=true with notificationText only when the user should be interrupted."
HEARTBEAT_FILTER_TASK_TOOL_COMPLETION = 'After completing all due tasks, use heartbeat_respond'
HEARTBEAT_TASK_DECLARATION_PREFIX = 'heartbeat-task:'
HEARTBEAT_DECLARATION_PREFIX = 'heartbeat:'
STREAM_ERROR_FALLBACK_TEXT = '[assistant turn failed before producing content]'
HEARTBEAT_TASK_MIGRATION_CHECK_ID = 'core/doctor/heartbeat-task-cron-migration'
HEARTBEAT_SCRATCH_MIGRATION_CHECK_ID = 'core/doctor/heartbeat-scratch-migration'
LEGACY_HEARTBEAT_FILENAME = 'HEARTBEAT.md'
HEARTBEAT_CLAIM_INFIX = '.doctor-importing-'
CRON_JOB_SCRATCH_TOO_LARGE = 'cron scratch exceeds {max_bytes} bytes ({size_bytes} bytes provided)'
HEARTBEAT_SCRATCH_PROMPT = '{prompt}\n\nHeartbeat monitor scratch:\n{directives}'
HEARTBEAT_TASK_LINE = '- {name}: {prompt}'
HEARTBEAT_TASKS_PROMPT = 'Run the following periodic tasks (only those due based on their intervals):\n\n{task_list}\n\n{completion}'
HEARTBEAT_FILTER_TASK_REPLY_COMPLETION = 'After completing all due tasks, reply {token}.'
HEARTBEAT_TASK_MIGRATION_FIX_HINT = 'Run {command} to convert heartbeat tasks into automations.'
HEARTBEAT_TASK_INTERVAL_ERROR = 'task {name_json} interval must be greater than zero'
HEARTBEAT_TASK_FINDING_UNREADABLE = 'Agent "{agent_id}" heartbeat scratch cannot be inspected: {error}'
HEARTBEAT_TASK_FINDING_IN_SCRATCH = 'Agent "{agent_id}" has {count} heartbeat task{plural} that must become cron jobs.'
HEARTBEAT_TASK_FINDING_BLOCKED = 'Agent "{agent_id}" heartbeat tasks cannot be migrated: {error}'
HEARTBEAT_TASK_WARNING_UNREADABLE = 'Agent "{agent_id}" heartbeat scratch could not be inspected: {error}.'
HEARTBEAT_TASK_WARNING_INVALID = 'Agent "{agent_id}" heartbeat tasks were not migrated: {error}.'
HEARTBEAT_TASK_WARNING_COLLISION = 'Agent "{agent_id}" task {name_json} collides with an incompatible cron declaration; scratch was left unchanged.'
HEARTBEAT_TASK_WARNING_COMMIT_FAILED = 'Agent "{agent_id}" task migration could not be committed: {error}. Scratch and cron jobs were left unchanged.'
HEARTBEAT_TASK_WARNING_SCRATCH_CHANGED = 'Agent "{agent_id}" scratch changed during task migration; no changes were committed.'
HEARTBEAT_TASK_WARNING_JOBS_CHANGED = 'Agent "{agent_id}" cron jobs changed during task migration; no changes were committed.'
HEARTBEAT_TASK_WARNING_TIMESTAMPS = 'Agent "{agent_id}" legacy task timestamps could not be cleared after migration: {error}. Cron jobs remain authoritative and a rerun is safe.'
HEARTBEAT_TASK_CHANGE = 'Converted {count} heartbeat task{plural} into cron jobs for agent "{agent_id}".'
HEARTBEAT_TASK_DISPLAY_NAME = 'Heartbeat task: {name}'
HEARTBEAT_SCRATCH_MIGRATION_FIX_HINT = 'Run {command} to migrate HEARTBEAT.md into cron scratch.'
HEARTBEAT_SCRATCH_FINDING_LEGACY = 'Agent "{agent_id}" still stores heartbeat instructions in HEARTBEAT.md.'
HEARTBEAT_SCRATCH_FINDING_BLOCKED = 'Agent "{agent_id}" HEARTBEAT.md cannot be migrated: {error}'
HEARTBEAT_SCRATCH_ERROR_ORPHAN_CLAIM = 'both {path} and an interrupted migration claim at {claim} exist; reconcile them manually before rerunning doctor'
HEARTBEAT_SCRATCH_ERROR_STALE_CLAIM = 'an interrupted migration claim exists at {claim}; run openclaw doctor --fix to restore it'
HEARTBEAT_SCRATCH_ERROR_MULTIPLE_CLAIMS = 'multiple interrupted migration claims exist for {path}; remove or restore the stale .doctor-importing-* files manually'
HEARTBEAT_SCRATCH_ERROR_CLAIM_HELD = 'a migration claim for {path} is held by running process {pid}; wait for that doctor run to finish'
HEARTBEAT_SCRATCH_ERROR_RECREATED = 'HEARTBEAT.md was recreated during migration; the claimed original is preserved at {conflict_path}'
HEARTBEAT_SCRATCH_ERROR_RESTORE_FAILED = 'HEARTBEAT.md migration claim could not be restored from {claim}'
HEARTBEAT_SCRATCH_ERROR_ARCHIVE_COLLISION = 'heartbeat migration archive collision at {archive}'
HEARTBEAT_SCRATCH_WARNING_NOT_MIGRATED = '{path} was not migrated: {error}. Rerun doctor to retry safely.'
HEARTBEAT_SCRATCH_WARNING_NOT_REMOVED = '{path} was migrated but not removed: {error}. Rerun doctor to retry safely.'
HEARTBEAT_SCRATCH_WARNING_UNREADABLE = 'Agent "{agent_id}" HEARTBEAT.md was not migrated: {error}'
HEARTBEAT_SCRATCH_WARNING_UNSET = 'Agent "{agent_id}" scratch was explicitly unset; it was left unchanged.'
HEARTBEAT_SCRATCH_WARNING_DIFFERENT = 'Agent "{agent_id}" already has different cron scratch; it was left unchanged.'
HEARTBEAT_SCRATCH_WARNING_NOT_FINALIZED = 'Agent "{agent_id}" scratch was not finalized: {error}. Rerun doctor to retry safely.'
HEARTBEAT_SCRATCH_WARNING_ROLLBACK = 'Agent "{agent_id}" scratch changed before the migration rollback; leaving current scratch in place.'
HEARTBEAT_SCRATCH_CHANGE_MIGRATED = 'Migrated {path} into cron scratch for {monitor}.'
HEARTBEAT_SCRATCH_CHANGE_COPIED = 'Copied {path} into cron scratch for {monitor}; retained the shared legacy file because {reason}.'
HEARTBEAT_SKIP_EMPTY_SCRATCH = 'empty-heartbeat-file'
HEARTBEAT_TASK_ERROR_NO_TASKS = 'tasks: block has no complete name/interval/prompt entries'
HEARTBEAT_TASK_ERROR_INCOMPLETE = 'tasks: block contains an incomplete name/interval/prompt entry'
HEARTBEAT_TASK_DESCRIPTION = 'Migrated from heartbeat monitor scratch by openclaw doctor.'
HEARTBEAT_SCRATCH_ERROR_NOT_FILE = 'HEARTBEAT.md must be a regular file or contained symlink'
HEARTBEAT_SCRATCH_ERROR_HARDLINK = 'HEARTBEAT.md has multiple hard links; refusing automatic removal'
HEARTBEAT_SCRATCH_ERROR_ESCAPES = 'HEARTBEAT.md symlink target escapes the agent workspace'
HEARTBEAT_SCRATCH_ERROR_NOT_UTF8 = 'HEARTBEAT.md is not valid UTF-8'
HEARTBEAT_SCRATCH_ERROR_WORKSPACE_CHANGED = 'HEARTBEAT.md workspace changed after the source was read'
HEARTBEAT_SCRATCH_ERROR_CLAIM_ESCAPES = 'claimed HEARTBEAT.md target escapes the agent workspace'
HEARTBEAT_SCRATCH_ERROR_CHANGED_BEFORE_CLAIM = 'HEARTBEAT.md changed before the migration claim was acquired'
HEARTBEAT_SCRATCH_ERROR_REVERIFY = 'claimed HEARTBEAT.md could not be re-verified before finalization'
HEARTBEAT_SCRATCH_ERROR_CHANGED_WHILE_HELD = 'HEARTBEAT.md changed while the migration claim was held'
HEARTBEAT_SCRATCH_ERROR_ORIGINAL_UNVERIFIED = 'could not verify the original HEARTBEAT.md path'
HEARTBEAT_SCRATCH_ERROR_RECREATED_WHILE_HELD = 'HEARTBEAT.md was recreated while the migration claim was held'
HEARTBEAT_SCRATCH_ERROR_RESTORED_UNVERIFIED = 'restored HEARTBEAT.md could not be re-verified'
HEARTBEAT_SCRATCH_ERROR_CHANGED_AFTER_RESTORE = 'HEARTBEAT.md changed after the migration claim was restored'
HEARTBEAT_SCRATCH_ERROR_TARGET_ESCAPES = 'HEARTBEAT.md target escapes the agent workspace'
HEARTBEAT_SCRATCH_ERROR_SCRATCH_CHANGED = 'scratch changed during migration'
HEARTBEAT_SCRATCH_ERROR_VERIFY_FAILED = 'scratch verification failed after write'
HEARTBEAT_SCRATCH_REASON_OWNER_DISABLED = 'a heartbeat owner is disabled'
HEARTBEAT_SCRATCH_REASON_OWNER_SKIPPED = "another heartbeat owner's scratch was left unchanged"
