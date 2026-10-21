"""Authoritative session services after the original ASGI auth + parameter gate."""
from functools import wraps
from .catalog import CapabilityError
from .session_scope import SUPPORTED, execute_session_call

def install_session_routes(app, owner_getter):
    from fastapi import HTTPException
    from .addon import settled_thread
    if getattr(app.state, '_pc_session_routes_installed', False):
        raise ValueError('PC session boundary already installed')
    found = set()
    def wrapper(original, operation):
        @wraps(original)
        async def invoke(**arguments):
            owner = owner_getter()
            if owner is None:
                return await original(**arguments)
            body = arguments.get('body')
            if body is not None:
                body = body.model_dump(exclude_unset=True)
                body.pop('profile', None)
            query = {key: value for key, value in arguments.items()
                     if key not in {'session_id', 'profile', 'body'} and value is not None}
            try:
                return await settled_thread(execute_session_call, operation, owner.profile,
                                            arguments['session_id'], query=query, body=body)
            except CapabilityError as exc:
                raise HTTPException(status_code=exc.status, detail=exc.detail) from None
        return invoke
    for route in app.routes:
        if hasattr(route, 'dependant') and hasattr(route, 'methods'):
            for method in route.methods:
                operation = method + ' ' + route.path
                if operation in SUPPORTED:
                    route.dependant.call = wrapper(route.dependant.call, operation)
                    found.add(operation)
    if found != SUPPORTED:
        raise ValueError('include original session routes before PC boundary')
    app.state._pc_session_routes_installed = True
