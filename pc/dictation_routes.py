"""Optional delegated ASGI seam; NOT installed by the current composition.

The parent adapter must inject dictation_context from the actual captured
transport / claimed upload and original remaining expiry. Never synthesize a
fresh upload TTL here. Existing admission, ASGI auth, schemas, mutation barrier,
claim/quota lifecycle and desktop.audio.config denial remain host obligations.
"""
from __future__ import annotations
from functools import wraps
from .gemini_dictation import GeminiDictation, RequestContext
from .policy import Owner
from .catalog import CapabilityError


def install_dictation_routes(app, context_getter, service):
    """Replace exactly one original validated POST route, not an alternate API.

    Install after the adapter's general settlement wrapper and before any
    production transcription-denial wrapper is removed/replaced. Missing service
    or private operation context NEVER restores original delegated transcription.
    """
    from fastapi import HTTPException
    routes = [route for route in app.routes
              if getattr(route, 'path', None) == '/api/audio/transcribe' and
              'POST' in getattr(route, 'methods', ()) and hasattr(route, 'dependant')]
    if len(routes) != 1 or not callable(context_getter):
        raise ValueError('one original transcription route and captured context required')
    original = routes[0].dependant.call

    @wraps(original)
    async def transcribe(**arguments):
        context = context_getter()
        if context is None:
            return await original(**arguments)
        owner = context.get('owner') if isinstance(context, dict) else None
        if not isinstance(owner, Owner) or arguments.get('profile') != owner.profile:
            raise HTTPException(403, detail='dictation owner denied')
        operation = context.get('dictation_context')
        if not isinstance(service, GeminiDictation) or not isinstance(operation, RequestContext):
            raise HTTPException(503, detail='dictation service unavailable')
        payload = arguments.get('payload')
        if hasattr(payload, 'model_dump'):
            payload = payload.model_dump(exclude_none=True)
        try:
            return await service.transcribe(owner, payload, context=operation)
        except CapabilityError as exc:
            raise HTTPException(exc.status, detail=exc.detail) from None
    routes[0].dependant.call = transcribe
