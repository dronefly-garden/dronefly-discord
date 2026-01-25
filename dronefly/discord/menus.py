import logging
from math import floor
from typing import Any, Optional

import discord
from discord.ext import commands
from dronefly.core.clients.inat import iNatClient
from dronefly.core.formatters import TaxonListFormatter
from dronefly.core.menus import (
    CountMenu as CoreCountMenu,
    CountSource as CoreCountSource,
    TaxonMenu as CoreTaxonMenu,
    TaxonListMenu as CoreTaxonListMenu,
    TaxonListSource as CoreTaxonListSource,
    TaxonSource as CoreTaxonSource,
)
from pyinaturalist import ROOT_TAXON_ID, Taxon
from requests import HTTPError

from .embeds import make_count_embed, make_embed, make_image_embed, make_taxa_embed

logger = logging.getLogger(__name__)


class TaxonListSource(CoreTaxonListSource):
    def format_page(
        self, page: list[Taxon], page_number: int = 0, selected: Optional[int] = None
    ):
        formatter = self._taxon_list_formatter
        query_response = self.query_response
        embed = make_embed(
            title=f"{self.formatter.short_description} {query_response.obs_query_description()}"
        )
        if self._url:
            embed.url = self._url
        embed.description = formatter.format_page(page, page_number, selected)
        embed.set_footer(text=f"Page {page_number + 1}/{self.get_max_pages()}")
        return embed


class StopButton(discord.ui.Button):
    def __init__(
        self,
        style: discord.ButtonStyle,
        row: Optional[int],
    ):
        super().__init__(style=style, row=row)
        self.style = style
        self.emoji = "\N{HEAVY MULTIPLICATION X}\N{VARIATION SELECTOR-16}"

    async def callback(self, interaction: discord.Interaction):
        self.view.stop()
        if interaction.message.flags.ephemeral:
            await interaction.response.edit_message(view=None)
            return
        await interaction.message.delete()


class ForwardButton(discord.ui.Button):
    def __init__(
        self,
        style: discord.ButtonStyle,
        row: Optional[int],
    ):
        super().__init__(style=style, row=row)
        self.style = style
        self.emoji = "\N{BLACK RIGHT-POINTING TRIANGLE}\N{VARIATION SELECTOR-16}"

    async def callback(self, interaction: discord.Interaction):
        await self.view.show_checked_page(self.view.current_page + 1, interaction)


class BackButton(discord.ui.Button):
    def __init__(
        self,
        style: discord.ButtonStyle,
        row: Optional[int],
    ):
        super().__init__(style=style, row=row)
        self.style = style
        self.emoji = "\N{BLACK LEFT-POINTING TRIANGLE}\N{VARIATION SELECTOR-16}"

    async def callback(self, interaction: discord.Interaction):
        await self.view.show_checked_page(self.view.current_page - 1, interaction)


class LastItemButton(discord.ui.Button):
    def __init__(
        self,
        style: discord.ButtonStyle,
        row: Optional[int],
    ):
        super().__init__(style=style, row=row)
        self.style = style
        self.emoji = "\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}\N{VARIATION SELECTOR-16}"  # noqa: E501

    async def callback(self, interaction: discord.Interaction):
        await self.view.show_page(self.view.source.get_max_pages() - 1, interaction)


class FirstItemButton(discord.ui.Button):
    def __init__(
        self,
        style: discord.ButtonStyle,
        row: Optional[int],
    ):
        super().__init__(style=style, row=row)
        self.style = style
        self.emoji = "\N{BLACK LEFT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}\N{VARIATION SELECTOR-16}"  # noqa: E501

    async def callback(self, interaction: discord.Interaction):
        await self.view.show_page(0, interaction)


class PerRankButton(discord.ui.Button):
    def __init__(
        self,
        style: discord.ButtonStyle,
        row: Optional[int],
    ):
        super().__init__(style=style, row=row)
        self.style = style
        self.emoji = "\N{UP DOWN ARROW}"

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        per_rank = view.source.per_rank
        if view.source.per_rank in ("leaf", "child"):
            _per_rank = "main"
        elif per_rank == "main":
            _per_rank = "any"
        elif per_rank == "any":
            current_taxon = view.select_taxon.taxon()
            if current_taxon:
                _per_rank = current_taxon.rank
            else:
                _per_rank = "main"
        else:
            _per_rank = "main"
        await view.update_source(interaction, per_rank=_per_rank)


class LeafButton(discord.ui.Button):
    def __init__(
        self,
        style: discord.ButtonStyle,
        row: Optional[int],
    ):
        super().__init__(style=style, row=row)
        self.style = style
        self.emoji = "\N{LEAF FLUTTERING IN WIND}"

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        per_rank = view.source.per_rank
        if per_rank == "leaf":
            _per_rank = "any"
        elif per_rank == "child":
            _per_rank = "leaf"
        else:
            _per_rank = "child"
        await view.update_source(interaction, per_rank=_per_rank)


class RootButton(discord.ui.Button):
    def __init__(
        self,
        style: discord.ButtonStyle,
        row: Optional[int],
    ):
        super().__init__(style=style, row=row)
        self.style = style
        self.emoji = "\N{TOP WITH UPWARDS ARROW ABOVE}"

    async def callback(self, interaction: discord.Interaction):
        await self.view.update_source(interaction, toggle_taxon_root=True)


class DirectButton(discord.ui.Button):
    def __init__(
        self,
        style: discord.ButtonStyle,
        row: Optional[int],
    ):
        super().__init__(style=style, row=row)
        self.style = style
        self.emoji = "\N{REGIONAL INDICATOR SYMBOL LETTER D}"

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        formatter = view.source._taxon_list_formatter
        await view.update_source(interaction, with_direct=not formatter.with_direct)


class CommonButton(discord.ui.Button):
    def __init__(
        self,
        style: discord.ButtonStyle,
        row: Optional[int],
    ):
        super().__init__(style=style, row=row)
        self.style = style
        self.emoji = "\N{REGIONAL INDICATOR SYMBOL LETTER C}"

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        formatter = view.source._taxon_list_formatter
        await view.update_source(interaction, with_common=not formatter.with_common)


class SelectTaxonOption(discord.SelectOption):
    def __init__(
        self,
        value: int,
        taxon: Taxon,
        default: int,
    ):
        super().__init__(label=taxon.full_name, value=str(value), default=default)


class SelectTaxonListTaxon(discord.ui.Select):
    def __init__(
        self,
        view: discord.ui.View,
        placeholder: Optional[str] = "Select a taxon",
        page: list[Taxon] = [],
        selected: Optional[int] = 0,
    ):
        view.ctx.selected = selected
        self.taxa = page
        options = self._make_options(selected)
        super().__init__(
            min_values=1, max_values=1, placeholder=placeholder, options=options
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.ctx.selected = self.values[0]
        await self.view.update_source(interaction)

    def taxon(self):
        return self.taxa[int(self.view.ctx.selected)]

    def update_options(self, page=list[Taxon], selected: Optional[int] = 0):
        self.view.ctx.selected = selected
        self.taxa = page
        self.options = self._make_options(selected)

    def _make_options(self, selected):
        options = []
        for (value, taxon) in enumerate(self.taxa):
            options.append(SelectTaxonOption(value, taxon, default=(value == selected)))
        return options


class DiscordBaseMenu(discord.ui.View):
    def __init__(
        self,
        timeout: int = 60,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            timeout=timeout,
        )


class UserButton(discord.ui.Button):
    def __init__(
        self,
        style: discord.ButtonStyle,
        row: Optional[int],
    ):
        super().__init__(style=style, row=row, custom_id="user")
        self.style = style
        self.emoji = "\N{BUST IN SILHOUETTE}"

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        inat_client = view.inat_client
        await interaction.response.defer()
        user = await (
            await inat_client.users.from_dronefly_users([interaction.user])
        ).async_one()
        await self.view.source.toggle_user_count(inat_client, user)
        await self.view.show_page(interaction)


class QueryUserModal(discord.ui.Modal):
    def __init__(self, view=None):
        super().__init__(title="Add or remove a user")
        self.view = view
        self.discord_user = discord.ui.UserSelect()
        self.user_select_label = discord.ui.Label(
            text="Select a member to add/remove", component=self.discord_user
        )
        self.user_text = discord.ui.TextInput(required=False)
        self.user_text_label = discord.ui.Label(
            text="Or type an iNat username", component=self.user_text
        )
        self.add_item(self.user_select_label)
        self.add_item(self.user_text_label)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            view = self.view
            inat_client = view.inat_client
            dronefly_config = view.dronefly_ctx.config

            discord_user_values = self.discord_user.values
            discord_user_value = None
            user_text_value = self.user_text.value

            if not (discord_user_values or user_text_value):
                await interaction.response.send_message(
                    content="No member selected or iNat username typed.", ephemeral=True
                )
                return
            elif discord_user_values and user_text_value:
                await interaction.response.send_message(
                    content="Choose only a member or iNat username, not both.",
                    ephemeral=True,
                )
                return
            user_for_member = None
            user_for_text = None
            inat_user_id = None
            if discord_user_values:
                discord_user_value = discord_user_values[0]
                if not isinstance(discord_user_value, discord.Member):
                    discord_user_value = await commands.MemberConverter().convert(
                        self.view.ctx, discord_user_value
                    )
                inat_user_id = await dronefly_config.user_id(discord_user_value)
                if inat_user_id:
                    user_for_member = await inat_client.users.from_ids(
                        inat_user_id
                    ).async_one()
                    if user_for_member:
                        await view.source.toggle_user_count(
                            inat_client, user_for_member
                        )
            if user_text_value:
                inat_user_id = await dronefly_config.user_id(user_text_value)
                if inat_user_id:
                    user_for_text = await inat_client.users.from_ids(
                        inat_user_id
                    ).async_one()
                    await view.source.toggle_user_count(inat_client, user_for_text)
        except (HTTPError, LookupError):
            pass
        if user_for_member or user_for_text:
            await view.show_page(interaction)
        elif discord_user_value:
            await interaction.response.send_message(
                content="iNat user not known for that member.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                content="iNat user not found.", ephemeral=True
            )
            return


class QueryUserButton(discord.ui.Button):
    def __init__(
        self,
        style: discord.ButtonStyle,
        row: Optional[int],
    ):
        super().__init__(style=style, row=row, custom_id="query_user")
        self.style = style
        self.emoji = "\N{BUSTS IN SILHOUETTE}"

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(QueryUserModal(view=self.view))


class HomePlaceButton(discord.ui.Button):
    def __init__(
        self,
        style: discord.ButtonStyle,
        row: Optional[int],
    ):
        super().__init__(style=style, row=row, custom_id="home_place")
        self.style = style
        self.emoji = "\N{HOUSE BUILDING}"

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        inat_client = view.inat_client
        dronefly_config = view.dronefly_ctx.config

        await interaction.response.defer()
        place_id = await dronefly_config.place_id("home", interaction.user)
        place = None
        if place_id:
            place = await inat_client.places.from_ids(place_id).async_one()
        if place:
            await self.view.source.toggle_place_count(inat_client, place)
            await self.view.show_page(interaction)
        else:
            await interaction.response.send_message(
                "You have not set a home place", ephemeral=True
            )


class QueryPlaceModal(discord.ui.Modal):
    def __init__(self, view=None):
        super().__init__(title="Add or remove a place")
        self.view = view
        self.place_text = discord.ui.TextInput(required=True)
        self.place_text_label = discord.ui.Label(
            text="Type an iNat place or abbreviation", component=self.place_text
        )
        self.add_item(self.place_text_label)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            view = self.view
            inat_client = view.inat_client
            dronefly_config = view.dronefly_ctx.config

            place_text_value = self.place_text.value

            if place_text_value:
                inat_place_id = await dronefly_config.place_id(place_text_value)
                if inat_place_id:
                    place_for_text = await inat_client.places.from_ids(
                        inat_place_id
                    ).async_one()
                else:
                    places_for_text = await inat_client.places.autocomplete(
                        q=place_text_value, limit=1
                    ).async_all()
                    if places_for_text:
                        place_for_text = places_for_text[0]
                if place_for_text:
                    await view.source.toggle_place_count(inat_client, place_for_text)
                    await view.show_page(interaction)
                    return
        except (HTTPError, LookupError):
            pass
        await interaction.response.send_message(
            content="iNat place not found.", ephemeral=True
        )


class QueryPlaceButton(discord.ui.Button):
    def __init__(
        self,
        style: discord.ButtonStyle,
        row: Optional[int],
    ):
        super().__init__(style=style, row=row, custom_id="query_place")
        self.style = style
        self.emoji = "\N{EARTH GLOBE EUROPE-AFRICA}"

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(QueryPlaceModal(view=self.view))


class TaxonomyButton(discord.ui.Button):
    def __init__(
        self,
        style: discord.ButtonStyle,
        row: Optional[int],
    ):
        super().__init__(style=style, row=row, custom_id="taxonomy")
        self.style = style
        self.emoji = "\N{REGIONAL INDICATOR SYMBOL LETTER T}"

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.view.source.toggle_ancestors()
        await self.view.show_page(interaction)


class TaxonListMenu(DiscordBaseMenu, CoreTaxonListMenu):
    def __init__(
        self,
        source: TaxonListSource,
        cog: commands.Cog,
        message: discord.Message = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.source = source
        self.cog = cog
        self.bot = None
        self.message = message
        self.ctx = None
        self.author: Optional[discord.Member] = None
        self.current_page = kwargs.get("page_start", 0)
        self.forward_button = ForwardButton(discord.ButtonStyle.grey, 0)
        self.back_button = BackButton(discord.ButtonStyle.grey, 0)
        self.first_item = FirstItemButton(discord.ButtonStyle.grey, 0)
        self.last_item = LastItemButton(discord.ButtonStyle.grey, 0)
        self.stop_button = StopButton(discord.ButtonStyle.red, 0)
        # Late bind these as which buttons are shown depends on page content:
        self.leaf_button = None
        self.per_rank_button = None
        self.direct_button = None
        self.common_button = None
        self.select_taxon = None
        self.root_button = None
        self.root_taxon_id_stack = []
        self.add_item(self.stop_button)
        self.add_item(self.first_item)
        self.add_item(self.back_button)
        self.add_item(self.forward_button)
        self.add_item(self.last_item)

    async def on_timeout(self):
        await self.message.edit(view=None)

    async def start(self, ctx: commands.Context):
        ctx.selected = 0
        self.ctx = ctx
        self.bot = self.cog.bot
        self.author = ctx.author
        # await self.source._prepare_once()
        self.message = await self.send_initial_message(ctx)

    async def _get_kwargs_from_page(self, page):
        selected = None
        if isinstance(self.source, TaxonListSource):
            selected = self.ctx.selected
        value = await discord.utils.maybe_coroutine(
            self.source.format_page, page, self.current_page, selected
        )
        if isinstance(value, dict):
            return value
        elif isinstance(value, str):
            return {"content": value, "embed": None}
        elif isinstance(value, discord.Embed):
            return {"embed": value, "content": None}

    async def send_initial_message(self, ctx: commands.Context):
        """|coro|
        The default implementation of :meth:`Menu.send_initial_message`
        for the interactive pagination session.
        This implementation shows the first page of the source.
        """
        self.ctx = ctx
        page = await self.source.get_page(self.current_page)
        kwargs = await self._get_kwargs_from_page(page)
        if getattr(page[0], "descendant_obs_count", None):
            # Source modifier buttons for life list:
            self.leaf_button = LeafButton(discord.ButtonStyle.grey, 1)
            self.per_rank_button = PerRankButton(discord.ButtonStyle.grey, 1)
            self.root_button = RootButton(discord.ButtonStyle.grey, 1)
            self.direct_button = DirectButton(discord.ButtonStyle.grey, 1)
            self.add_item(self.leaf_button)
            self.add_item(self.per_rank_button)
            self.add_item(self.root_button)
            self.add_item(self.direct_button)
            if self.source.query_response.user:
                self.common_button = CommonButton(discord.ButtonStyle.grey, 1)
                self.add_item(self.common_button)
        self.select_taxon = SelectTaxonListTaxon(view=self, page=page, selected=0)
        self.add_item(self.select_taxon)
        self.message = await ctx.send(**kwargs, view=self)
        return self.message

    async def show_page(
        self, page_number: int, interaction: discord.Interaction, selected: int = 0
    ):
        page = await self.source.get_page(page_number)
        self.current_page = page_number
        self.ctx.selected = selected
        kwargs = await self._get_kwargs_from_page(page)
        self.select_taxon.update_options(page, selected)
        if interaction.response.is_done():
            await interaction.edit_original_response(**kwargs, view=self)
        else:
            await interaction.response.edit_message(**kwargs, view=self)

    async def show_checked_page(
        self, page_number: int, interaction: discord.Interaction
    ) -> None:
        max_pages = self.source.get_max_pages()
        try:
            if max_pages is None:
                # If it doesn't give maximum pages, it cannot be checked
                await self.show_page(page_number, interaction)
            elif page_number >= max_pages:
                await self.show_page(0, interaction)
            elif page_number < 0:
                await self.show_page(max_pages - 1, interaction)
            elif max_pages > page_number >= 0:
                await self.show_page(page_number, interaction)
        except IndexError:
            # An error happened that can be handled, so ignore it.
            pass

    async def interaction_check(self, interaction: discord.Interaction):
        """Just extends the default reaction_check to use owner_ids"""
        if interaction.user.id not in (
            *interaction.client.owner_ids,
            getattr(self.author, "id", None),
        ):
            await interaction.response.send_message(
                content="You are not authorized to interact with this.", ephemeral=True
            )
            return False
        return True

    @property
    def formatter(self) -> TaxonListFormatter:
        return self.source.formatter

    async def update_source(self, interaction: discord.Interaction, **kwargs):
        await interaction.response.defer()
        # Replace the source with a new source, preserving the currently
        # selected taxon
        per_rank = kwargs.get("per_rank") or self.source.per_rank
        with_direct = kwargs.get("with_direct")
        if with_direct is None:
            with_direct = self.formatter.with_direct
        with_common = kwargs.get("with_common")
        if with_common is None:
            with_common = self.formatter.with_common
        short_description = self.formatter.short_description
        toggle_taxon_root = kwargs.get("toggle_taxon_root")
        per_page = self.source.per_page
        taxon_list = self.source._entries
        query_response = self.source.query_response
        current_taxon = self.select_taxon.taxon()
        root_taxon_id = (
            self.root_taxon_id_stack[-1] if self.root_taxon_id_stack else None
        )
        sort_by = kwargs.get("sort_by") or self.source.sort_by
        order = kwargs.get("order") or self.source.order
        if toggle_taxon_root:
            if current_taxon.id in self.root_taxon_id_stack:
                self.root_taxon_id_stack.pop()
                root_taxon_id = (
                    self.root_taxon_id_stack[-1] if self.root_taxon_id_stack else None
                )
            else:
                query_taxon = query_response.taxon
                # If at the top of the stack, and a taxon was specified in
                # the query, generate a new life list for its immediate
                # ancestor.
                if (
                    query_taxon
                    and query_taxon.id != ROOT_TAXON_ID
                    and not self.root_taxon_id_stack
                    and self.current_page == 0
                    and self.ctx.selected == 0
                ):
                    if query_taxon.parent_id == ROOT_TAXON_ID:
                        # Simplify the request by removing the taxon filter
                        # if we hit the top (Life)
                        query_response.taxon = None
                    else:
                        paginator = self.ctx.inat_client.taxa.from_ids(
                            query_taxon.parent_id,
                            limit=1,
                        )
                        if paginator:
                            taxa = await paginator.async_all()
                            query_response.taxon = taxa[0] if taxa else None

                    # And in either case, get a new taxon_list for the updated query response:
                    life_list = await self.ctx.inat_client.observations.life_list(
                        **query_response.obs_args()
                    )
                    if life_list:
                        taxon_list = life_list.data
                    # The first taxon on page 0 is selected:
                    root_taxon_id = None
                    current_taxon = None
                else:
                    root_taxon_id = current_taxon.id
                    self.root_taxon_id_stack.append(root_taxon_id)
        # Replace the formatter; TODO: support updating existing formatter
        formatter = TaxonListFormatter(
            with_taxa=True,
            with_direct=with_direct,
            with_common=with_common,
            short_description=short_description,
        )
        self._taxon_list_formatter = formatter
        # Replace the source
        self.source = self.source.__class__(
            taxon_list,
            query_response,
            formatter,
            per_rank=per_rank,
            per_page=per_page,
            root_taxon_id=root_taxon_id,
            sort_by=sort_by,
            order=order,
        )
        # Find the current taxon
        if current_taxon:
            # Find the taxon or the first taxon that is a descendant of it (e.g.
            # "leaf" case may have dropped the taxon if was above all of the taxa
            # in the new display)
            taxon_index = next(
                (
                    i
                    for i, taxon in enumerate(self.source.entries)
                    if current_taxon.id == taxon.id
                    or current_taxon.id in (t.id for t in taxon.ancestors)
                ),
                None,
            )

            # Or the lowest ancestor of the taxon e.g. the "main" case may have
            # dropped the taxon if it was below all of the taxa in the new display
            if taxon_index is None:
                ancestor_indices = reversed(
                    list(
                        i
                        for i, taxon in enumerate(self.source.entries)
                        if taxon.id in (t.id for t in current_taxon.ancestors)
                    )
                )
                taxon_index = next(ancestor_indices, 0)

            # Show the page with the matched taxon on it
            page = floor(taxon_index / per_page)
            selected = taxon_index % per_page
        else:
            # Should never get here as we require the select to always have a value
            page = 0
            selected = 0
        await self.show_page(page, interaction, selected)


class CountSource(CoreCountSource):
    def format_page(self):
        embed = make_count_embed(
            formatter=self.formatter,
            description=self.formatter.format(),
        )
        return embed


class CountMenu(DiscordBaseMenu, CoreCountMenu):
    ctx: commands.Context = None
    author: discord.Member = None
    message: discord.Message = None
    home_place_button: discord.Button = None
    query_place_button: discord.Button = None
    user_button: discord.Button = None
    query_user_button: discord.Button = None

    def __init__(
        self,
        cog: commands.Cog,
        inat_client: iNatClient,
        source: CountSource,
        for_place: bool = None,
        **kwargs: Any,
    ) -> None:
        self.cog = cog
        self.bot = self.cog.bot
        self.inat_client = inat_client
        self.source = source
        self.for_place = for_place
        if for_place:
            self.home_place_button = HomePlaceButton(discord.ButtonStyle.grey, 0)
            self.query_place_button = QueryPlaceButton(discord.ButtonStyle.grey, 0)
        else:
            self.user_button = UserButton(discord.ButtonStyle.grey, 0)
            self.query_user_button = QueryUserButton(discord.ButtonStyle.grey, 0)
        super().__init__(**kwargs)

    async def on_timeout(self):
        await self.message.edit(view=None)

    async def start(self, ctx: commands.Context):
        self.ctx = ctx
        self.author = ctx.author
        # await self.source._prepare_once()
        # Place or user social buttons
        if self.for_place:
            self.add_item(self.home_place_button)
            self.add_item(self.query_place_button)
        else:
            self.add_item(self.user_button)
            self.add_item(self.query_user_button)
        # Owner-only button to cancel the menu
        self.stop_button = StopButton(discord.ButtonStyle.red, 0)
        self.add_item(self.stop_button)
        self.message = await self.send_initial_message(ctx)

    async def _get_kwargs_from_page(self):
        value = await discord.utils.maybe_coroutine(self.source.format_page)
        if isinstance(value, dict):
            return value
        elif isinstance(value, str):
            return {"content": value, "embed": None}
        elif isinstance(value, discord.Embed):
            return {"embed": value, "content": None}

    async def send_initial_message(self, ctx: commands.Context):
        """|coro|
        The default implementation of :meth:`Menu.send_initial_message`
        for the interactive pagination session.
        This implementation shows the first page of the source.
        """
        self.ctx = ctx
        kwargs = await self._get_kwargs_from_page()
        self.message = await ctx.send(**kwargs, view=self)
        return self.message

    async def show_page(self, interaction: discord.Interaction):
        self.current_page = 0
        kwargs = await self._get_kwargs_from_page()
        if interaction.response.is_done():
            await interaction.edit_original_response(**kwargs, view=self)
        else:
            await interaction.response.edit_message(**kwargs, view=self)

    async def interaction_check(self, interaction: discord.Interaction):
        """Allow owner and known iNat user interactions."""
        # Only some buttons can be pressed by known users:
        if interaction.data.get("custom_id") in [
            "user",
            "query_user",
            "home_place",
            "query_place",
            # "taxonomy",
        ]:
            dronefly_config = self.dronefly_ctx.config
            try:
                await dronefly_config.user_id(interaction.user)
            except LookupError:
                await interaction.response.send_message(
                    content="Your iNat account is not known here.", ephemeral=True
                )
                return False
            return True
        elif interaction.user.id not in (
            *interaction.client.owner_ids,
            getattr(self.author, "id", None),
        ):
            # Other buttons can only be pressed by the owner:
            await interaction.response.send_message(
                content="Only the command owner can do this.", ephemeral=True
            )
            return False
        return True


class TaxonSource(CoreTaxonSource):
    def format_page(self):
        # TODO: migrate photo concerns into taxon source & formatter:
        if self.formatter.image_number is None:
            embed = make_taxa_embed(
                taxon=self.query_response.taxon,
                formatter=self.formatter,
                description=self.formatter.format(
                    with_title=False, with_ancestors=self.with_ancestors
                ),
            )
        else:
            embed = make_image_embed(
                taxon=self.query_response.taxon,
                formatter=self.formatter,
                index=self.formatter.image_number,
            )
        return embed


class TaxonMenu(DiscordBaseMenu, CoreTaxonMenu):
    ctx: commands.Context = None
    author: discord.Member = None
    message: discord.Message = None
    home_place_button: discord.Button = None
    query_place_button: discord.Button = None
    user_button: discord.Button = None
    query_user_button: discord.Button = None

    def __init__(
        self,
        inat_client: iNatClient,
        source: TaxonSource,
        cog: commands.Cog,
        message: discord.Message = None,
        for_place: bool = False,
        image_number: int = None,
        related_embed: discord.Embed = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.inat_client = inat_client
        self.source = source
        self.cog = cog
        self.bot = None
        self.message = message
        self.ctx = None
        self.author: Optional[discord.Member] = None
        self.image_number = image_number
        self.related_embed = related_embed
        self.taxonomy_button = TaxonomyButton(discord.ButtonStyle.grey, 0)
        self.stop_button = StopButton(discord.ButtonStyle.red, 0)
        self.for_place = for_place
        if self.for_place:
            self.home_place_button = HomePlaceButton(discord.ButtonStyle.grey, 0)
            self.query_place_button = QueryPlaceButton(discord.ButtonStyle.grey, 0)
        else:
            self.user_button = UserButton(discord.ButtonStyle.grey, 0)
            self.query_user_button = QueryUserButton(discord.ButtonStyle.grey, 0)

    async def on_timeout(self):
        await self.message.edit(view=None)

    async def start(self, ctx: commands.Context):
        self.ctx = ctx
        self.bot = self.cog.bot
        self.author = ctx.author
        # await self.source._prepare_once()
        if self.for_place:
            self.add_item(self.home_place_button)
            self.add_item(self.query_place_button)
        else:
            self.add_item(self.user_button)
            self.add_item(self.query_user_button)
        if self.source.formatter.image_number is None:
            self.add_item(self.taxonomy_button)
        self.add_item(self.stop_button)
        self.message = await self.send_initial_message(ctx)

    async def _get_kwargs_from_page(self):
        value = await discord.utils.maybe_coroutine(self.source.format_page)
        if isinstance(value, dict):
            return value
        elif isinstance(value, str):
            return {"content": value, "embed": None}
        elif isinstance(value, discord.Embed):
            if self.related_embed:
                embeds = [self.related_embed, value]
            else:
                embeds = [value]
            return {"embeds": embeds, "content": None}

    async def send_initial_message(self, ctx: commands.Context):
        """|coro|
        The default implementation of :meth:`Menu.send_initial_message`
        for the interactive pagination session.
        This implementation shows the first page of the source.
        """
        self.ctx = ctx
        kwargs = await self._get_kwargs_from_page()
        self.message = await ctx.send(**kwargs, view=self)
        return self.message

    async def show_page(self, interaction: discord.Interaction):
        self.current_page = 0
        kwargs = await self._get_kwargs_from_page()
        if interaction.response.is_done():
            await interaction.edit_original_response(**kwargs, view=self)
        else:
            await interaction.response.edit_message(**kwargs, view=self)

    async def interaction_check(self, interaction: discord.Interaction):
        """Allow owner and known iNat user interactions."""
        # Only some buttons can be pressed by known users:
        if interaction.data.get("custom_id") in [
            "user",
            "query_user",
            "home_place",
            "query_place",
            # "taxonomy",
        ]:
            dronefly_config = self.dronefly_ctx.config
            try:
                await dronefly_config.user_id(interaction.user)
            except LookupError:
                await interaction.response.send_message(
                    content="Your iNat account is not known here.", ephemeral=True
                )
                return False
            return True
        elif interaction.user.id not in (
            *interaction.client.owner_ids,
            getattr(self.author, "id", None),
        ):
            # Other buttons can only be pressed by the owner:
            await interaction.response.send_message(
                content="Only the command owner can do this.", ephemeral=True
            )
            return False
        return True
