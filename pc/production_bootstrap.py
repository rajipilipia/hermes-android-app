"""Authenticated, host-selected desktop owner discovery; no original imports at load."""
from __future__ import annotations

from typing import Literal

from .catalog import SOURCE_COMMIT, CapabilityError

NAME = 'desktop.bootstrap'


class Bootstrap:
    def __init__(self, adapter):
        self.adapter, self.server = adapter, adapter.server
        self._closed = False
        self._handler = self.handler
        self._registry, self._contract = None, None

    def handler(self, rid, params):
        try:
            if self._closed or self.adapter._closed:
                raise CapabilityError(410, 'desktop bootstrap is closed')
            if type(params) is not dict or params:
                raise CapabilityError(400, 'desktop.bootstrap requires empty params')
            from tui_gateway.transport import current_transport
            # owner() enforces the actual WSTransport + server-verified identity
            # seam; BoundPolicy.authorize rechecks live homes and manifest.
            owner = self.adapter.owner(current_transport(), self.adapter.policy.launch_profile, 'read')
            result = {'status': 200, 'body': {'schemaVersion': 1,
                       'sourceCommit': SOURCE_COMMIT, 'primaryProfile': owner.profile}}
        except CapabilityError as exc:
            result = {'status': exc.status, 'body': {'detail': exc.detail}}
        except Exception:
            result = {'status': 403, 'body': {'detail': 'desktop bootstrap authority cannot be verified'}}
        return self.server._ok(rid, result)

    def close(self):
        """Revoke even a retained callable; remove only this installation's entries."""
        self._closed = True
        if self.server._methods.get(NAME) is self._handler:
            self.server._methods.pop(NAME)
        if (self._registry is not None and self._contract is not None
                and self._registry.METHODS.get(NAME) is self._contract):
            self._registry.METHODS.pop(NAME)
        self.adapter = None


def install(adapter):
    """Register after original auth, policy binding and additive adapter install."""
    from tui_gateway.contracts.base import Params, Result
    from tui_gateway.contracts import registry
    if NAME in adapter.server._methods or NAME in registry.METHODS:
        raise ValueError('desktop bootstrap already registered')

    class BootstrapParams(Params):
        pass

    class BootstrapBody(Result):
        schemaVersion: Literal[1]
        sourceCommit: Literal[SOURCE_COMMIT]
        primaryProfile: str

    class BootstrapError(Result):
        detail: str

    class BootstrapReply(Result):
        status: int
        body: BootstrapBody | BootstrapError

    bootstrap = Bootstrap(adapter)
    bootstrap._registry = registry
    try:
        bootstrap._contract = registry.method(NAME, params=BootstrapParams, result=BootstrapReply,
                                             doc='Authenticated host-selected primary Desktop profile.')
        adapter.server.register_method(NAME, bootstrap._handler)
    except BaseException:
        bootstrap.close()
        raise
    return bootstrap
