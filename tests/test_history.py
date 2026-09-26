import copy
import json

from paper_agent.history import STATE_PREFIX, model_input


def test_compaction_preserves_calls_sources_and_durable_transcript(completed):
    original = copy.deepcopy(completed.conversation)
    snapshot = {"role": "user", "content": STATE_PREFIX + "latest"}
    compact = model_input(completed, snapshot)
    assert completed.conversation == original
    assert sum(i.get("content", "").startswith(STATE_PREFIX) for i in compact if isinstance(i.get("content", ""), str)) == 1
    assert [i["call_id"] for i in compact if i.get("type") == "function_call_output"] == [
        i["call_id"] for i in original if i.get("type") == "function_call_output"]
    truncated = [json.loads(i["output"]) for i in compact if i.get("type") == "function_call_output"
                 and json.loads(i["output"]).get("notice", "").startswith("이미 근거")]
    assert truncated
    assert all(c["id"] and c["location"] and c["source_url"] and c["text_omitted"]
               for r in truncated for c in r["chunks"])
    assert len(json.dumps(compact)) < len(json.dumps(original))


def test_latest_tool_observations_and_user_answers_never_omitted(completed):
    result = next(i for i in completed.conversation if i.get("type") == "function_call_output"
                  and "untrusted_source_material" in i["output"])
    completed.event("tool_result", "freshly read", call_id=result["call_id"], name="read_chunks")
    answer = {"role": "user", "content": "추가 질문에 대한 사용자 답변: 한국어"}
    completed.conversation.append(answer)
    compact = model_input(completed, {"role": "user", "content": STATE_PREFIX + "latest"})
    assert result in compact and answer in compact


def test_unassessed_unnoted_text_is_preserved_but_assessed_text_is_reloadable(completed):
    completed.evidence.clear()
    for paper in completed.papers.values():
        paper.verdict = "unassessed"
    snapshot = {"role": "user", "content": STATE_PREFIX + "latest"}
    full = model_input(completed, snapshot)
    assert not any('"text_omitted": true' in i.get("output", "") for i in full)
    for paper in completed.papers.values():
        paper.verdict = "exclude"
    compact = model_input(completed, snapshot)
    omitted = [json.loads(i["output"]) for i in compact if '"text_omitted": true' in i.get("output", "")]
    assert omitted
    assert all(c["id"] and c["location"] and c["source_url"] for r in omitted for c in r["chunks"])
