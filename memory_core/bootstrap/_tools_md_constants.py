"""Upstream TOOLS.md migration constants.

Extracted by scripts/extract_upstream_constants.py.
Generated from OpenClaw eb377ac59e6c9fd6c7705028034812becf00271b:
src/commands/doctor-tools-md-migration-content.ts,
src/commands/doctor-tools-md-migration-guidance.ts,
src/commands/doctor-tools-md-migration.ts.
Do not edit by hand: re-run the script; tests/integration/test_extracted_upstream_constants.py
checks these values against the source.
The legacy templates are upstream's retired TOOLS.md stock texts, used only to
recognise an untouched file; memory-core never seeds them.
"""

from __future__ import annotations

LEGACY_TOOLS_MD_TEMPLATE = '# TOOLS.md - Local Notes\n\nSkills define _how_ tools work. This file is for _your_ specifics \u2014 the stuff that\'s unique to your setup: camera names and locations, SSH hosts and aliases, preferred TTS voices, speaker/room names, device nicknames, anything environment-specific.\n\n## Examples\n\n```markdown\n### Cameras\n\n- living-room \u2192 Main area, 180\xb0 wide angle\n- front-door \u2192 Entrance, motion-triggered\n\n### SSH\n\n- home-server \u2192 192.168.1.100, user: admin\n\n### TTS\n\n- Preferred voice: "Nova" (warm, slightly British)\n- Default speaker: Kitchen HomePod\n```\n\n## Why Separate?\n\nSkills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.\n\n---\n\nAdd whatever helps you do your job. This is your cheat sheet.\n\n## Related\n\n- [Agent workspace](/concepts/agent-workspace)\n'
LEGACY_TOOLS_DEV_MD_TEMPLATE = '# TOOLS.md - User Tool Notes (editable)\n\nThis file is for _your_ notes about external tools and conventions. It does not define which tools exist; OpenClaw provides built-in tools internally, and skills add the rest.\n\n## Examples\n\n### imsg\n\n- Send an iMessage/SMS: describe who/what, confirm before sending.\n- Prefer short messages; avoid sending secrets.\n\n### sag\n\n- Text-to-speech: specify voice, target speaker/room, and whether to stream.\n\nAdd whatever else you want the assistant to know about your local toolchain.\n\n## Related\n\n- [TOOLS.md template](/reference/templates/TOOLS)\n'
LEGACY_TOOLS_DEV_FALLBACK = '# TOOLS.md - User Tool Notes (editable)\n\nAdd your local tool notes here.\n'
CURRENT_AGENTS_TOOLS_GUIDANCE = 'Skills define how tools work. Keep environment-specific local notes in this section.'
LEGACY_AGENTS_TOOLS_GUIDANCE_REWRITES: tuple[tuple[str, str], ...] = (
    ('Skills provide your tools. When you need one, check its `SKILL.md`. Keep local notes (camera names, SSH details, voice preferences) in `TOOLS.md`.', 'Skills define how tools work. Keep environment-specific local notes in this section.'),
    ('- Keep environment-specific notes in `TOOLS.md` (notes for skills).', "- Keep environment-specific notes in this file's `## Tools` section."),
    ('- Keep environment-specific notes in `TOOLS.md` (Notes for Skills).', "- Keep environment-specific notes in this file's `## Tools` section."),
    ('- You learn a lesson -> update `AGENTS.md`, `TOOLS.md`, or the relevant skill.', '- You learn a lesson -> update `AGENTS.md` or the relevant skill.'),
    ('- When you learn a lesson \u2192 update AGENTS.md, TOOLS.md, or the relevant skill', '- When you learn a lesson \u2192 update AGENTS.md or the relevant skill'),
    ('Skills \u63d0\u4f9b\u4f60\u7684\u5de5\u5177\u3002\u5f53\u4f60\u9700\u8981\u67d0\u4e2a\u5de5\u5177\u65f6\uff0c\u67e5\u770b\u5b83\u7684 `SKILL.md`\u3002\u5728 `TOOLS.md` \u4e2d\u4fdd\u5b58\u672c\u5730\u7b14\u8bb0\uff08\u6444\u50cf\u5934\u540d\u79f0\u3001SSH \u8be6\u60c5\u3001\u8bed\u97f3\u504f\u597d\u7b49\uff09\u3002', 'Skills \u5b9a\u4e49\u5de5\u5177\u7684\u4f7f\u7528\u65b9\u5f0f\u3002\u8bf7\u5c06\u73af\u5883\u7279\u5b9a\u7684\u672c\u5730\u7b14\u8bb0\u4fdd\u5b58\u5728\u672c\u8282\u4e2d\u3002'),
    ('\u6280\u80fd\u63d0\u4f9b\u4f60\u7684\u5de5\u5177\u3002\u5f53\u4f60\u9700\u8981\u67d0\u4e2a\u5de5\u5177\u65f6\uff0c\u67e5\u770b\u5b83\u7684 `SKILL.md`\u3002\u5728 `TOOLS.md` \u4e2d\u4fdd\u5b58\u672c\u5730\u7b14\u8bb0\uff08\u6444\u50cf\u5934\u540d\u79f0\u3001SSH \u8be6\u60c5\u3001\u8bed\u97f3\u504f\u597d\u7b49\uff09\u3002', '\u6280\u80fd\u5b9a\u4e49\u5de5\u5177\u7684\u4f7f\u7528\u65b9\u5f0f\u3002\u8bf7\u5c06\u73af\u5883\u7279\u5b9a\u7684\u672c\u5730\u7b14\u8bb0\u4fdd\u5b58\u5728\u672c\u8282\u4e2d\u3002'),
    ('- \u5728 `TOOLS.md` \u4e2d\u4fdd\u5b58\u73af\u5883\u7279\u5b9a\u7684\u7b14\u8bb0\uff08Skills \u6ce8\u610f\u4e8b\u9879\uff09\u3002', '- \u5c06\u73af\u5883\u7279\u5b9a\u7684\u7b14\u8bb0\u4fdd\u5b58\u5728\u672c\u6587\u4ef6\u7684 `## Tools` \u90e8\u5206\u3002'),
    ('- \u5c06\u73af\u5883\u76f8\u5173\u7684\u5907\u6ce8\u4fdd\u5b58\u5728 `TOOLS.md`\uff08Skills \u5907\u6ce8\uff09\u4e2d\u3002', '- \u5c06\u73af\u5883\u76f8\u5173\u7684\u5907\u6ce8\u4fdd\u5b58\u5728\u672c\u6587\u4ef6\u7684 `## Tools` \u90e8\u5206\u3002'),
    ('- \u5c06\u73af\u5883\u76f8\u5173\u7684\u5907\u6ce8\u4fdd\u5b58\u5728 `TOOLS.md`\uff08\u6280\u80fd\u5907\u6ce8\uff09\u4e2d\u3002', '- \u5c06\u73af\u5883\u76f8\u5173\u7684\u5907\u6ce8\u4fdd\u5b58\u5728\u672c\u6587\u4ef6\u7684 `## Tools` \u90e8\u5206\u3002'),
    ('- \u5f53\u4f60\u5b66\u5230\u6559\u8bad \u2192 \u66f4\u65b0 AGENTS.md\u3001TOOLS.md \u6216\u76f8\u5173 Skills \u6587\u4ef6', '- \u5f53\u4f60\u5b66\u5230\u6559\u8bad \u2192 \u66f4\u65b0 AGENTS.md \u6216\u76f8\u5173 Skills \u6587\u4ef6'),
    ('- \u5f53\u4f60\u5b66\u5230\u6559\u8bad \u2192 \u66f4\u65b0 AGENTS.md\u3001TOOLS.md \u6216\u76f8\u5173\u6280\u80fd\u6587\u4ef6', '- \u5f53\u4f60\u5b66\u5230\u6559\u8bad \u2192 \u66f4\u65b0 AGENTS.md \u6216\u76f8\u5173\u6280\u80fd\u6587\u4ef6'),
)
MIGRATED_SUBSECTION_HEADING = '### Local notes (migrated from TOOLS.md)'
