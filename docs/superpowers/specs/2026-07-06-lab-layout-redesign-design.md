# Lab Layout Redesign Design

## Goal

Make the demo lab usable after adding the Live SDK task demo by replacing the cramped all-at-once layout with a mode-based workspace.

## Design

The lab keeps one page but separates the two primary workflows:

- Chat Memory mode shows the existing chat surface and the Memory Pipeline inspector.
- Live SDK Task mode shows the live task surface and a live event/latency inspector.

The top bar stays compact and owns provider controls. The main workspace becomes a two-column layout: a primary interaction column and a contextual inspector column. Lower tabs for memory files, workspace files, tools, parity, and config move below the workspace as a normal scrollable section instead of fighting the main viewport.

## Constraints

The redesign keeps existing endpoint contracts. It changes only the lab UI structure, CSS, and client-side state handling. The page must remain usable at desktop width without overlap, and tablet/mobile widths must fall back to vertical scrolling.

## Verification

Tests should prove the HTML exposes mode controls and no longer uses the previous squeezed interaction stack. CSS tests should prove the workspace is two-column and the page allows vertical scrolling. Browser verification should confirm both modes can be selected and the Live SDK stream button is actually clickable.
