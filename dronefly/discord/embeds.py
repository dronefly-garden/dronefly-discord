from functools import wraps

import discord
from pyinaturalist.models import Taxon

from dronefly.core.formatters.constants import WWW_BASE_URL
from dronefly.core.formatters.generic import TaxonFormatter

EMBED_COLOR = 0x90EE90
# From https://discordapp.com/developers/docs/resources/channel#embed-limits
MAX_EMBED_TITLE_LEN = MAX_EMBED_NAME_LEN = 256
MAX_EMBED_DESCRIPTION_LEN = 2048
MAX_EMBED_FIELDS = 25
MAX_EMBED_VALUE_LEN = 1024
MAX_EMBED_FOOTER_LEN = 2048
MAX_EMBED_AUTHOR_LEN = 256
MAX_EMBED_LEN = 6000
# It's not exactly 2**23 due to overhead, but how much less, we can't determine.
# This is a safe value that works for others.
MAX_EMBED_FILE_LEN = 8000000


def make_decorator(function):
    """Make a decorator that has arguments."""

    @wraps(function)
    def wrap_make_decorator(*args, **kwargs):
        if len(args) == 1 and (not kwargs) and callable(args[0]):
            # i.e. called as @make_decorator
            return function(args[0])
        # i.e. called as @make_decorator(*args, **kwargs)
        return lambda wrapped_function: function(wrapped_function, *args, **kwargs)

    return wrap_make_decorator


@make_decorator
def format_items_for_embed(function, max_len=MAX_EMBED_NAME_LEN):
    """Format items as delimited list not exceeding Discord length limits."""

    @wraps(function)
    def wrap_format_items_for_embed(*args, **kwargs):
        kwargs["max_len"] = max_len
        return function(*args, **kwargs)

    return wrap_format_items_for_embed


def make_embed(**kwargs):
    """Make a standard embed."""
    return discord.Embed(color=EMBED_COLOR, **kwargs)

def make_taxa_embed(taxon: Taxon, formatter: TaxonFormatter, description: str):
    """Make a taxon embed."""
    embed = make_embed(
        url=f"{WWW_BASE_URL}/taxa/{taxon.id}",
        title=formatter.format_title(),
        description=description,
    )
    embed.set_thumbnail(
        url=taxon.default_photo.square_url
        if taxon.default_photo
        else taxon.icon.url
    )
    return embed
