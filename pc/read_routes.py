"""Finite startup/history implementations behind original auth/parameter gates."""
from functools import wraps
from .catalog import CapabilityError
from .history import HISTORY_OPERATIONS, execute_history
from .startup import STARTUP_OPERATIONS, execute_startup


def install_read_routes(app, policy, context_getter):
    from fastapi import HTTPException
    from .addon import settled_thread
    operations = HISTORY_OPERATIONS | STARTUP_OPERATIONS
    found = set()
    if getattr(app.state, '_pc_read_routes_installed', False):
        raise ValueError('PC read boundary already installed')
    def wrapper(original, operation):
        @wraps(original)
        async def invoke(**arguments):
            context = context_getter()
            if context is None:
                return await original(**arguments)
            owner = context['owner']
            # Original FastAPI already parsed and validated the injected HTTP
            # fields. Keep only the caller's closed catalog query so ambient
            # original defaults such as profile=all never widen selection.
            query = context['call_query']
            try:
                if operation in STARTUP_OPERATIONS:
                    return await execute_startup(operation, owner, query, policy)
                return await settled_thread(execute_history, operation, owner, query, policy)
            except CapabilityError as exc:
                raise HTTPException(status_code=exc.status, detail=exc.detail) from None
        import inspect
        if inspect.iscoroutinefunction(original):
            return invoke
        @wraps(original)
        def sync_invoke(**arguments):
            if context_getter() is None:
                return original(**arguments)
            import asyncio
            return asyncio.run(invoke(**arguments))
        return sync_invoke
    for route in app.routes:
        if not hasattr(route, 'dependant') or not hasattr(route, 'methods'):
            continue
        for method in route.methods:
            operation = method + ' ' + route.path
            if operation in operations:
                route.dependant.call = wrapper(route.dependant.call, operation)
                found.add(operation)
    if found != operations:
        raise ValueError('include original startup/history routes before PC read boundary')
    # Upstream intentionally makes /api/status public, so its original gate
    # returns before attaching a Session. Delegated calls still require the
    # ORIGINAL provider scan and original verified principal, even there.
    @app.middleware('http')
    async def verify_delegated_public_read(request, call_next):
        context = context_getter()
        from hermes_cli.dashboard_auth.middleware import _path_is_public, _verify_access_token
        if context is not None and _path_is_public(request.url.path):
            from hermes_cli.dashboard_auth.cookies import read_session_cookies, read_session_provider
            from starlette.responses import JSONResponse
            access, _ = read_session_cookies(request)
            session = _verify_access_token(request, access_token=access or '',
                                            provider_hint=read_session_provider(request))
            owner = context['owner']
            if session is None or (session.provider, session.user_id) != (owner.provider, owner.user_id):
                return JSONResponse({'detail': 'delegated startup authentication required'}, status_code=401)
            request.state.session = session
        return await call_next(request)
    app.state._pc_read_routes_installed = True
