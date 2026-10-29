"""Generate/verify the finite client contract without importing upstream runtime."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
from .catalog import MAX_JSON_BYTES, MAX_REQUEST_BYTES, OPERATIONS, PROFILE, SOURCE_COMMIT, WITHHELD_OPERATIONS
from .addon import CHUNK_BYTES, DOWNLOAD_TTL, MAX_DOWNLOAD_BYTES, MAX_DOWNLOADS
from .bootstrap import ONBOARDING_SHA256
from .media import binary_contract

WS_REUSE = {
    'profiles': ['profiles.list', 'profiles.create', 'profiles.describe', 'profiles.configure', 'profiles.get_asset', 'profiles.set_asset'],
    'conversation': ['session.create', 'session.resume', 'session.activate', 'session.list', 'session.history', 'session.interrupt', 'session.branch', 'session.events.since', 'prompt.submit', 'command.dispatch', 'command.resolve', 'commands.catalog'],
    'attachments': ['image.attach_bytes', 'pdf.attach', 'file.attach', 'image.detach'],
    'model': ['model.options', 'config.get', 'config.set'],
    'tools_skills_mcp_plugins': ['tools.list', 'toolsets.list', 'tools.show', 'tools.configure', 'skills.manage', 'skills.reload', 'mcp.catalog', 'mcp.servers.list', 'mcp.servers.add', 'mcp.servers.remove', 'mcp.servers.test', 'plugins.manage', 'plugins.catalog.lookup'],
    'terminal': ['process.list', 'process.kill', 'shell.exec'],
}
# These remain normal upstream agent authority, NOT tunneled or granted by the
# desktop.call read permission. This map is source existence, not safety approval.
WS_CAUTIONS = [
    'Do not forward config.get key=full: it expands effective credentials.',
    'Do not use cli.exec as a REST fallback. Arbitrary plugin REST is unlisted.',
    'Shell/terminal/tool/plugin execution retains upstream agent authority and approvals; the REST workspace grant is not an agent sandbox.',
    'profiles.create must explicitly set mirror_credentials=false unless credential sharing is separately intended.',
    'tools.configure and some tools/learning methods do not bind an explicit profile without a live session; use supported scoped REST or an exact live owner.',
    'voice.record/voice.tts control PC microphone/playback, not Android audio.',
]
GAPS = [
    'Reviewed connection deployment to the current PC gateway: not installed or enabled.',
    'Full settings/schema/provider credential setup, custom endpoints, OAuth manager, env reveal: not renderer capabilities.',
    'Profile rename/delete/import/export/sticky-default/open-terminal not implemented by this catalog; WS profile lifecycle only partially equivalent.',
    'Dynamic plugin REST/socket APIs, Bot Mode plugin UI/commands and arbitrary plugin capability contracts require per-plugin audits.',
    'Interactive console/PTY, terminal streaming, Git mutations/review shipping/worktrees, local-model runtime management remain separate typed-host integration gates.',
    'Messaging setup/pairing, webhooks, cron create/trigger/update, maintenance/update/restart/debug-share and external communications require separate approved typed capabilities.',
    'Uploads above 25 MiB, dynamic plugin/Kanban attachment REST, media URL proxying and native Android storage/share integrations are not supplied.',
    'Bounded relay STT/TTS and file/image attachments have original-service byte transport proof with injected provider boundaries, not valid-provider semantics, real microphone/playback, streaming/live voice or renderer/device acceptance.',
    'The isolated proof covers a real subset, not all catalog services or full Android/Desktop parity.',
    'Session-bound file reads, learning/skill mutations, mkdir, provider-engine warm-up leases and opaque Git aggregate/diff/status remain explicitly withheld. See per-operation availability.',
    'Startup/sidebar/history reads have scoped isolated original-service proof, not renderer/device/live-profile acceptance. SQL source ownership scans are bounded to 20000 rows per store, 4096 connected rows, and 32 granted profiles; oversized/unavailable stores report failed reads, never successful empty history.',
    'Model picker cold-cache refresh can contact original providers and warm caches. Its bounded two-worker/eight-second foreground deadline retains worker admission until settlement; fixture proof uses only synthetic local caches with network blocked.',
    'Blocking OS/service mutation cannot be forcibly interrupted safely: cancellation/deadlines retain admission and write barriers until settlement, return uncertainty and never automatically retry; no cross-call idempotency or last-write CAS.',
]


def build(upstream):
    root = Path(upstream).resolve(strict=True)
    revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != SOURCE_COMMIT:
        raise ValueError('upstream source pin mismatch')
    files, operations = {}, []
    for operation in OPERATIONS.values():
        path = root / operation.source
        raw = path.read_bytes()
        tree = ast.parse(raw.decode('utf-8'))
        endpoint = None
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                            and dec.func.attr == operation.method.lower() and dec.args
                            and isinstance(dec.args[0], ast.Constant) and dec.args[0].value == operation.path):
                        endpoint = node
        if endpoint is None:
            raise ValueError(f'catalog path missing in pinned source: {operation.id}')
        arguments = {arg.arg for arg in endpoint.args.args + endpoint.args.kwonlyargs}
        if set(operation.query['properties']) - arguments:
            raise ValueError(f'unsupported query fields: {operation.id}')
        if operation.profile_query and 'profile' not in arguments:
            raise ValueError(f'missing original profile scope: {operation.id}')
        contract = operation.contract()
        contract['sourceHandler'] = endpoint.name
        contract['sourceLines'] = [endpoint.lineno, endpoint.end_lineno]
        files[operation.source] = hashlib.sha256(raw).hexdigest()
        operations.append(contract)
    # Check reuse names against the pinned generated OpenRPC file; no importing
    # config.get full or introspecting any live runtime/config.
    openrpc_path = 'apps/shared/src/gateway-contract.openrpc.json'
    raw_openrpc = (root / openrpc_path).read_bytes()
    openrpc = json.loads(raw_openrpc)
    names = {row['name'] for row in openrpc['methods']}
    reuse = {family: [name for name in methods if name in names] for family, methods in WS_REUSE.items()}
    missing = sorted({method for methods in WS_REUSE.values() for method in methods} - names)
    if missing:
        raise ValueError(f'WS reuse names missing: {missing}')
    files[openrpc_path] = hashlib.sha256(raw_openrpc).hexdigest()
    for source in ('tui_gateway/methods_onboarding.py', 'hermes_constants.py',
                   'hermes_cli/profiles.py', 'hermes_state.py', 'hermes_state_sessions.py',
                   'hermes_state_messages.py', 'hermes_state_timeline.py', 'hermes_state_titles.py',
                   'hermes_cli/dashboard_auth/registry.py', 'hermes_cli/dashboard_auth/middleware.py',
                   'hermes_cli/dashboard_auth/request_utils.py',
                   'hermes_state_search.py', 'hermes_state_usage.py',
                   'hermes_cli/session_listing.py', 'hermes_cli/inventory.py',
                   'hermes_cli/web_server_sessions.py', 'hermes_cli/web_server_profiles.py',
                   'hermes_cli/web_server_config.py', 'hermes_cli/config_defaults.py',
                   'hermes_cli/web_models.py', 'hermes_cli/web_server_files.py',
                   'tui_gateway/server.py', 'tui_gateway/prompt_attachments.py', 'tui_gateway/methods_prompt.py',
                   'tui_gateway/contracts/prompt_voice.py', 'tools/voice_client_config.py',
                   'tools/transcription_tools.py', 'tools/transcription_cloud.py',
                   'tools/stt_lease.py', 'tools/tts_tool_lifecycle.py',
                   'apps/desktop/src/global.d.ts', 'apps/desktop/electron/main.ts',
                   'apps/desktop/src/api/system.ts', 'apps/desktop/src/plugins/kanban/api.ts',
                   'apps/desktop/src/app/session/hooks/use-prompt-actions/index.ts',
                   'apps/desktop/src/app/session/hooks/use-prompt-actions/submit.ts',
                   'apps/desktop/src/app/chat/composer/hooks/use-mic-recorder.ts',
                   'apps/desktop/src/lib/voice-client-direct.ts', 'apps/desktop/src/lib/voice-playback.ts',
                   # Added for 925ede7: Live voice request shapes, session mutation identity.
                   'apps/desktop/src/lib/voice-live.ts', 'tools/voice_live.py', 'tools/voice_live_debug.py',
                   'apps/desktop/src/api/sessions.ts', 'apps/shared/src/session-http-mutations.ts'):
        files[source] = hashlib.sha256((root / source).read_bytes()).hexdigest()
    if files['tui_gateway/methods_onboarding.py'] != ONBOARDING_SHA256:
        raise ValueError('onboarding source hash mismatch')
    return {'schemaVersion': 2, 'profileSchema': PROFILE, 'withheldOperations': sorted(WITHHELD_OPERATIONS), 'sourceCommit': SOURCE_COMMIT, 'transport': 'authenticated upstream /api/ws JSON-RPC',
            'rpcMethod': 'desktop.call', 'requiredFields': ['operation', 'profile'],
            'requestFields': ['operation', 'profile', 'pathParams', 'query', 'body'],
            'requestAdditionalProperties': False, 'reply': {'status': 'integer HTTP status', 'body': 'JSON value'},
            'limits': {'requestBytes': MAX_REQUEST_BYTES, 'jsonResponseBytes': MAX_JSON_BYTES,
                       'downloadBytes': MAX_DOWNLOAD_BYTES, 'downloadCount': MAX_DOWNLOADS,
                       'downloadChunkBytes': CHUNK_BYTES, 'downloadTtlSeconds': DOWNLOAD_TTL, 'concurrency': 8},
            'ownership': {'principal': 'server-verified WSTransport.auth_identity; caller identity/headers forbidden',
                          'connection': 'server-generated transport identity; no caller-controlled connectionId',
                          'profile': 'required canonical name authorized by host Policy; no current/all aliases',
                          'storedSession': 'exact detail/messages/PATCH/timeline/around: complete connected-component ownership and service share one snapshot/write transaction. Lists/search/sidebar source-filter original SQL before aggregation/limits; all selects only explicit readable principal grants, never upstream raw all; no shared row cache or NULL-owner repair. Session-file forwarding remains withheld',
                          'workspace': 'host-local Windows pinned handles through I/O, final resolved sensitive checks, atomic write-text; SSH file semantics and opaque Git aggregate/content operations withheld'},
            'downloads': {'readMethod': 'desktop.download.read', 'releaseMethod': 'desktop.download.release',
                          'readParams': {'profile': 'string', 'downloadId': 'opaque string', 'offset': 'integer >=0', 'length': 'integer 1..65536'},
                          'releaseParams': {'profile': 'string', 'downloadId': 'opaque string'},
                          'descriptorFields': ['downloadId', 'byteSize', 'mimeType', 'chunkBytes', 'expiresInSeconds'],
                          'chunkFields': ['dataBase64', 'offset', 'byteSize', 'mimeType', 'eof']},
            'binaryRpc': binary_contract(),
            'operationCount': len(operations), 'operations': operations,
            'existingWsReuse': reuse, 'existingWsCautions': WS_CAUTIONS, 'remainingGates': GAPS, 'sourceSha256': files}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--upstream', required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    result = build(args.upstream)
    output = Path(__file__).with_name('capability-contract.json')
    binary_output = Path(__file__).with_name('binary-rpc-contract.json')
    binary_content = json.dumps({'sourceCommit':SOURCE_COMMIT,**result['binaryRpc']},indent=2,ensure_ascii=False)+'\n'
    if args.check:
        if binary_output.read_text(encoding='utf-8')!=binary_content:
            raise SystemExit('binary RPC contract differs from compiled schemas')
    else:
        binary_output.write_text(binary_content,encoding='utf-8',newline='\n')
    content = json.dumps(result, indent=2, ensure_ascii=False) + '\n'
    if args.check:
        if output.read_text(encoding='utf-8') != content:
            raise SystemExit('capability contract differs from compiled/source-verified catalog')
    else:
        output.write_text(content, encoding='utf-8', newline='\n')
    print(json.dumps({'verified': True, 'operationCount': result['operationCount'], 'sourceCommit': SOURCE_COMMIT,
                      'artifact': str(output), 'sha256': hashlib.sha256(content.encode()).hexdigest()}))


if __name__ == '__main__':
    main()
