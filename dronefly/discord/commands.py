import discord


class InteractionContext:
    def __init__(self, interaction: discord.Interaction):
        self.interaction = interaction
        self.author = interaction.user
        self.bot = interaction.client

    async def send(self, **kwargs):
        if self.interaction.response.is_done():
            return await self.interaction.followup.send(**kwargs)
        await self.interaction.response.send_message(**kwargs)
        return await self.interaction.original_response()
