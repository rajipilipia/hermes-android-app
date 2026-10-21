"""Pinned original runtime composition; no live injection or alternate auth server.

Normal preparation/start_server/lifespan remain authoritative. Operator must drain
exact prior generation: original siblings do not honor this project's lock.
"""
from __future__ import annotations
import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
from .catalog import SOURCE_COMMIT, CapabilityError
from .production_policy import BoundPolicy


def validate_launch(*, mode, host, port, isolated):
    if isolated is not True or mode not in {'serve', 'dashboard'}:
        raise ValueError('explicit isolated dashboard/serve launch required')
    if (not isinstance(host, str) or not host or host.strip() != host
            or any(c.isspace() or ord(c) < 32 for c in host)):
        raise ValueError('explicit bind host required')
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('valid bind port required')
    if any(name in sys.modules for name in ('hermes_cli.main', 'hermes_cli.web_server', 'tui_gateway.server')):
        raise ValueError('fresh process required; no live injection or inherited runtime')
    if os.environ.get('HERMES_DESKTOP') or os.environ.get('HERMES_DESKTOP_OWNER_NONCE'):
        raise ValueError('Desktop-owned ambient lifecycle is not this launcher')


def verify_source(upstream):
    upstream = Path(upstream).resolve(strict=True)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(upstream), *args], text=True).strip()
    if git('rev-parse', 'HEAD') != SOURCE_COMMIT:
        raise ValueError('original source revision differs from approved pin')
    if git('status', '--porcelain', '--untracked-files=no'):
        raise ValueError('original source tree is modified')
    pins = json.loads(Path(__file__).with_name('production-source-pins.json').read_text(encoding='utf-8'))
    for name, expected in pins.items():
        path = upstream / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('original source bytes differ from approved pin: ' + name)
    return upstream


@contextmanager
def runtime_lock(policy):
    """Nonblocking process-lifetime lock; retained file avoids unlink/relock races."""
    policy.validate()
    path = policy.spool / '.production-runtime.lock'
    if path.is_symlink() or (path.exists() and getattr(path.lstat(), 'st_file_attributes', 0) & 0x400):
        raise ValueError('linked runtime lock forbidden')
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError('project runtime already owns this spool; no second process') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def refuse_android_stt(adapter):
    """No approved TScriber/Gemini adapter: NEVER fall back to Whisper.

    Only Android delegation is restricted; original PC transcription is unchanged.
    DTOs are unchanged. Audio config is a denial, not fake configured readiness.
    """
    original_invoke = adapter.invoke
    async def invoke(call, owner, transport):
        if call.operation.id == 'POST /api/audio/transcribe' and adapter.dictation is None:
            raise CapabilityError(403, 'Android transcription withheld: approved TScriber/Gemini route required')
        return await original_invoke(call, owner, transport)
    adapter.invoke = invoke
    original_media = adapter.media_handler
    def media(rid, params, method):
        if method == 'desktop.audio.config' or (method == 'desktop.upload.begin'
                and isinstance(params, dict) and params.get('purpose') == 'transcribe' and adapter.dictation is None):
            from tui_gateway.transport import current_transport
            try:
                adapter.owner(current_transport(), params.get('profile'), 'audio')
            except CapabilityError as exc:
                return adapter.server._ok(rid, {'status': exc.status, 'body': {'detail': exc.detail}})
            return adapter.server._ok(rid, {'status': 403, 'body': {
                'detail': 'Android transcription withheld: approved TScriber/Gemini route required'}})
        return original_media(rid, params, method)
    adapter.media_handler = media
    if adapter.dictation is not None:
        return
    for route in adapter.app.routes:
        if getattr(route, 'path', None) == '/api/audio/transcribe' and hasattr(route, 'dependant'):
            original = route.dependant.call
            async def transcribe_guard(*args, _original=original, **kwargs):
                if adapter._delegation.get() is not None:
                    from fastapi import HTTPException
                    raise HTTPException(403, 'approved TScriber/Gemini route required')
                return await _original(*args, **kwargs)
            route.dependant.call = transcribe_guard


class Composition:
    def __init__(self, policy, upstream, dictation_factory=None):
        self.policy, self.upstream, self.adapter = policy, upstream, None
        self.web, self.original_builder, self.bootstrap = None, None, None
        self.dictation_factory = dictation_factory
        self._route_seams, self._installed_routes = (), ()
        self._build_attempted = False
        self._registrations = None
        self._owned_methods, self._owned_contracts = {}, {}
        self._added_long = frozenset()
        self._original_lifespan, self._installed_lifespan = None, None
        self.health = None

    def builder(self, *args, **kwargs):
        if self._build_attempted:
            raise ValueError('production builder must run exactly once')
        self._build_attempted = True
        web = self.web
        from hermes_cli.dashboard_auth import list_session_providers
        if not web.app.state.auth_required or not list_session_providers():
            raise ValueError('original authenticated gate with real session providers required')
        from .bootstrap import load_pinned_onboarding
        load_pinned_onboarding(self.upstream)
        from tui_gateway import server
        from tui_gateway.contracts import registry
        from hermes_cli.web_server_profiles import _resolve_profile_dir
        self.policy.bind(server, _resolve_profile_dir)
        self._registrations = server, registry, dict(server._methods), dict(registry.METHODS), server._LONG_HANDLERS
        self._original_lifespan = web.app.router.lifespan_context
        self._route_seams = tuple((route, route.dependant.call) for route in web.app.routes
                                  if hasattr(route, 'dependant'))
        try:
            from .addon import install
            self.adapter = install(web.app, server, self.policy, spool_dir=self.policy.spool)
            if self.dictation_factory is not None:
                from .dictation_integration import install as install_dictation
                install_dictation(self.adapter, self.dictation_factory)
            refuse_android_stt(self.adapter)
            from .production_bootstrap import install as install_bootstrap
            self.bootstrap = install_bootstrap(self.adapter)
            from .service_health import install as install_health
            self.health = install_health(self.adapter, self.bootstrap)
            from contextlib import asynccontextmanager
            original_lifespan = web.app.router.lifespan_context
            @asynccontextmanager
            async def lifespan(app):
                try:
                    async with original_lifespan(app) as state:
                        yield state
                finally:
                    await self.close()
            web.app.router.lifespan_context = lifespan
        finally:
            # Capture only our additive registrations, including a partial install.
            # Identity checks at teardown must not remove a later replacement.
            _, _, methods, contracts, long_handlers = self._registrations
            self._owned_methods = {name: handler for name, handler in server._methods.items()
                                   if name.startswith('desktop.') and methods.get(name) is not handler}
            self._owned_contracts = {name: contract for name, contract in registry.METHODS.items()
                                     if name.startswith('desktop.') and contracts.get(name) is not contract}
            self._added_long = frozenset(name for name in server._LONG_HANDLERS - long_handlers
                                         if name.startswith('desktop.'))
            self._installed_lifespan = web.app.router.lifespan_context
            self._installed_routes = tuple((route, original, route.dependant.call)
                                           for route, original in self._route_seams)
        return self.original_builder(*args, **kwargs)

    def _restore_registrations(self):
        if self._registrations is None:
            return
        server, registry, methods, contracts, _ = self._registrations
        for target, baseline, owned in ((server._methods, methods, self._owned_methods),
                                        (registry.METHODS, contracts, self._owned_contracts)):
            for name, installed in owned.items():
                if target.get(name) is installed:
                    if name in baseline:
                        target[name] = baseline[name]
                    else:
                        target.pop(name)
        server._LONG_HANDLERS = server._LONG_HANDLERS - self._added_long
        if self.web.app.router.lifespan_context is self._installed_lifespan:
            self.web.app.router.lifespan_context = self._original_lifespan
        for route, original, installed in self._installed_routes:
            if route.dependant.call is installed:
                route.dependant.call = original
        self._installed_routes = ()
        self._registrations = None

    async def close(self):
        if self.health is not None:
            self.health.close()
        if self.bootstrap is not None:
            self.bootstrap.close()
        try:
            if self.adapter is not None:
                await self.adapter.aclose()
        finally:
            self._restore_registrations()

    def prepare(self, original_prepare, args, headless):
        result = original_prepare(args, headless)
        from hermes_cli.dashboard_auth import list_session_providers
        if not list_session_providers():
            raise ValueError('no original session provider; interactive setup is forbidden')
        self.web = importlib.import_module('hermes_cli.web_server')
        self.original_builder = self.web._build_uvicorn_server
        self.web._build_uvicorn_server = self.builder
        return result


def preflight_profile(policy):
    """Use original pure resolvers BEFORE main's dotenv/config/logging imports."""
    from hermes_constants import get_default_hermes_root
    from hermes_cli.profiles import resolve_profile_env, get_profile_dir
    if Path(get_default_hermes_root(home=policy.root)).resolve() != policy.root:
        raise ValueError('original default root resolution differs from manifest root')
    if Path(resolve_profile_env(policy.launch_profile)).resolve() != policy.launch_home:
        raise ValueError('original launch profile resolution differs from manifest home')
    for name,home in policy._expected_homes.items():
        if Path(get_profile_dir(name)).resolve() != home:
            raise ValueError('original named profile resolution differs from manifest home')


def run(*, upstream, manifest, mode, host, port, isolated, skip_build=False, dictation_factory=None):
    policy = BoundPolicy.load(manifest, forbidden_roots=[upstream])
    validate_launch(mode=mode, host=host, port=port, isolated=isolated)
    upstream = verify_source(upstream)
    composition = Composition(policy, upstream, dictation_factory=dictation_factory)
    with runtime_lock(policy):
        # This additive entry is not an installer/updater. Original bootstrap's
        # managed-Python relaunch serializes our temporary original-main argv,
        # losing this composition/manifest and -I's project import path. Launch
        # with the operator-verified installed interpreter/dependencies instead.
        # The original dependency activation/validation still runs unchanged.
        os.environ['HERMES_DISABLE_LAZY_INSTALLS'] = '1'
        os.environ['HERMES_HOME'] = str(policy.root)
        sys.path.insert(0, str(upstream))
        original_argv = sys.argv[:]
        sys.argv = [str(upstream/'hermes_cli/main.py'), '-p', policy.launch_profile,
                    mode, '--host', host, '--port', str(port), '--no-open', '--isolated']
        if skip_build:
            sys.argv.append('--skip-build')
        main, original_prepare = None, None
        try:
            preflight_profile(policy)
            main = importlib.import_module('hermes_cli.main')
            from hermes_constants import get_process_hermes_home
            if Path(get_process_hermes_home()).resolve() != policy.launch_home:
                raise ValueError('original profile startup did not select exact launch home')
            from hermes_cli.profiles import get_active_profile_name
            if get_active_profile_name() != policy.launch_profile:
                raise ValueError('original profile startup selected unexpected profile')
            policy.validate()
            original_prepare = main._dashboard_prepare_runtime
            main._dashboard_prepare_runtime = lambda args, headless: composition.prepare(original_prepare, args, headless)
            parser = argparse.ArgumentParser()
            subs = parser.add_subparsers(dest='command', required=True)
            from hermes_cli.subcommands.dashboard import build_dashboard_parser
            build_dashboard_parser(subs, cmd_dashboard=main.cmd_dashboard,
                                   cmd_dashboard_register=lambda _: (_ for _ in ()).throw(ValueError('registration forbidden')))
            args = parser.parse_args(sys.argv[1:])
            main.cmd_dashboard(args)
            if composition.adapter is None:
                raise ValueError('original startup returned without installing composition')
            return composition
        finally:
            try:
                # Includes partial registration before install returned an adapter.
                asyncio.run(composition.close())
            finally:
                if main is not None and original_prepare is not None:
                    main._dashboard_prepare_runtime = original_prepare
                if composition.web is not None:
                    composition.web._build_uvicorn_server = composition.original_builder
                sys.argv = original_argv


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--mode', choices=('dashboard', 'serve'), required=True)
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--isolated', action='store_true', required=True)
    parser.add_argument('--skip-build', action='store_true')
    args = parser.parse_args(argv)
    try:
        run(upstream=args.upstream, manifest=args.manifest, mode=args.mode,
            host=args.host, port=args.port, isolated=args.isolated, skip_build=args.skip_build)
    except (ValueError, OSError) as exc:
        parser.exit(2, 'Production composition refused: ' + str(exc) + '\n')
