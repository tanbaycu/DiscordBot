import asyncio
from datetime import datetime, timezone
import io
import logging
import os
import platform
import random
import sys
from typing import Dict, Optional, Union

import aiohttp
from colorama import init
from deep_translator import GoogleTranslator
import discord
from discord.ext import commands
from dotenv import load_dotenv

from ai_client import AsyncGeminiClient
from memory_store import MemoryStore
from music_system import Music

load_dotenv()
init(autoreset=True)

DATA_DIR = os.getenv("DATA_DIR") or "data"
os.makedirs(DATA_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(DATA_DIR, "bot.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID", "0") or 0)
MUSIC_CHANNEL_ID = int(os.getenv("MUSIC_CHANNEL_ID", "0") or 0)
GITHUB_GIST_URL = "https://api.github.com/gists"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

MUSIC_COMMANDS = {
    "play", "p", "pause", "resume", "skip", "s", "stopmusic", "queue", "q",
    "volume", "vol", "join", "connect", "j", "disconnect", "dc", "leave",
    "musicstats", "search",
}

OPTIMIZED_PROMPT = (
    "Bạn là một trợ lý AI thân thiện, trả lời ngắn gọn, tự nhiên và hữu ích bằng tiếng Việt "
    "(hoặc ngôn ngữ người dùng sử dụng). Giữ văn phong gần gũi, rõ ràng."
)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

ai_client = AsyncGeminiClient()
memory_store: Optional[MemoryStore] = None
gemini_responses_active = True
fact_tasks: Dict[str, asyncio.Task] = {}


def get_memory_store() -> MemoryStore:
    global memory_store
    if memory_store is None:
        memory_store = MemoryStore()
    return memory_store


@bot.event
async def on_ready():
    logger.info(f"{bot.user} đã kết nối với Discord!")
    await bot.change_presence(activity=discord.Game(name="Insta/Discord AI v2"))
    try:
        if bot.get_cog("Music") is None:
            await bot.add_cog(Music(bot))
            logger.info("✅ Music system đã sẵn sàng!")
    except Exception as exc:
        logger.error(f"❌ Lỗi tải music system: {exc}")


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.content.startswith(bot.command_prefix):
        command_name = message.content.split()[0][len(bot.command_prefix) :]
        if MUSIC_CHANNEL_ID and command_name in MUSIC_COMMANDS and message.channel.id != MUSIC_CHANNEL_ID:
            await message.channel.send(f"❌ lệnh nhạc chỉ dùng trong kênh <#{MUSIC_CHANNEL_ID}>")
            return
        await bot.process_commands(message)
        return

    if ALLOWED_CHANNEL_ID and message.channel.id != ALLOWED_CHANNEL_ID:
        return

    if gemini_responses_active:
        user_id = str(message.author.id)
        try:
            async with message.channel.typing():
                store = get_memory_store()
                context = store.get_context(user_id)
                prompt = f"Context:\n{context}\n\nUser: {message.content}\nResponse:" if context else message.content
                reply = await ai_client.generate(prompt, system_instruction=OPTIMIZED_PROMPT)
                store.update(user_id, message.content, reply)
            await message.channel.send(reply[:2000])
        except Exception as exc:
            logger.error(f"Lỗi xử lý tin nhắn: {exc}")
            await message.channel.send("❌ đã xảy ra lỗi khi xử lý tin nhắn.")


@bot.command(name="ping")
async def ping(ctx):
    latency = round(bot.latency * 1000)
    embed = discord.Embed(title="ping", description=f"độ trễ: **{latency}ms**", color=0x2F3136)
    await ctx.send(embed=embed)


@bot.command(name="helpme")
async def help_command(ctx, command_name: Optional[str] = None):
    if command_name:
        cmd = bot.get_command(command_name)
        if not cmd:
            return await ctx.send(f"❌ không tìm thấy lệnh `{command_name}`")
        embed = discord.Embed(title=f"lệnh: {cmd.name}", description=cmd.help or "không có mô tả", color=0x2F3136)
        embed.add_field(name="cách dùng", value=f"`/{cmd.name} {cmd.signature}`", inline=False)
        return await ctx.send(embed=embed)

    embed = discord.Embed(title="danh sách lệnh DiscordBot v2.0", color=0x2F3136)
    categories = {
        "chính": ["ping", "helpme", "stop", "continue", "clearmemory", "clearall"],
        "thông tin": ["invite", "botinfo", "serverinfo"],
        "vui": ["fact", "stopfact", "quote", "randomimage", "coinflip"],
        "nhạc": ["play", "pause", "resume", "skip", "stopmusic", "queue", "volume", "musicstats"],
        "admin": ["shutdown", "kick", "ban", "warning", "say", "embed"],
    }
    for cat, cmds in categories.items():
        embed.add_field(name=cat, value=" ~ ".join(f"`{c}`" for c in cmds), inline=False)
    await ctx.send(embed=embed)


@bot.command(name="stop")
async def stop_bot(ctx):
    global gemini_responses_active
    gemini_responses_active = False
    await ctx.send(f"đã tạm dừng AI chat — bật lại bằng `/continue` ({ctx.author.mention})")


@bot.command(name="continue")
async def continue_bot(ctx):
    global gemini_responses_active
    gemini_responses_active = True
    await ctx.send(f"đã bật lại AI chat ({ctx.author.mention})")


@bot.command(name="clearmemory")
async def clear_memory(ctx):
    cleared = get_memory_store().clear_short(str(ctx.author.id))
    await ctx.send("đã xóa bộ nhớ ngắn hạn" if cleared else "không có bộ nhớ để xóa")


@bot.command(name="clearall")
async def clear_all_memory(ctx):
    get_memory_store().clear_all(str(ctx.author.id))
    await ctx.send("đã xóa toàn bộ bộ nhớ của bạn")


async def create_gist(content: str, language: str) -> Optional[str]:
    if not content or not language or not GITHUB_TOKEN:
        return None
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    data = {
        "description": "Code snippet created by Discord bot",
        "public": True,
        "files": {f"snippet.{language}": {"content": content}},
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GITHUB_GIST_URL, headers=headers, json=data) as resp:
                if resp.status == 201:
                    result = await resp.json()
                    return result.get("html_url")
    except Exception as exc:
        logger.error(f"Lỗi tạo Gist: {exc}")
    return None


@bot.command(name="invite")
async def invite_link(ctx):
    invite_url = discord.utils.oauth_url(bot.user.id, permissions=discord.Permissions(8))
    await ctx.send(f"🔗 link mời bot: {invite_url}")


@bot.command(name="botinfo")
async def bot_info(ctx):
    embed = discord.Embed(title="thông tin bot", color=0x2F3136)
    embed.add_field(name="tên", value=bot.user.name, inline=True)
    embed.add_field(name="python", value=platform.python_version(), inline=True)
    embed.add_field(name="discord.py", value=discord.__version__, inline=True)
    embed.add_field(name="servers", value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="model", value=ai_client.model, inline=True)
    embed.add_field(name="version", value="2.0.0", inline=True)
    await ctx.send(embed=embed)


@bot.command(name="serverinfo")
async def server_info(ctx):
    guild = ctx.guild
    embed = discord.Embed(
        title=f"server: {guild.name}",
        color=0x2F3136,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="id", value=f"`{guild.id}`", inline=True)
    embed.add_field(name="thành viên", value=str(guild.member_count), inline=True)
    embed.add_field(name="kênh", value=str(len(guild.channels)), inline=True)
    await ctx.send(embed=embed)


async def get_random_fact_or_joke():
    sources = [
        ("https://catfact.ninja/fact", lambda d: ("🐱 Sự thật về mèo", d["fact"])),
        (
            "https://uselessfacts.jsph.pl/random.json?language=en",
            lambda d: ("🤔 Sự thật thú vị", d["text"]),
        ),
        (
            "https://official-joke-api.appspot.com/random_joke",
            lambda d: ("😂 Câu chuyện cười", f"{d['setup']} {d['punchline']}"),
        ),
    ]
    random.shuffle(sources)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        for url, extractor in sources:
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        return extractor(data)
            except Exception:
                continue
    return ("Thông báo", "Hiện chưa lấy được fact mới, bạn thử lại sau nhé.")


@bot.command(name="fact")
async def random_fact(ctx):
    user_id = str(ctx.author.id)
    if user_id in fact_tasks:
        return await ctx.send("đã bật fact rồi, dùng `/stopfact` để dừng")

    async def send_facts():
        while True:
            title, content = await get_random_fact_or_joke()
            try:
                vi = GoogleTranslator(source="en", target="vi").translate(content)
            except Exception:
                vi = content
            await ctx.send(f"**{title}**\nEN: {content}\nVI: {vi}")
            await asyncio.sleep(30)

    fact_tasks[user_id] = asyncio.create_task(send_facts())
    await ctx.send("bắt đầu gửi fact mỗi 30s — dùng `/stopfact` để dừng")


@bot.command(name="stopfact")
async def stop_fact(ctx):
    user_id = str(ctx.author.id)
    task = fact_tasks.pop(user_id, None)
    if task:
        task.cancel()
        await ctx.send("đã dừng gửi fact")
    else:
        await ctx.send("chưa bật fact")


@bot.command(name="quote")
async def random_quote(ctx):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        try:
            async with session.get("https://api.quotable.io/random") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return await ctx.send(f'"{data["content"]}" — *{data["author"]}*')
        except Exception:
            pass
    await ctx.send("không thể lấy trích dẫn lúc này")


@bot.command(name="randomimage")
async def random_image(ctx):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        try:
            async with session.get("https://picsum.photos/500") as resp:
                if resp.status == 200:
                    raw = await resp.read()
                    return await ctx.send(file=discord.File(io.BytesIO(raw), "random.png"))
        except Exception:
            pass
    await ctx.send("không thể tải ảnh lúc này")


@bot.command(name="coinflip")
async def coin_flip(ctx):
    await ctx.send(f"tung đồng xu: **{random.choice(['mặt sấp', 'mặt ngửa'])}**")


def is_admin():
    async def predicate(ctx):
        return await bot.is_owner(ctx.author) or ctx.author.guild_permissions.administrator

    return commands.check(predicate)


@bot.command(name="shutdown")
@is_admin()
async def shutdown(ctx):
    await ctx.send("đang tắt bot...")
    if memory_store:
        memory_store.close()
    await bot.close()


@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: Optional[str] = None):
    await member.kick(reason=reason)
    await ctx.send(f"đã kick {member.mention} ({reason or 'không có lý do'})")


@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: Optional[str] = None):
    await member.ban(reason=reason)
    await ctx.send(f"đã ban {member.mention} ({reason or 'không có lý do'})")


@bot.command(name="warning")
@commands.has_permissions(manage_messages=True)
async def warning(ctx, member: discord.Member, *, reason: str):
    await ctx.send(f"**cảnh cáo** {member.mention} — lý do: {reason}")


@bot.command(name="say")
@is_admin()
async def say(ctx, *, message: str):
    await ctx.message.delete()
    await ctx.send(message)


@bot.command(name="embed")
@is_admin()
async def embed_cmd(ctx, *, message: str):
    embed = discord.Embed(description=message, color=0x2F3136)
    await ctx.send(embed=embed)


@bot.command(name="sendcontact")
@is_admin()
async def send_contact(ctx, user: Union[discord.Member, str]):
    if isinstance(user, str):
        found = discord.utils.find(lambda m: user.lower() in m.name.lower(), ctx.guild.members)
        if not found:
            return await ctx.send(f"không tìm thấy `{user}`")
        user = found
    try:
        await user.send(f"Liên hệ admin: {ctx.author.name} (`{ctx.author.id}`)")
        await ctx.send(f"đã gửi thông tin đến {user.name}")
    except discord.Forbidden:
        await ctx.send(f"không thể gửi DM đến {user.name}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("không tìm thấy lệnh, dùng `/helpme` để xem danh sách")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("thiếu tham số, dùng `/helpme <lệnh>`")
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("bạn không có quyền dùng lệnh này")
    else:
        logger.error(f"Lỗi lệnh: {error}")
        await ctx.send("đã xảy ra lỗi, thử lại sau nhé")


def main() -> int:
    if not ai_client.rotator.has_keys():
        logger.error("Thiếu GEMINI_API_KEY / GEMINI_API_KEY_1 trong .env")
        return 1
    discord_token = os.getenv("DISCORD_TOKEN")
    if not discord_token:
        logger.error("Thiếu DISCORD_TOKEN trong .env")
        return 1
    bot.run(discord_token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
