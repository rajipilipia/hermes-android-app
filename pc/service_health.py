"""Adapter readiness on the original public health route; no new auth surface.

Only nonsecret generation/source metadata is exposed. This proves composition
liveness, not Nous login, profile authorization or successful model execution.
"""
from __future__ import annotations

import os
import re

from .catalog import SOURCE_COMMIT


class Health:
    def __init__(self, adapter, bootstrap):
        self.adapter, self.bootstrap = adapter, bootstrap
        routes = [route for route in adapter.app.routes
                  if getattr(route, 'path', None) == '/api/health'
                  and 'GET' in getattr(route, 'methods', ())
                  and hasattr(route, 'dependant')]
        required = ('desktop.bootstrap', 'desktop.call', 'desktop.upload.begin',
                    'desktop.download.read')
        if len(routes) != 1 or any(name not in adapter.server._methods for name in required):
            raise ValueError('original health route and adapter registrations required')
        self.route = routes[0]
        self.original = self.route.dependant.call
        self.bindings = {name: adapter.server._methods[name] for name in required}
        self.closed = False
        self.generation = self._marker('HERMES_ANDROID_ADAPTER_GENERATION', 32)
        self.digest = self._marker('HERMES_ANDROID_ADAPTER_SOURCE_SHA256', 64)
        self.handler = self._response
        self.route.dependant.call = self.handler

    @staticmethod
    def _marker(name, length):
        value = os.environ.get(name, '')
        return value if re.fullmatch('[0-9a-f]{' + str(length) + '}', value) else None

    def ready(self):
        if (self.closed or self.adapter._closed or self.bootstrap._closed
                or not self.adapter.app.state.auth_required):
            return False
        if any(self.adapter.server._methods.get(name) is not handler
               for name, handler in self.bindings.items()):
            return False
        try:
            self.adapter.policy.validate()
        except Exception:
            return False
        return True

    async def _response(self, *args, **kwargs):
        result = await self.original(*args, **kwargs)
        # Preserve original liveness/version/auth fields and its public route.
        return {**result, 'androidAdapter': {
            'schemaVersion': 1, 'sourceCommit': SOURCE_COMMIT,
            'generation': self.generation, 'sourceDigest': self.digest,
            'ready': self.ready()}}

    def close(self):
        self.closed = True
        if self.route.dependant.call is self.handler:
            self.route.dependant.call = self.original


def install(adapter, bootstrap):
    return Health(adapter, bootstrap)
