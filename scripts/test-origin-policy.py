"""Read-only proof of exact existing gateway origin guard; no server/profile imports."""
from pathlib import Path
import ast,sys,types,urllib.parse
source=Path('C:/Users/example-user/AppData/Local/hermes/hermes-agent/hermes_cli/web_server_chat.py').read_text(encoding='utf-8')
tree=ast.parse(source);node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_ws_host_origin_reason')
app=types.SimpleNamespace(state=types.SimpleNamespace(bound_host='127.0.0.1',trusted_public_hosts={'gateway.example.com'}))
server=types.ModuleType('hermes_cli.web_server');server.app=app;server._is_accepted_host=lambda host,bound,trusted:host==bound or host in trusted
sys.modules['hermes_cli']=types.ModuleType('hermes_cli');sys.modules['hermes_cli.web_server']=server
scope={'Optional':__import__('typing').Optional,'WebSocket':object,'urllib':__import__('urllib')}
exec(compile(ast.Module(body=[node],type_ignores=[]),'actual_gateway_origin_guard','exec'),scope)
check=scope['_ws_host_origin_reason']
def run(origin):return check(types.SimpleNamespace(headers={'host':'gateway.example.com','origin':origin}))
assert str(run('https://appassets.androidplatform.net')).startswith('origin_mismatch')
assert run('https://gateway.example.com') is None
print('PASS real gateway guard rejects old appassets origin, accepts exact PC HTTPS origin; no backend state changed')
