from kanka_scribe.llm import estimate_tokens, summarize


def test_summarize_single_pass_when_under_context(monkeypatch):
    calls: list[list[dict]] = []

    def fake_chat(base_url, api_key, model, messages, timeout=600.0):
        calls.append(messages)
        return "full recap"

    monkeypatch.setattr("kanka_scribe.llm.chat", fake_chat)
    out = summarize(
        "http://llm.test",
        "",
        "model",
        "short transcript",
        context_length=8192,
    )
    assert out == "full recap"
    assert len(calls) == 1
    assert "short transcript" in calls[0][1]["content"]


def test_summarize_chunks_then_merges_when_over_context(monkeypatch):
    calls: list[str] = []

    def fake_chat(base_url, api_key, model, messages, timeout=600.0):
        system = messages[0]["content"]
        user = messages[1]["content"]
        if "ONE CHUNK" in system:
            calls.append("chunk")
            # pull chunk index from user header
            return f"partial for {user.splitlines()[0]}"
        if "merging partial recaps" in system.lower() or "Partial recap" in user:
            calls.append("merge")
            return "merged final recap"
        calls.append("full")
        return "should not happen"

    monkeypatch.setattr("kanka_scribe.llm.chat", fake_chat)
    # Force multiple chunks: tiny context + long multi-paragraph transcript
    paragraphs = [f"**Speaker {i}:**\n" + ("word " * 80) for i in range(12)]
    transcript = "\n\n".join(paragraphs)
    assert estimate_tokens(transcript) > 256

    out = summarize(
        "http://llm.test",
        "key",
        "model",
        transcript,
        context_length=256,
    )
    assert out == "merged final recap"
    assert calls.count("merge") == 1
    assert calls.count("chunk") >= 2
    assert "full" not in calls
