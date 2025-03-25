import asyncio
import functools

import anki.connect
from anki.errors import APIException as AnkiAPIException
from anki.errors import UnexpectedAPIResponse as AnkiAPIUnexpectedResponse

class BatchManager:
    def __init__(self, ac_client, auto_await=True):
        self.ac_client = ac_client
        self.actions = []
        self.futures = []
        self.deferred_results = []
        self.auto_await = auto_await

        # Monotonically increasing counter
        # to determine if a new batch needs
        # to be delivered once a result has been requested.
        self.dispatch_group = 0

    @staticmethod
    def make_request(version, action, **params):
        if params:
            return {"action": action, "params": params, "version": version}
        else:
            return {"action": action, "version": version}

    @staticmethod
    def parse_response(response):
        if len(response) != 2:
            return AnkiAPIUnexpectedResponse("Response has an unexpected number of fields")
        if "error" not in response:
            return AnkiAPIUnexpectedResponse("Response is missing required error field")
        if "result" not in response:
            return AnkiAPIUnexpectedResponse("Response is missing required result field")
        if response["error"] is not None:
            return AnkiAPIException(response["error"])
        return response["result"]

    def __getattr__(self, name):
        # This trick enables us to use the same interface between
        # the
        method = getattr(anki.connect.Client, name)
        def wrapper(*args, **params):
            return method(self, *args, **params)
        return wrapper

    def invoke(self, action, **params):
        return self.add_action(self.ac_client.version, action, **params)

    def add_action(self, version, action_name, **params):
        fut = asyncio.get_event_loop().create_future()
        result = DeferredResult(self, fut)
        self.actions.append(self.make_request(version, action_name, **params))
        self.futures.append(fut)
        self.deferred_results.append(result)
        return result

    def _handle_responses(self, responses):
        assert len(self.futures) == len(responses)
        for fut, result in zip(self.futures, responses):
            if isinstance(result, Exception):
                fut.set_exception(result)
            else:
                fut.set_result(result)
        self.futures.clear()
        self.actions.clear()

    def sync_dispatch(self):
        if not self.actions:
            return
        self.dispatch_group += 1
        responses = self.ac_client.invoke_no_batch('multi', actions=self.actions)
        responses = [self.parse_response(response) for response in responses]
        self._handle_responses(responses)

    async def async_dispatch(self):
        if not self.actions:
            return
        self.dispatch_group += 1
        responses = await self.ac_client.invoke_no_batch('multi', actions=self.actions)
        responses = [self.parse_response(response) for response in responses]
        self._handle_responses(responses)

        if self.auto_await:
            for result in self.deferred_results:
                try:
                    await result
                except AnkiAPIException as e:
                    pass
            self.deferred_results.clear()

class DeferredResult:
    def __init__(self, batcher, future):
        self._batcher = batcher
        self._future = future
        self._batcher_group = batcher.dispatch_group

    def __await__(self):
        if self._batcher_group >= self._batcher.dispatch_group:
            yield from self._batcher.async_dispatch().__await__()
        return (yield from self._future.__await__())

    @functools.cached_property
    async def async_value(self):
        if self._batcher_group >= self._batcher.dispatch_group:
            await self._batcher.async_dispatch()
        return self._future.result()

    @functools.cached_property
    def value(self):
        if self._batcher_group >= self._batcher.dispatch_group:
            self._batcher.sync_dispatch()
        return self._future.result()
