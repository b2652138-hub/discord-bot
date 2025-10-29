import discord
from discord.ext import commands
from discord import ui
import asyncio
from typing import Optional
import os

# ================== КОНФИГ ==================
TOKEN = os.getenv("BOT_TOKEN")  # Токен бота мы положим не сюда, а отдельно (чтоб не спалить)

COMPLAINT_CHANNEL = "подача-жалоб"
FORUM_CHANNEL_ID = 1432673738578464798  # замени на ID своего форум-канала жалоб

TAG_ON_REVIEW = "НА РАССМОТРЕНИИ"
TAG_OPEN      = "ОТКРЫТО"
TAG_APPROVED  = "ОДОБРЕНО"
TAG_DENIED    = "ОТКЛОНЕНО"
TAG_CLOSED    = "ЗАКРЫТО"

RESPONSIBLE_ROLES = {
    "Игрок": 123456789012345678,
    "Администратор": 234567890123456789,
    "Куратор организации": 345678901234567890,
    "ГС / ЗГС": 456789012345678901,
    "Старший администратор": 567890123456789012,
    "Лидер и заместитель": 678901234567890123,
    "Пользователь дискорд сервера": 789012345678901234,
}

COUNTER_FILE = "complaint_counter.txt"


def load_counter() -> int:
    if not os.path.exists(COUNTER_FILE):
        return 0
    try:
        with open(COUNTER_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip() or "0")
    except ValueError:
        return 0


def save_counter(value: int):
    with open(COUNTER_FILE, "w", encoding="utf-8") as f:
        f.write(str(value))


# ================== ИНИЦИАЛИЗАЦИЯ БОТА ==================
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True  # чтобы работала команда !reset_counter
bot = commands.Bot(command_prefix="!", intents=intents)


# ================== УТИЛИТЫ ==================
async def get_forum_channel(guild: discord.Guild) -> Optional[discord.ForumChannel]:
    ch = guild.get_channel(FORUM_CHANNEL_ID)
    if ch is None:
        try:
            ch = await guild.fetch_channel(FORUM_CHANNEL_ID)
        except Exception:
            ch = None

    if isinstance(ch, discord.ForumChannel):
        return ch
    return None


def find_tags(forum: discord.ForumChannel, names: list[str]) -> list[discord.ForumTag]:
    tags_found = []
    for n in names:
        tag = discord.utils.find(lambda t: t.name.lower() == n.lower(), forum.available_tags)
        if tag:
            tags_found.append(tag)
    return tags_found


# ================== МОДАЛКА РЕШЕНИЯ МОДЕРА ==================
class VerdictModal(ui.Modal):
    def __init__(self, thread_id: int, approved: bool, reporter_id: int, complaint_number: int):
        super().__init__(title="Причина решения")
        self.thread_id = thread_id
        self.approved = approved
        self.reporter_id = reporter_id
        self.complaint_number = complaint_number

        placeholder_text = (
            "Опишите наказание нарушителю, формально и вежливо."
            if approved else
            "Укажите причину отклонения (например: отсутствуют доказательства)."
        )

        self.reason_field = ui.TextInput(
            label="Введите текст решения",
            style=discord.TextStyle.paragraph,
            placeholder=placeholder_text,
            required=True,
            max_length=1000,
        )
        self.add_item(self.reason_field)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        forum = await get_forum_channel(guild)
        if forum is None:
            await interaction.response.send_message(
                "Форум не найден. Сообщите разработчику.",
                ephemeral=True
            )
            return

        thread = guild.get_channel(self.thread_id)
        if thread is None:
            thread = await bot.fetch_channel(self.thread_id)

        if self.approved:
            new_tags_names = [TAG_APPROVED, TAG_CLOSED]
        else:
            new_tags_names = [TAG_DENIED, TAG_CLOSED]

        new_tags = find_tags(forum, new_tags_names)

        try:
            await thread.edit(applied_tags=new_tags, archived=False, locked=False)
        except Exception:
            pass

        reporter_mention = f"<@{self.reporter_id}>"
        moderator_mention = interaction.user.mention

        if self.approved:
            header_line = f"Здравствуйте, {reporter_mention}! Ваша жалоба одобрена."
            status_line = "Статус: ✅ Жалоба одобрена."
        else:
            header_line = f"Здравствуйте, {reporter_mention}! Ваша жалоба отклонена."
            status_line = "Статус: ⛔ Жалоба отклонена."

        body_lines = [
            header_line,
            "",
            "Решение:",
            self.reason_field.value,
            "",
            f"Благодарим вас за вашу жалобу #{self.complaint_number}.",
            status_line,
            f"Модератор рассмотревший жалобу: {moderator_mention}",
        ]

        verdict_text = "\n".join(body_lines)

        await thread.send(verdict_text)

        await interaction.response.send_message(
            "Решение опубликовано. Тема закрыта.",
            ephemeral=True
        )

        try:
            await thread.edit(archived=True, locked=True)
        except Exception:
            pass


# ================== КНОПКИ МОДЕРА ==================
class ModerationPanelView(ui.View):
    def __init__(self, thread_id: int, reporter_id: int, complaint_number: int):
        super().__init__(timeout=None)
        self.thread_id = thread_id
        self.reporter_id = reporter_id
        self.complaint_number = complaint_number

    @ui.button(label="Одобрено", style=discord.ButtonStyle.success)
    async def approve_button(self, interaction: discord.Interaction, button: ui.Button):
        modal = VerdictModal(
            thread_id=self.thread_id,
            approved=True,
            reporter_id=self.reporter_id,
            complaint_number=self.complaint_number,
        )
        await interaction.response.send_modal(modal)

    @ui.button(label="Отклонено", style=discord.ButtonStyle.danger)
    async def deny_button(self, interaction: discord.Interaction, button: ui.Button):
        modal = VerdictModal(
            thread_id=self.thread_id,
            approved=False,
            reporter_id=self.reporter_id,
            complaint_number=self.complaint_number,
        )
        await interaction.response.send_modal(modal)


# ================== МОДАЛКА ЖАЛОБЫ (ИГРОК ЗАПОЛНЯЕТ) ==================
class ComplaintModal(ui.Modal):
    def __init__(self, complaint_type: str):
        super().__init__(title=f"Жалоба: {complaint_type}")
        self.complaint_type = complaint_type

        self.field_nick = ui.TextInput(
            label="Ваш ник",
            style=discord.TextStyle.short,
            placeholder="Напишите ваш ник",
            required=True,
            max_length=100,
        )

        self.field_target = ui.TextInput(
            label="На кого жалоба",
            style=discord.TextStyle.short,
            placeholder="Ник нарушителя",
            required=True,
            max_length=100,
        )

        self.field_datetime = ui.TextInput(
            label="Дата / время",
            style=discord.TextStyle.short,
            placeholder="Например: 28.10.2025, 15:30",
            required=True,
            max_length=100,
        )

        self.field_reason = ui.TextInput(
            label="Суть жалобы",
            style=discord.TextStyle.paragraph,
            placeholder="Опишите нарушение подробно",
            required=True,
            max_length=1000,
        )

        self.field_proofs = ui.TextInput(
            label="Доказательства",
            style=discord.TextStyle.paragraph,
            placeholder="Ссылки на YouTube / Imgur.",
            required=True,
            max_length=1000,
        )

        self.add_item(self.field_nick)
        self.add_item(self.field_target)
        self.add_item(self.field_datetime)
        self.add_item(self.field_reason)
        self.add_item(self.field_proofs)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        forum = await get_forum_channel(guild)

        if forum is None:
            await interaction.response.send_message(
                "Ошибка: форум-канал для жалоб не найден. Сообщите администрации.",
                ephemeral=True
            )
            return

        current = load_counter()
        case_number = current + 1
        save_counter(case_number)

        thread_title = f'Жалоба на "{self.complaint_type}" #{case_number}'

        embed = discord.Embed(
            title=f"Жалоба на {self.complaint_type}",
            color=discord.Color.dark_red()
        )
        embed.add_field(name="Ваш ник", value=self.field_nick.value, inline=False)
        embed.add_field(name="На кого жалоба", value=self.field_target.value, inline=False)
        embed.add_field(name="Дата / время", value=self.field_datetime.value, inline=False)
        embed.add_field(name="Суть жалобы", value=self.field_reason.value, inline=False)
        embed.add_field(name="Доказательства", value=self.field_proofs.value, inline=False)

        start_tags = find_tags(forum, [TAG_ON_REVIEW, TAG_OPEN])

        thread, first_msg = await forum.create_thread(
            name=thread_title,
            content=None,
            embed=embed,
            applied_tags=start_tags
        )

        role_id = RESPONSIBLE_ROLES.get(self.complaint_type)
        ping_text = None
        if role_id:
            ping_text = (
                f"<@&{role_id}> ⚠️ Поступила новая жалоба #{case_number} "
                f"({self.complaint_type})"
            )

        panel_view = ModerationPanelView(
            thread_id=thread.id,
            reporter_id=interaction.user.id,
            complaint_number=case_number
        )

        await first_msg.edit(
            content=ping_text if ping_text else discord.utils.MISSING,
            view=panel_view
        )

        await interaction.response.send_message(
            "✅ Ваша жалоба отправлена и находится на рассмотрении модераторов.",
            ephemeral=True
        )


# ================== ВЫПАДАЮЩЕЕ МЕНЮ В КАНАЛЕ ==================
class ComplaintSelect(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        self.select = ui.Select(
            placeholder="Выберите тип жалобы",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Игрок", value="Игрок"),
                discord.SelectOption(label="Администратор", value="Администратор"),
                discord.SelectOption(label="Куратор организации", value="Куратор организации"),
                discord.SelectOption(label="ГС / ЗГС", value="ГС / ЗГС"),
                discord.SelectOption(label="Старший администратор", value="Старший администратор"),
                discord.SelectOption(label="Лидер и заместитель", value="Лидер и заместитель"),
                discord.SelectOption(label="Пользователь дискорд сервера", value="Пользователь дискорд сервера"),
            ]
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        complaint_type = self.select.values[0]
        modal = ComplaintModal(complaint_type)
        await interaction.response.send_modal(modal)


# ================== on_ready ==================
@bot.event
async def on_ready():
    print(f"✅ Бот запущен как {bot.user} (id={bot.user.id})")
    await bot.wait_until_ready()
    await asyncio.sleep(1)

    for guild in bot.guilds:
        complaint_channel = discord.utils.get(guild.text_channels, name=COMPLAINT_CHANNEL)
        if complaint_channel:
            async for msg in complaint_channel.history(limit=20):
                if msg.author == bot.user:
                    await msg.delete()

            view = ComplaintSelect()
            await complaint_channel.send(
                "Для подачи жалобы используйте меню ниже.",
                view=view
            )


# ================== КОМАНДА !reset_counter ==================
@bot.command(name="reset_counter")
@commands.has_permissions(administrator=True)
async def reset_counter(ctx: commands.Context):
    save_counter(0)
    await ctx.reply("Счётчик жалоб сброшен. Следующая жалоба будет #1.")


# ================== СТАРТ ==================
bot.run(TOKEN)
