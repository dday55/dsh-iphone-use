"""Error helpers shared by every controller mixin."""
from functools import wraps
import math

from wda_client import WDAError


def fail(code, message, **details):
    raise WDAError(code, message, details=details)


def stale(message,reason,scope="page",**details):
    fail("stale_observation",message,action_executed=False,reason=reason,freshness_scope=scope,
         recovery={"next_tool":"pua_observe","next_arguments":{"mode":"both"},"same_observation_retry":False,"replay_action":False,
                   "next_step":"Inspect the current app and viewport before reusing coordinates. An observation ID is optional; changing text, numbers or screenshot pixels does not invalidate its app/viewport context."},**details)


def finite(value, name, low=0, high=10000):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not low <= value <= high:
        fail("invalid_argument", f"{name} must be a finite number in [{low}, {high}].")
    return value


def integer(value, name, low, high):
    finite(value, name, low, high)
    if not isinstance(value,int):
        fail("invalid_argument", f"{name} must be an integer.")
    return value


def action_result(function):
    @wraps(function)
    def wrapped(self,*args,**kwargs):
        before=self.accepted_actions
        try:return function(self,*args,**kwargs)
        except WDAError as error:
            if self.accepted_actions>before:
                error.details.update(action_executed=True,action_complete=False)
                if function.__name__=="swipe":
                    error.details.setdefault("attempts",self.accepted_actions-before)
                error.details.setdefault("verification_required","At least one phone action was accepted before the error. Read actual state; do not automatically replay the operation.")
            self.switch_to_coordinates(error,typing=function.__name__=="type_text")
            raise
    return wrapped
