"""Trusted source-only Gemini composition; no environment or config discovery.

The no-argument factory returns immutable bindings and one explicit shared budget.
Only this module constructs the owned service and supplies authority callbacks.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import asyncio
from typing import Callable

from .catalog import CapabilityError
from .gemini_dictation import GeminiDictation, HostBinding, RequestContext, SharedBudget


@dataclass(frozen=True)
class DictationSpec:
    bindings: tuple[HostBinding, ...]
    budget: SharedBudget
    transport_factory: Callable | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if (not isinstance(self.bindings, tuple) or
                any(not isinstance(binding, HostBinding) for binding in self.bindings) or
                not isinstance(self.budget, SharedBudget) or
                (self.transport_factory is not None and not callable(self.transport_factory))):
            raise ValueError('explicit immutable host dictation bindings and shared budget required')


def authorize(adapter, captured, permission):
    """Reauthorize the captured ACTUAL WSTransport, never a copied identity."""
    grant = adapter._delegation.get()
    if (adapter._closed or not isinstance(grant, dict) or
            getattr(grant.get('owner'), 'key', None) != captured.key):
        raise CapabilityError(403, 'dictation owner denied')
    transport = grant.get('transport')
    current = adapter.owner(transport, captured.profile, permission)
    if current.key != captured.key:
        raise CapabilityError(403, 'dictation owner denied')
    return current


def request_context(adapter, owner, transport, *, deadline, source='catalog', item=None):
    """Use admission expiry, or the minimum of it and the ORIGINAL upload TTL."""
    if deadline is None:
        raise CapabilityError(503, 'dictation admission context unavailable')
    if item is not None:
        deadline = min(deadline, item['expires'])
    try:
        task = asyncio.current_task()
    except RuntimeError:  # upload.begin runs in the original RPC worker thread
        task = None

    def owner_valid():
        if adapter._closed or getattr(transport, 'closed', True):
            return False
        if item is not None and item['transport']() is not transport:
            return False
        try:
            current = adapter.owner(transport, owner.profile, 'audio')
            return current.key == owner.key
        except Exception:
            return False

    def cancelled():
        return (adapter._closed or (task is not None and bool(task.cancelling())) or
                (item is not None and item['cancelled']))

    return RequestContext(deadline=deadline, source=source, owner_valid=owner_valid, cancelled=cancelled)


def install(adapter, factory):
    """Called after addon settlement routes. Construct exactly one owned service."""
    if not callable(factory) or adapter.dictation is not None:
        raise ValueError('one explicit trusted dictation factory required')
    spec = factory()
    if not isinstance(spec, DictationSpec):
        raise ValueError('trusted factory must return DictationSpec')

    def current_home(owner):
        # authorize validates current WS identity, full Owner and current runtime
        # resolvers via BoundPolicy before consulting its immutable exact map.
        authorize(adapter, owner, 'audio')
        return str(adapter.policy._expected_homes[owner.profile])

    adapter.dictation = GeminiDictation(bindings=spec.bindings,
        authorize=lambda owner, permission: authorize(adapter, owner, permission),
        current_home=current_home, budget=spec.budget, transport_factory=spec.transport_factory)
    from .dictation_routes import install_dictation_routes
    install_dictation_routes(adapter.app, adapter._delegation.get, adapter.dictation)
    return adapter.dictation
