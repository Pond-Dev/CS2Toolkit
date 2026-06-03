"""Runtime wiring for normal controller mode vs derank AFK mode."""
from .afk import afk_loop
from .controller import controller_loop
from .startup import wait_before_automation


def wait_for_automation_mode(derank_afk_mode, delay_secs, wait_func=wait_before_automation):
    if derank_afk_mode:
        return
    wait_func(delay_secs)


def automation_for_mode(derank_afk_mode):
    if derank_afk_mode:
        return afk_loop, "derank_afk"
    return controller_loop, "controller"
