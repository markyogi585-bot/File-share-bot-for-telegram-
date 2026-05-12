"""
Channel Handler — Join verification callback.
"""

from telegram import Update
from telegram.ext import ContextTypes

from config import Config
from database.mongodb import Database
from middlewares.force_join import ForceJoinMiddleware


class ChannelHandler:

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.force_join = ForceJoinMiddleware(cfg)

    async def handle_join_verify(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """User clicked 'I have joined' button."""
        q = update.callback_query
        user = q.from_user

        # Re-check membership
        all_joined, not_joined = await self.force_join.check_membership(ctx.bot, user.id)

        if all_joined:
            await q.answer("✅ Verified! Bot use kar sakte ho.", show_alert=True)
            await q.message.edit_text(
                "✅ <b>Verified!</b>\n\n"
                "Ab /start bhejo aur bot ka maza lo! 🎉",
                parse_mode="HTML"
            )
        else:
            channels_text = "\n".join(f"• {ch.get('channel_name', ch['channel_id'])}" for ch in not_joined)
            await q.answer(
                f"❌ Abhi bhi join nahi kiya:\n{channels_text}",
                show_alert=True
            )
