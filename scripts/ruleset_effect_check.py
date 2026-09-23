"""Explicit two-call real-model comparison using synthetic, identical RAG inputs.

Each exact request is preflighted by the production adapter with a separate
two-call experiment cap; this is not a classroom-generation run.
A fresh exclusive audit file records sending before
network I/O. Existing or uncertain runs are never retried by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / "backend").is_dir():
    sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.modules.debates.generation.segments import SegmentInputSnapshot  # noqa: E402
from app.modules.debates.generation.types import SnapshotRetrievalReceipt  # noqa: E402
from app.modules.debates.playback.generation_adapter import (  # noqa: E402
    _assert_llm_provider_endpoint,
)
from app.modules.debates.teaching_rules import (  # noqa: E402
    freeze_teaching_rules,
    frozen_system_prompt,
)
from app.providers.control_repository import ProviderRepository  # noqa: E402
from app.providers.factory import llm_provider  # noqa: E402
from app.providers.llm_privacy import LLMOutboundManifestV1  # noqa: E402
from app.providers.llm_segments import SegmentLLMAdapter  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

CUSTOM = """# 本场用水决策课堂

第一轮用中文，恰好三个段落。不要介绍身份，不写一般性开场。
第一段以“决定：”开头，给出供水和生态保留的具体数值方案。
第二段以“依据：”开头，引用RAG并解释为什么这个分配符合资料中的条件。
第三段以“复核：”开头，提出一周后复核的具体指标、记录方法与调整条件。
每段只推进自己的任务，不重复前段。使用资料里的数值，不编造实测结果。
第二至第四轮维持这种具体、简洁和有依据的交流；本次只执行当前轮。
"""


def run(output: Path, *, execute: bool) -> None:
    if not execute:
        raise SystemExit("Requires --execute-real; maximum two calls, no automatic retry.")
    settings = Settings()
    if settings.llm_provider != "dashscope":
        raise SystemExit("Real provider is required; no Mock fallback.")
    disclosure = LLMOutboundManifestV1(
        field_classes=(*LLMOutboundManifestV1().field_classes, "session_discussion_memory"),
        max_attempts=1,
        repair_policy_version=None,
        repair_policy_hash=None,
    )
    provider = llm_provider(settings, outbound_manifest=disclosure)
    policy_hash = settings.provider_policy_hash_for("llm")
    policy = ProviderRepository(create_engine(settings.database_url)).get_policy_snapshot(
        policy_hash
    )
    if policy is None:
        raise SystemExit("Reviewed policy is missing.")
    _assert_llm_provider_endpoint(provider, policy)
    adapter = SegmentLLMAdapter(
        provider.config,
        provider.transport,
        tokenizer=provider.tokenizer,
        outbound_manifest=disclosure,
    )
    receipt = SnapshotRetrievalReceipt(
        snapshot_id="synthetic-snapshot",
        query_kind="viewpoint",
        query_hash="synthetic-query",
        threshold_key="strict",
        rank=1,
        score=0.8,
        chunk_id="synthetic-water-record",
        source_filename="synthetic-water.md",
        text="虚构课堂资料：村庄每天可分配100升水，共10户且人口相同。生态评估要求每天至少保留20升维持河流。各户生活用水需求相同。现有记录没有一周后的实际用水或河流监测结果。",
    )
    persona = {
        "identity": {
            "name": "River Keeper",
            "role": "流域管理者",
            "historical_or_cultural_context": "虚构村庄的水资源管理课堂角色",
        },
        "cultural_lens": ["代际责任"],
        "core_values": ["公平分配", "生态延续"],
        "initial_position": "在满足河流最低生态需要后，按公平原则分配居民用水。",
        "speaking_style": {
            "tone": "清楚平实",
            "argument_pattern": "证据到行动",
            "concession_style": "承认资料边界",
            "question_style": "询问具体条件",
        },
    }
    common = SegmentInputSnapshot.from_groups(
        topic="村庄应如何分配每日有限的水，同时保护河流？",
        language="zh",
        round_number=1,
        round_total=4,
        persona=persona,
        receipts=(receipt,),
        snapshot_id="synthetic-snapshot",
        discussion={
            "protocol": "four_round_v1",
            "self_id": "keeper",
            "agents": [
                {"id": "keeper", "name": "River Keeper"},
                {"id": "resident", "name": "Resident"},
            ],
            "question_target_id": None,
            "received_questions": [],
            "memories": [],
        },
    )
    default = freeze_teaching_rules()
    changed = freeze_teaching_rules({"zh": CUSTOM, "en": default["teaching_prompts"]["en"]})
    report = {
        "run_id": str(uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "synthetic_inputs_only": True,
        "maximum_calls": 2,
        "automatic_retries": 0,
        "maximum_reserved_cost_cny": "0",
        "user_input_sha256": hashlib.sha256(common.to_user_json().encode()).hexdigest(),
        "custom_markdown": CUSTOM,
        "cases": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)

    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for name, rules in (("default", default), ("custom", changed)):
        frozen = replace(
            common, frozen_system_prompt=frozen_system_prompt(json.dumps(rules), 1, "zh")
        )
        request = adapter.build_request(frozen)
        assert request.user_message.content == common.to_user_json()
        case = {
            "name": name,
            "request_sha256": request.request_hash,
            "system_sha256": hashlib.sha256(request.system_message.content.encode()).hexdigest(),
            "status": "sending",
            "call_count": 1,
        }
        report["cases"].append(case)
        save()
        try:
            candidate = adapter.send_accepted(request)
            result = adapter.validate_accepted(candidate)
            case.update(status="accepted", speech=result.speech)
            save()
            case.update(
                status="succeeded",
                speech=result.speech,
                paragraphs=[segment.text for segment in result.segments],
                prompt_tokens=candidate.usage.prompt_tokens,
                completion_tokens=candidate.usage.completion_tokens,
                total_tokens=candidate.usage.total_tokens,
            )
            save()
        except Exception as error:
            case.update(
                status="failed_or_uncertain",
                error_type=type(error).__name__,
                safe_error_code=getattr(error, "code", "unavailable"),
            )
            save()
            raise SystemExit("Stopped; inspect audit. No automatic retry.") from None
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-real", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output, execute=args.execute_real)
