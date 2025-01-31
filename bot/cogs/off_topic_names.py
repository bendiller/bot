import asyncio
import difflib
import logging
from datetime import datetime, timedelta

from discord import Colour, Embed
from discord.ext.commands import BadArgument, Bot, Cog, Context, Converter, group

from bot.api import ResponseCodeError
from bot.constants import Channels, MODERATION_ROLES
from bot.decorators import with_role
from bot.pagination import LinePaginator


CHANNELS = (Channels.off_topic_0, Channels.off_topic_1, Channels.off_topic_2)
log = logging.getLogger(__name__)


class OffTopicName(Converter):
    """A converter that ensures an added off-topic name is valid."""

    @staticmethod
    async def convert(ctx: Context, argument: str) -> str:
        """Attempt to replace any invalid characters with their approximate Unicode equivalent."""
        allowed_characters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ!?'`-"

        if not (2 <= len(argument) <= 96):
            raise BadArgument("Channel name must be between 2 and 96 chars long")

        elif not all(c.isalnum() or c in allowed_characters for c in argument):
            raise BadArgument(
                "Channel name must only consist of "
                "alphanumeric characters, minus signs or apostrophes."
            )

        # Replace invalid characters with unicode alternatives.
        table = str.maketrans(
            allowed_characters, '𝖠𝖡𝖢𝖣𝖤𝖥𝖦𝖧𝖨𝖩𝖪𝖫𝖬𝖭𝖮𝖯𝖰𝖱𝖲𝖳𝖴𝖵𝖶𝖷𝖸𝖹ǃ？’’-'
        )
        return argument.translate(table)


async def update_names(bot: Bot) -> None:
    """Background updater task that performs the daily channel name update."""
    while True:
        # Since we truncate the compute timedelta to seconds, we add one second to ensure
        # we go past midnight in the `seconds_to_sleep` set below.
        today_at_midnight = datetime.utcnow().replace(microsecond=0, second=0, minute=0, hour=0)
        next_midnight = today_at_midnight + timedelta(days=1)
        seconds_to_sleep = (next_midnight - datetime.utcnow()).seconds + 1
        await asyncio.sleep(seconds_to_sleep)

        try:
            channel_0_name, channel_1_name, channel_2_name = await bot.api_client.get(
                'bot/off-topic-channel-names', params={'random_items': 3}
            )
        except ResponseCodeError as e:
            log.error(f"Failed to get new off topic channel names: code {e.response.status}")
            continue
        channel_0, channel_1, channel_2 = (bot.get_channel(channel_id) for channel_id in CHANNELS)

        await channel_0.edit(name=f'ot0-{channel_0_name}')
        await channel_1.edit(name=f'ot1-{channel_1_name}')
        await channel_2.edit(name=f'ot2-{channel_2_name}')
        log.debug(
            "Updated off-topic channel names to"
            f" {channel_0_name}, {channel_1_name} and {channel_2_name}"
        )


class OffTopicNames(Cog):
    """Commands related to managing the off-topic category channel names."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.updater_task = None

    def cog_unload(self) -> None:
        """Cancel any running updater tasks on cog unload."""
        if self.updater_task is not None:
            self.updater_task.cancel()

    @Cog.listener()
    async def on_ready(self) -> None:
        """Start off-topic channel updating event loop if it hasn't already started."""
        if self.updater_task is None:
            coro = update_names(self.bot)
            self.updater_task = self.bot.loop.create_task(coro)

    @group(name='otname', aliases=('otnames', 'otn'), invoke_without_command=True)
    @with_role(*MODERATION_ROLES)
    async def otname_group(self, ctx: Context) -> None:
        """Add or list items from the off-topic channel name rotation."""
        await ctx.invoke(self.bot.get_command("help"), "otname")

    @otname_group.command(name='add', aliases=('a',))
    @with_role(*MODERATION_ROLES)
    async def add_command(self, ctx: Context, *names: OffTopicName) -> None:
        """Adds a new off-topic name to the rotation."""
        # Chain multiple words to a single one
        name = "-".join(names)

        await self.bot.api_client.post(f'bot/off-topic-channel-names', params={'name': name})
        log.info(
            f"{ctx.author.name}#{ctx.author.discriminator}"
            f" added the off-topic channel name '{name}"
        )
        await ctx.send(f":ok_hand: Added `{name}` to the names list.")

    @otname_group.command(name='delete', aliases=('remove', 'rm', 'del', 'd'))
    @with_role(*MODERATION_ROLES)
    async def delete_command(self, ctx: Context, *names: OffTopicName) -> None:
        """Removes a off-topic name from the rotation."""
        # Chain multiple words to a single one
        name = "-".join(names)

        await self.bot.api_client.delete(f'bot/off-topic-channel-names/{name}')
        log.info(
            f"{ctx.author.name}#{ctx.author.discriminator}"
            f" deleted the off-topic channel name '{name}"
        )
        await ctx.send(f":ok_hand: Removed `{name}` from the names list.")

    @otname_group.command(name='list', aliases=('l',))
    @with_role(*MODERATION_ROLES)
    async def list_command(self, ctx: Context) -> None:
        """
        Lists all currently known off-topic channel names in a paginator.

        Restricted to Moderator and above to not spoil the surprise.
        """
        result = await self.bot.api_client.get('bot/off-topic-channel-names')
        lines = sorted(f"• {name}" for name in result)
        embed = Embed(
            title=f"Known off-topic names (`{len(result)}` total)",
            colour=Colour.blue()
        )
        if result:
            await LinePaginator.paginate(lines, ctx, embed, max_size=400, empty=False)
        else:
            embed.description = "Hmmm, seems like there's nothing here yet."
            await ctx.send(embed=embed)

    @otname_group.command(name='search', aliases=('s',))
    @with_role(*MODERATION_ROLES)
    async def search_command(self, ctx: Context, *, query: OffTopicName) -> None:
        """Search for an off-topic name."""
        result = await self.bot.api_client.get('bot/off-topic-channel-names')
        in_matches = {name for name in result if query in name}
        close_matches = difflib.get_close_matches(query, result, n=10, cutoff=0.70)
        lines = sorted(f"• {name}" for name in in_matches.union(close_matches))
        embed = Embed(
            title=f"Query results",
            colour=Colour.blue()
        )

        if lines:
            await LinePaginator.paginate(lines, ctx, embed, max_size=400, empty=False)
        else:
            embed.description = "Nothing found."
            await ctx.send(embed=embed)


def setup(bot: Bot) -> None:
    """Off topic names cog load."""
    bot.add_cog(OffTopicNames(bot))
    log.info("Cog loaded: OffTopicNames")
