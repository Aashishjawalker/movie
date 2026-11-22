"""Provider registry: the four sites, in the order the UI shows them."""

from providers import moviesflix, movierulz, netmirror, yts

ALL = [
    netmirror.provider,
    movierulz.provider,
    moviesflix.provider,
    yts.provider,
]

BY_ID = {provider.id: provider for provider in ALL}


def get(provider_id):
    return BY_ID.get(provider_id)


def enabled(config=None):
    from config import load_config

    config = config or load_config()
    wanted = config.get("providers") or list(BY_ID)
    return [p for p in ALL if p.id in wanted]


__all__ = ["ALL", "BY_ID", "get", "enabled"]
