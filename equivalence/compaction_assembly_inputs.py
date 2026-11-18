"""Common offline provider events and reopened session inputs for context assembly."""


def inputs():
    template = {
        "kind": "compaction-context-assembly",
        "sessionId": "assembly-reopen-demo",
        "sessionKey": "agent:main:telegram:direct:assembly-peer",
        "seedMs": 1694000000000, "attemptMs": 1694000060000,
        "model": {"api": "openai-responses", "provider": "openai", "id": "gpt-5.4",
                  "name": "OpenAI fixture", "baseUrl": "https://api.openai.com/v1", "reasoning": False,
                  "input": ["text"], "contextWindow": 128000, "maxTokens": 4096,
                  "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}},
        "users": ["Old fixture fact", "Middle turn", "Recent turn"],
        "checkpointItem": {"type": "compaction", "id": "cmp_reopen_7", "encrypted_content": "opaque-state-over-restart"},
        "checkpointTextItem": {"type": "message", "id": "msg_resume_checkpoint", "role": "assistant",
                               "status": "completed", "content": [{"type": "output_text",
                               "text": "An earlier task was summarized.", "annotations": []}]},
        "callItem": {"type": "function_call", "id": "fc_reopen_7", "call_id": "call_reopen_7", "name": "memory_get",
                     "arguments": '{"path":"MEMORY.md","from":1,"lines":1}', "status": "completed"},
        "seedResponseIds": ["resp_reopen_7", "resp_reopen_call"],
        "replyItem": {"type": "message", "id": "msg_reopen_8", "role": "assistant",
                      "status": "completed", "content": [{"type": "output_text", "text": "Ready.", "annotations": []}]},
        "attemptResponseId": "resp_reopen_8", "file": {"path": "MEMORY.md", "text": "Compaction boundary read.\n"},
        "prompt": "Use the persisted fixture result.", "historyLimit": 1,
    }
    from copy import deepcopy
    return {name: {**deepcopy(template), "checkpointAfterUser": checkpoint_index, "attemptModelId": target}
            for name, checkpoint_index, target in (("retained", 2, "gpt-5.4"),
                ("outside-window", 0, "gpt-5.4"), ("changed-model", 2, "gpt-5.4-mini"))}
