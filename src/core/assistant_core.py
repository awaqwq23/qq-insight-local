"""Local JSON-RPC core for the QQ Insight desktop test build.

The core only reads user-selected, offline plaintext SQLite snapshots. It never
writes to QQ files and never sends chat data across the network.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from local_assistant.service import AssistantService, CoreError


def response(request_id: Any, result: Any = None, error: CoreError | None = None) -> dict[str, Any]:
    if error:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": error.code, "message": str(error), "data": error.data},
        }
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def dispatch(service: AssistantService, method: str, params: dict[str, Any]) -> Any:
    methods = {
        "system.health": service.health,
        "ai.catalog": service.ai.catalog,
        "workspace.begin": service.workspace_agent.begin,
        "workspace.chat.create": service.workspace_agent.create_session,
        "workspace.chat.list": service.workspace_agent.list_sessions,
        "workspace.chat.recent": service.workspace_agent.recent_chats,
        "workspace.chat.get": service.workspace_agent.get_session,
        "workspace.chat.rename": service.workspace_agent.rename_session,
        "workspace.chat.select": service.workspace_agent.select_branch,
        "chat.settings.get": service.chat_memory.settings,
        "chat.settings.save": service.chat_memory.save_settings,
        "chat.memory.coverage": service.chat_memory.coverage,
        "chat.memory.list": service.chat_memory.view,
        "self.get": service.chat_memory.self_profile,
        "self.save": service.chat_memory.save_self,
        "self.memory": service.chat_memory.self_memories,
        "workspace.tool": service.workspace_agent.tool,
        "workspace.context.commit": service.workspace_agent.context_commit,
        "workspace.finish": service.workspace_agent.finish,
        "workspace.history": service.workspace_agent.history,
        "workspace.history.delete": service.workspace_agent.delete_history,
        "workspace.tool.error": service.workspace_agent.tool_error,
        "workspace.output.rejected": service.workspace_agent.output_rejected,
        "workspace.image.data": service.workspace_agent.image_data,
        "workspace.image.observed": service.workspace_agent.image_observed,
        "workspace.profile.request": service.workspace_agent.profile_request,
        "workspace.profile.result": service.workspace_agent.profile_result,
        "workspace.attachment.add": service.workspace_agent.add_attachment,
        "workspace.attachment.data": service.workspace_agent.attachment_data,
        "workspace.attachment.observed": service.workspace_agent.attachment_observed,
        "workspace.artifact": service.workspace_agent.materialize,
        "ai.usage.list": service.ai.ledger.list,
        "ai.pricing.apply": service.ai.ledger.reprice_unknown,
        "ai.call.reserve": service.ai.ledger.reserve_call,
        "ai.call.settle": service.ai.ledger.settle_call,
        "ai.call.reuse": service.ai.ledger.reuse,
        "ai.media.save": service.ai.save_media_result,
        "group.get": service.ai.get_group,
        "group.save": service.ai.save_group,
        "ai.budget.get": service.ai.budget,
        "ai.budget.save": service.ai.save_budget,
        "ai.prepare": service.ai.prepare,
        "ai.next": service.ai.next_chunk,
        "ai.commit": service.ai.commit_chunk,
        "ai.context": service.ai.context,
        "ai.fail": service.ai.fail,
        "ai.finish": service.ai.finish,
        "ai.resume": service.ai.resume,
        "ai.history": service.ai.history,
        "ai.history.delete": service.ai.delete_history,
        "ai.memory.list": service.ai.memories,
        "ai.memory.update": service.ai.update_memory,
        "ai.item.update": service.ai.update_item,
        "ai.schedules": service.ai.schedules,
        "source.discover": service.discover_sources,
        "source.prepare": service.prepare_source,
        "source.import": service.import_snapshot,
        "source.manual_import": service.manual_import,
        "archive.export": service.export_archive,
        "roster.export": service.export_roster,
        "roster.scope": service.roster_scope,
        "roster.cache_info": service.member_cache_info,
        "dashboard.overview": service.overview,
        "conversation.list": service.list_conversations,
        "message.list": service.list_messages,
        "message.search": service.search_messages,
        "message.context": service.message_context,
        "message.repair": service.repair_messages,
        "conversation.pin": service.pin_conversation,
        "favorite.set": service.set_favorite,
        "favorite.list": service.list_favorites,
        "media.read": service.read_media,
        "media.refresh": service.refresh_media,
        "media.configure_roots": service.configure_media_roots,
        "insights.work_digest": service.work_digest,
        "profile.save": service.save_profile,
        "profile.get": service.get_profile,
    }
    handler = methods.get(method)
    if handler is None:
        raise CoreError("METHOD_NOT_FOUND", f"Unsupported method: {method}")
    return handler(**params)


def main() -> int:
    # Electron communicates over byte pipes, not a Windows console.  Pin the
    # JSON-RPC channel to UTF-8 so database paths and message text containing
    # Chinese characters survive packaging and locale differences.
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    def progress(message: str) -> None:
        print(json.dumps({"jsonrpc": "2.0", "method": "source.progress", "params": {"message": message}}, ensure_ascii=False), flush=True)

    service = AssistantService(args.data_dir, on_progress=progress)
    for line in sys.stdin:
        request: dict[str, Any] = {}
        try:
            request = json.loads(line)
            if request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
                raise CoreError("INVALID_REQUEST", "Expected a JSON-RPC 2.0 request")
            request_id = request.get("id")
            params = request.get("params", {})
            if not isinstance(params, dict):
                raise CoreError("INVALID_PARAMS", "params must be an object")
            print(json.dumps(response(request_id, dispatch(service, request["method"], params)), ensure_ascii=False), flush=True)
        except CoreError as exc:
            print(json.dumps(response(request.get("id") if "request" in locals() else None, error=exc), ensure_ascii=False), flush=True)
        except json.JSONDecodeError:
            print(json.dumps(response(None, error=CoreError("INVALID_JSON", "Request is not valid JSON")), ensure_ascii=False), flush=True)
        except Exception as exc:  # Do not expose local paths or message data.
            print(json.dumps(response(request.get("id") if "request" in locals() else None, error=CoreError("INTERNAL_ERROR", "The local core could not complete this request")), ensure_ascii=False), flush=True)
            print(f"core error: {type(exc).__name__}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
