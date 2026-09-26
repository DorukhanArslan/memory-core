import memory_core as memory


def test_public_api_exports_core_memory_surface():
    expected = {
        "__version__",
        "DEFAULT_CHAT_SYSTEM_PROMPT",
        "DEFAULT_MEMORY_MD_TEMPLATE",
        "MemoryConfig",
        "FeatureFlags",
        "EmbeddingProvider",
        "FakeEmbeddingProvider",
        "OpenAICompatibleEmbeddingProvider",
        "RuntimeIdentity",
        "MEMORY_CORE_RUNTIME_IDENTITY",
        "OPENCLAW_COMPAT_RUNTIME_IDENTITY",
        "MEMORY_CORE_RUNTIME_CONTEXT_CUSTOM_TYPE",
        "MemoryWorkspace",
        "MemoryFile",
        "MemoryReadResult",
        "UnsafeMemoryPathError",
        "memory_get",
        "memory_search",
        "MemoryFlushPlan",
        "MemoryFlushTriggerDecision",
        "build_memory_flush_plan",
        "build_memory_flush_plan_from_config",
        "should_run_memory_flush",
        "explain_memory_flush_trigger",
        "limit_history_turns",
        "get_history_limit_from_session_key",
        "normalize_assistant_replay_content",
        "repair_tool_use_result_pairing",
        "resolve_runtime_context_prompt_parts",
        "strip_runtime_context_custom_messages",
        "should_preemptively_compact_before_prompt",
        "truncate_tool_result_text",
        "decide_provider_overflow_recovery",
        "LangGraphMemoryRecall",
        "MemoryChatResult",
        "MemoryChatTurn",
        "MemoryRecordResult",
        "Memory",
        "IdentityLoadError",
        "JsonlTraceSink",
        "LIVE_TURN_COMPLETED",
        "LIVE_TURN_FAILED",
        "LIVE_TURN_STARTED",
        "LiveIdentity",
        "LiveIdentityStore",
        "LiveSDKConfig",
        "LiveTurnEventType",
        "LiveTurnContext",
        "LiveTurnEvent",
        "MEMORY_RECALL_COMPLETED",
        "PROMPT_ASSEMBLED",
        "PROVIDER_EVENT",
        "PreparedLiveTurn",
        "SENTENCE",
        "SESSION_SUMMARY_COMPLETED",
        "SESSION_SUMMARY_FAILED",
        "SESSION_SUMMARY_SKIPPED",
        "SESSION_SUMMARY_STARTED",
        "SessionSummaryResult",
        "SentenceBoundaryPolicy",
        "SubjectMemory",
        "SubjectPathBuilder",
        "TEXT_DELTA",
        "TraceSink",
        "UnknownIdentityFilePolicy",
        "format_memory_context",
        "initialize_memory_core_workspace",
    }

    assert expected.issubset(set(memory.__all__))
    for name in expected:
        assert hasattr(memory, name)


def test_public_api_can_build_workspace_and_flush_plan(tmp_path):
    workspace = memory.MemoryWorkspace(tmp_path)
    plan = memory.build_memory_flush_plan(
        workspace_dir=tmp_path,
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
    )

    assert workspace.root == tmp_path
    assert plan.relative_path == "memory/2026-05-03.md"


def test_public_api_replay_helpers_are_callable():
    cleaned = memory.normalize_assistant_replay_content(
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "NO_REPLY"},
        ]
    )
    repaired = memory.repair_tool_use_result_pairing(
        [
            {
                "role": "assistant",
                "content": [{"type": "toolCall", "id": "call_1", "name": "read", "arguments": {}}],
            }
        ],
        missing_tool_result_text="aborted",
    )

    assert cleaned == [{"role": "user", "content": "hello"}]
    assert repaired.messages[1]["toolCallId"] == "call_1"


def test_public_api_exports_workspace_bootstrap_surface(tmp_path):
    expected = {
        "ContextFile",
        "DEFAULT_WORKSPACE_LAYOUT",
        "MEMORY_CORE_WORKSPACE_LAYOUT",
        "OPENCLAW_PIN_LAYOUT",
        "WorkspaceBootstrapFile",
        "WorkspaceContext",
        "WorkspaceInitResult",
        "WorkspaceLayout",
        "WorkspaceSetupState",
        "bootstrap_status",
        "build_bootstrap_context_files",
        "build_startup_context",
        "build_workspace_context",
        "initialize_agent_workspace",
        "load_workspace_bootstrap_files",
    }

    assert expected.issubset(set(memory.__all__))
    assert memory.DEFAULT_WORKSPACE_LAYOUT is memory.MEMORY_CORE_WORKSPACE_LAYOUT
    result = memory.initialize_agent_workspace(tmp_path / "ws")
    assert result.bootstrap_status == "pending"
    context = memory.build_workspace_context(tmp_path / "ws")
    assert context.files == ()


def test_public_api_exports_scored_consolidation_surface():
    expected = {
        "DeepDreamingPolicy",
        "DreamingSweepResult",
        "MemoryPromotionRun",
        "SubjectConsolidation",
        "SubjectPromotionDisabledError",
        "audit_short_term_promotion_artifacts",
        "record_daily_memory_flush",
        "record_short_term_recalls",
        "repair_short_term_promotion_artifacts",
        "resolve_deep_dreaming_policy",
        "run_dreaming_sweep",
        "run_short_term_promotion",
    }

    assert expected.issubset(set(memory.__all__))
    for name in expected:
        assert hasattr(memory, name)
    assert memory.FeatureFlags().subject_promotion is False
