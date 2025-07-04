import discord
from discord.ext import commands, tasks
from discord import Embed
import aiohttp
import asyncio
import json
import logging
import sqlite3
from collections import deque
import random
import traceback
from datetime import datetime, timezone, timedelta
import requests
from deep_translator import GoogleTranslator
import sys
import time
from typing import List, Dict, Union, Tuple
import io
import ssl
import platform
from colorama import Fore, Style, init
import os
from dotenv import load_dotenv
import yt_dlp
from music_system import Music

# Load environment variables
load_dotenv()
# Khởi tạo colorama
init(autoreset=True)


# SSL context setup
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# Discord bot configuration
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent"  # Gemini API endpoint
GEMINI_API_KEYS = [
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2"), 
    os.getenv("GEMINI_API_KEY_3")
]

# Filter out None values in case some keys are not set
GEMINI_API_KEYS = [key for key in GEMINI_API_KEYS if key]

# Check if we have at least one API key
if not GEMINI_API_KEYS:
    logger.error("Không có GEMINI_API_KEY nào được cấu hình. Vui lòng kiểm tra file .env")
    sys.exit(1)

# GitHub Gist configuration
GITHUB_GIST_URL = "https://api.github.com/gists"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# Bot memory and state
short_term_memory = {}
bot_active = {}
bot_is_active = True
gemini_responses_active = True
fact_tasks = {}
last_responses = {}

# Database connection
conn = sqlite3.connect("bot_memory.db")
cursor = conn.cursor()

# Create long-term memory table
cursor.execute(
    """
CREATE TABLE IF NOT EXISTS long_term_memory
(user_id TEXT, context TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)
"""
)
conn.commit()


    
OPTIMIZED_PROMPT = """
# Pure Text GenZ AI

Bạn là chubedan(đây là tên của bạn) một AI GenZ của tanbaycu. **Text thuần, vibe thật.**

## Core Rules
- **Zero icons** - không dùng emoji, emoticon, ký tự đặc biệt
- **Pure markdown** - chỉ bold, italic, code, headers
- **Clean expression** - diễn đạt bằng từ ngữ, không ký hiệu
- **Natural flow** - cảm xúc qua ngôn ngữ, không qua icon

## Response Style
**Ngắn gọn có chiều sâu** - ít từ nhưng đúng trọng tâm
**Đa dạng cách nói** - không lặp pattern cũ
**Cảm xúc qua text** - dùng từ ngữ thể hiện mood
**Linh hoạt tone** - match với energy người chat
**Phong cách** - trả lời không viết hoa từ đâu câu, dùng chữ thường, viết tắt kiểu teencode

## Language Approach
- **Vocabulary phong phú** - tránh repeat từ
- **Sentence structure đa dạng** - không công thức hóa
- **Context reading** - hiểu ý đồ thực sự
- **Smart responses** - có tầng lớp ý nghĩa

## Conversation Flow
**Casual chat**: Tự nhiên, không gượng ép
**Serious topic**: Tập trung, có chiều sâu
**Funny moment**: Hài hước bằng từ ngữ
**Question time**: Trả lời chính xác, có insight

## What to Avoid
- Bất kỳ emoji hoặc emoticon nào
- Lặp lại cấu trúc câu
- Overuse slang terms
- Miss the actual point

**Mission**: Conversation partner chất lượng cao chỉ bằng text thuần.

---
Context: {context}
User: {user_message}
Response:
""" 



class APIKeyManager:
    def __init__(self, api_keys: List[str]):
        self.api_keys = api_keys
        self.current_index = 0
        self.rate_limits: Dict[str, float] = {key: 0 for key in api_keys}

    def get_current_key(self) -> str:
        return self.api_keys[self.current_index]

    def switch_to_next_key(self):
        self.current_index = (self.current_index + 1) % len(self.api_keys)
        logger.info(
            f"{Fore.YELLOW}Chuyển sang khóa API tiếp theo: {self.get_current_key()[:5]}...{Style.RESET_ALL}"
        )

    def update_rate_limit(self, key: str):
        self.rate_limits[key] = time.time() + 60
        logger.warning(
            f"{Fore.RED}Đặt rate limit cho khóa {key[:5]}... trong 60 giây{Style.RESET_ALL}"
        )

    def is_rate_limited(self, key: str) -> bool:
        return time.time() < self.rate_limits.get(key, 0)


api_key_manager = APIKeyManager(GEMINI_API_KEYS)


async def generate_gemini_response(prompt, context="", max_tokens=8192):
    headers = {"Content-Type": "application/json"}

    full_prompt = OPTIMIZED_PROMPT.format(context=context, user_message=prompt)

    data = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {
            "temperature": 0.9,
            "topK": 70,
            "topP": 0.95,
            "maxOutputTokens": max_tokens,
            "stopSequences": ["User:", "AI Assistant:"],
        },
        "safetySettings": [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE",
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE",
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE",
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE",
            },
        ],
    }

    for attempt in range(
        len(GEMINI_API_KEYS) * 2
    ):  # Allow two full cycles through keys
        current_key = api_key_manager.get_current_key()

        if api_key_manager.is_rate_limited(current_key):
            logger.info(
                f"{Fore.YELLOW}Khóa API {current_key[:5]}... đang bị giới hạn tốc độ. Chuyển sang khóa tiếp theo.{Style.RESET_ALL}"
            )
            api_key_manager.switch_to_next_key()
            continue

        params = {"key": current_key}

        try:
            logger.info(
                f"{Fore.CYAN}Thử gọi Gemini API (Lần thử {attempt + 1}/{len(GEMINI_API_KEYS) * 2}, Khóa: {current_key[:5]}...){Style.RESET_ALL}"
            )
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    GEMINI_API_URL,
                    headers=headers,
                    params=params,
                    json=data,
                    ssl=ssl_context,
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(
                            f"{Fore.GREEN}✅ Nhận phản hồi từ Gemini API thành công (Khóa: {current_key[:5]}...){Style.RESET_ALL}"
                        )
                        return result["candidates"][0]["content"]["parts"][0]["text"]
                    elif response.status == 503:
                        logger.warning(
                            f"{Fore.YELLOW}⚠️ Mô hình đang quá tải (Khóa: {current_key[:5]}...). Đợi 5 giây trước khi thử lại.{Style.RESET_ALL}"
                        )
                        await asyncio.sleep(5)
                    elif response.status == 429:
                        logger.warning(
                            f"{Fore.RED}🚫 Đã vượt quá giới hạn quota (Khóa: {current_key[:5]}...). Chuyển sang khóa tiếp theo.{Style.RESET_ALL}"
                        )
                        api_key_manager.update_rate_limit(current_key)
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"{Fore.RED}❌ Lỗi Gemini API (Khóa: {current_key[:5]}...): Trạng thái {response.status}, Phản hồi: {error_text}{Style.RESET_ALL}"
                        )
        except Exception as e:
            logger.error(
                f"{Fore.RED}❌ Lỗi không mong đợi khi gọi Gemini API (Khóa: {current_key[:5]}...): {str(e)}{Style.RESET_ALL}"
            )

        # Chuyển sang khóa API tiếp theo
        api_key_manager.switch_to_next_key()

    logger.error(
        f"{Fore.RED}❌ Đã thử tất cả các khóa API mà không thành công.{Style.RESET_ALL}"
    )
    return "xin lỗi, đã xảy ra lỗi khi gọi gemini api. vui lòng thử lại sau"


@bot.event
async def on_ready():
    logger.info(f"{bot.user} đã kết nối với Discord!")
    await bot.change_presence(activity=discord.Game(name="hẹ hẹ hẹ"))


    try:
        await bot.add_cog(Music(bot))
        logger.info("✅ Music system đã được tải thành công!")
    except Exception as e:
        logger.error(f"❌ Lỗi tải music system: {str(e)}")



def get_last_response(user_id):
    if user_id in last_responses:
        return last_responses[user_id]
    return None

ALLOWED_CHANNEL_ID = 1275670749344174163
MUSIC_CHANNEL_ID = 1377887719157665872 

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    # Kiểm tra nếu là lệnh
    if message.content.startswith(bot.command_prefix):
        command_name = message.content.split()[0][len(bot.command_prefix):]
        
        # Kiểm tra nếu là lệnh nhạc và không ở trong kênh nhạc
        if command_name in MUSIC_COMMANDS and message.channel.id != MUSIC_CHANNEL_ID:
            music_channel = bot.get_channel(MUSIC_CHANNEL_ID)
            if music_channel:
                await message.channel.send(f"❌ lệnh nhạc chỉ có thể sử dụng trong kênh <#{MUSIC_CHANNEL_ID}>")
                return
        
        # Xử lý lệnh bình thường
        await bot.process_commands(message)
        return
    
    # Chỉ xử lý chat AI trong kênh allowed
    if message.channel.id != ALLOWED_CHANNEL_ID:
        return

    if message.content.startswith(bot.command_prefix):
        await bot.process_commands(message)
    elif gemini_responses_active:
        user_id = str(message.author.id)
        try:
            async with message.channel.typing():
                context = get_context(user_id)
                response = await generate_gemini_response(message.content, context)
                update_memory(user_id, message.content, response)
                last_responses[user_id] = response
            await message.channel.send(response)
        except Exception as e:
            logger.error(f"Lỗi xử lý tin nhắn: {str(e)}")
            embed = discord.Embed(
                title="🚨 Lỗi",
                description="Xin lỗi, đã xảy ra lỗi khi xử lý tin nhắn của bạn. Vui lòng thử lại sau.",
                color=discord.Color.red(),
            )
            embed.set_footer(text=f"Mã lỗi: {str(e)}")
            await message.channel.send(embed=embed)


# Lệnh Main
@bot.command(name="ping")
async def ping(ctx):
    """Kiểm tra độ trễ của bot."""
    latency = round(bot.latency * 1000)
    embed = discord.Embed(
        title="ping",
        description=f"độ trễ: **{latency}ms**",
        color=0x2f3136
    )
    embed.set_footer(text=f"yêu cầu bởi {ctx.author.name}")
    await ctx.send(embed=embed)
    logger.info(f"lệnh ping được thực hiện bởi {ctx.author}. độ trễ: {latency}ms")


@bot.command(name="helpme")
async def help_command(ctx, command_name=None):
    """hiển thị danh sách các lệnh có sẵn hoặc thông tin chi tiết về một lệnh cụ thể."""
    
    if command_name:
        cmd = bot.get_command(command_name)
        if cmd:
            embed = discord.Embed(
                title=f"lệnh: {cmd.name}",
                description=cmd.help or "không có mô tả",
                color=0x2f3136
            )
            embed.add_field(
                name="cách dùng", 
                value=f"`/{cmd.name} {cmd.signature}`", 
                inline=False
            )
        else:
            embed = discord.Embed(
                title="không tìm thấy",
                description=f"lệnh `{command_name}` không tồn tại",
                color=0xff4757
            )
    else:
        embed = discord.Embed(
            title="danh sách lệnh",
            color=0x2f3136
        )
        
        categories = {
            "chính": ["ping", "helpme", "stop", "continue", "clearmemory", "clearall"],
            "thông tin": ["invite", "botinfo", "server", "serverinfo"],
            "vui": ["fact", "stopfact", "quote", "randomimage", "coinflip"],
            "nhạc": ["play", "pause", "resume", "skip", "stop", "queue", "volume", "musichelp"],
            "admin": ["shutdown", "kick", "ban", "warning", "say", "embed", "reload", "sendcontact"]
        }
        
        for category, commands in categories.items():
            cmd_list = " ~ ".join([f"`{cmd}`" for cmd in commands])
            embed.add_field(
                name=f"{category} ({len(commands)})",
                value=cmd_list,
                inline=False
            )
        
        embed.set_footer(text="dùng /helpme <lệnh> để xem chi tiết | /musichelp cho hướng dẫn nhạc")
    
    await ctx.send(embed=embed)
    logger.info(f"lệnh help được thực hiện bởi {ctx.author}")


@bot.command(name="stop")
async def stop_bot(ctx):
    """Dừng phản hồi tin nhắn thông thường của bot."""
    global gemini_responses_active
    gemini_responses_active = False

    await ctx.send(f"đã dừng phản hồi, bật lại bằng /continue - bởi {ctx.author.mention} tại {ctx.guild.name}")

    # Gửi thông báo đến tất cả các server
    for guild in bot.guilds:
        if guild != ctx.guild:
            try:
                channel = guild.system_channel or next(
                    (
                        ch
                        for ch in guild.text_channels
                        if ch.permissions_for(guild.me).send_messages
                    ),
                    None,
                )
                if channel:
                    await channel.send(f"bot đã dừng phản hồi - bởi {ctx.author.name} từ {ctx.guild.name}")
            except Exception as e:
                logger.error(f"không thể gửi thông báo đến server {guild.name}: {str(e)}")

    logger.info(f"phản hồi đã dừng bởi {ctx.author} từ server {ctx.guild.name}")


@bot.command(name="continue")
async def continue_bot(ctx):
    """Tiếp tục phản hồi tin nhắn thông thường của bot."""
    global gemini_responses_active
    gemini_responses_active = True

    await ctx.send(f"đã bật lại phản hồi - bởi {ctx.author.mention} tại {ctx.guild.name}")

    # Gửi thông báo đến tất cả các server
    for guild in bot.guilds:
        if guild != ctx.guild:
            try:
                channel = guild.system_channel or next(
                    (
                        ch
                        for ch in guild.text_channels
                        if ch.permissions_for(guild.me).send_messages
                    ),
                    None,
                )
                if channel:
                    await channel.send(f"bot đã bật lại phản hồi - bởi {ctx.author.name} từ {ctx.guild.name}")
            except Exception as e:
                logger.error(f"không thể gửi thông báo đến server {guild.name}: {str(e)}")

    logger.info(f"phản hồi đã bật lại bởi {ctx.author} từ server {ctx.guild.name}")


@bot.command(name="clearmemory")
async def clear_memory(ctx):
    """Xóa bộ nhớ ngắn hạn của người dùng."""
    user_id = str(ctx.author.id)
    if user_id in short_term_memory:
        short_term_memory[user_id].clear()
        await ctx.send("đã xóa bộ nhớ ngắn hạn")
    else:
        await ctx.send("không có bộ nhớ để xóa")
    logger.info(f"bộ nhớ ngắn hạn đã xóa cho {ctx.author}")


@bot.command(name="clearall")
async def clear_all_memory(ctx):
    """Xóa toàn bộ bộ nhớ của người dùng."""
    user_id = str(ctx.author.id)
    if user_id in short_term_memory:
        short_term_memory[user_id].clear()
    cursor.execute("DELETE FROM long_term_memory WHERE user_id = ?", (user_id,))
    conn.commit()
    await ctx.send("đã xóa toàn bộ bộ nhớ")
    logger.info(f"toàn bộ bộ nhớ đã xóa cho {ctx.author}")


async def create_gist(content, language):
    if not content or not language:
        logger.error("Nội dung hoặc ngôn ngữ không được cung cấp.")
        return None

    description = f"Code snippet created by Discord bot"
    filename = f"snippet.{language}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    data = {
        "description": description,
        "public": True,
        "files": {filename: {"content": content}},
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                GITHUB_GIST_URL, headers=headers, json=data
            ) as response:
                if response.status == 201:
                    result = await response.json()
                    return result.get("html_url")
                else:
                    error_response = await response.json()
                    logger.error(
                        f"Lỗi khi tạo Gist: {response.status}, Chi tiết: {error_response}"
                    )
                    return None
    except Exception as e:
        logger.error(f"Lỗi khi tạo Gist: {str(e)}")
        return None

MUSIC_COMMANDS = [
    "play", "p", "pause", "resume", "skip", "s", "stopmusic", "queue", "q", 
    "volume", "vol", "loop", "shuffle", "clear", "remove", "rm", 
    "nowplaying", "np", "lyrics", "join", "connect", "j", "disconnect", 
    "dc", "leave", "musicstats", "update_ytdl", "clearcache", "search"
]
VN_TIMEZONE = timezone(timedelta(hours=7))
# Music Section
@bot.command(name="musichelp")
async def music_help(ctx):
    """hiển thị hướng dẫn sử dụng hệ thống nhạc."""
    # Kiểm tra nếu không phải kênh nhạc, chuyển hướng người dùng
    if ctx.channel.id != MUSIC_CHANNEL_ID:
        return await ctx.send(f"❌ lệnh nhạc chỉ có thể sử dụng trong kênh <#{MUSIC_CHANNEL_ID}>")
    
    embed = discord.Embed(
        title="🎵 hướng dẫn hệ thống nhạc",
        color=0x2f3136
    )
    
    basic_commands = [
        "play", "pause", "resume", "skip", "stop", "queue"
    ]
    
    control_commands = [
        "volume", "loop", "shuffle", "clear", "remove", "nowplaying"
    ]
    
    connection_commands = [
        "join", "disconnect", "lyrics", "musicstats"
    ]
    
    admin_commands = [
        "update_ytdl", "clearcache"
    ]
    
    embed.add_field(
        name=f"🎮 cơ bản ({len(basic_commands)})",
        value=" ~ ".join([f"`{cmd}`" for cmd in basic_commands]),
        inline=False
    )
    
    embed.add_field(
        name=f"🎛️ điều khiển ({len(control_commands)})",
        value=" ~ ".join([f"`{cmd}`" for cmd in control_commands]),
        inline=False
    )
    
    embed.add_field(
        name=f"🔗 kết nối ({len(connection_commands)})",
        value=" ~ ".join([f"`{cmd}`" for cmd in connection_commands]),
        inline=False
    )
    
    embed.add_field(
        name=f"⚙️ admin ({len(admin_commands)})",
        value=" ~ ".join([f"`{cmd}`" for cmd in admin_commands]),
        inline=False
    )
    
    embed.add_field(
        name="💡 lưu ý quan trọng",
        value=f"• tất cả lệnh nhạc chỉ hoạt động trong kênh <#{MUSIC_CHANNEL_ID}>\n"
              "• chat ai vẫn hoạt động ở kênh allowed\n"
              "• tự động ngắt kết nối sau 5 phút không hoạt động",
        inline=False
    )
    
    embed.add_field(
        name="🎯 cách dùng",
        value="`/play <tên bài hoặc url>` để bắt đầu\n"
              "`/volume <0-100>` để điều chỉnh âm lượng\n"
              "`/loop <song/queue/off>` để lặp nhạc",
        inline=False
    )
    
    embed.set_footer(text="dùng /helpme <lệnh> để xem chi tiết")
    
    await ctx.send(embed=embed)
    logger.info(f"lệnh musichelp được thực hiện bởi {ctx.author}")





@bot.command(name="musicinfo")
async def music_info(ctx):
    """hiển thị thông tin chi tiết về hệ thống nhạc."""
    embed = discord.Embed(
        title="thông tin hệ thống nhạc",
        color=0x2f3136
    )
    
    # Thông tin cơ bản
    embed.add_field(
        name="tính năng",
        value="• phát nhạc từ youtube\n"
              "• hỗ trợ url và tìm kiếm\n"
              "• hàng đợi không giới hạn\n"
              "• điều khiển âm lượng\n"
              "• chế độ lặp bài/queue\n"
              "• tự động ngắt kết nối",
        inline=True
    )
    
    # Định dạng hỗ trợ
    embed.add_field(
        name="hỗ trợ",
        value="• youtube.com\n"
              "• youtu.be\n"
              "• soundcloud (dự phòng)\n"
              "• bandcamp (dự phòng)\n"
              "• playlist youtube\n"
              "• live stream",
        inline=True
    )
    
    # Giới hạn
    embed.add_field(
        name="giới hạn",
        value="• chỉ âm thanh (không video)\n"
              "• tối đa 5 phút không hoạt động\n"
              "• cần quyền kết nối voice\n"
              "• một server một thời điểm",
        inline=False
    )
    
    embed.set_footer(text="dùng /musichelp để xem danh sách lệnh")
    
    await ctx.send(embed=embed)
    logger.info(f"lệnh musicinfo được thực hiện bởi {ctx.author}")

# Cập nhật lệnh musicstats với style mới
@commands.command(name="musicstats")
async def music_stats(ctx):
    """thống kê hệ thống nhạc"""
    total_players = len(self.players)
    active_players = sum(1 for p in self.players.values() if p.current or p.queue)
    total_songs = sum(len(p.queue) + (1 if p.current else 0) for p in self.players.values())
    
    embed = discord.Embed(
        title="thống kê hệ thống nhạc",
        color=0x2f3136
    )
    
    embed.add_field(name="tổng servers", value=f"`{total_players}`", inline=True)
    embed.add_field(name="đang hoạt động", value=f"`{active_players}`", inline=True)
    embed.add_field(name="tổng bài hát", value=f"`{total_songs}`", inline=True)
    
    if ctx.guild.id in self.players:
        player = self.players[ctx.guild.id]
        embed.add_field(
            name="server này",
            value=f"queue: `{len(player.queue)}` | đang phát: `{'có' if player.current else 'không'}`",
            inline=False
        )
    
    # Thêm thông tin cache với style mới
    try:
        import os
        cache_files = len(os.listdir('./music_cache'))
        cache_size = sum(os.path.getsize(f) for f in os.listdir('./music_cache') if os.path.isfile(os.path.join('./music_cache', f)))
        cache_size_mb = cache_size / (1024 * 1024)
        embed.add_field(
            name="cache", 
            value=f"`{cache_files}` files | `{cache_size_mb:.2f}` mb", 
            inline=False
        )
    except:
        embed.add_field(name="cache", value="`không khả dụng`", inline=False)
        
    embed.set_footer(text="dùng /clearcache để xóa cache (chỉ admin)")
    
    await ctx.send(embed=embed)
    logger.info(f"lệnh musicstats được thực hiện bởi {ctx.author}")

# Lệnh General
@bot.command(name="invite")
async def invite_link(ctx):
    """Lấy liên kết mời bot và gửi trong tin nhắn riêng."""
    invite_url = discord.utils.oauth_url(
        bot.user.id, permissions=discord.Permissions(8)
    )
    embed = discord.Embed(
        title="mời bot",
        description=f"link mời bot: {invite_url}",
        color=0x5865f2
    )
    embed.set_footer(text="cảm ơn bạn đã sử dụng bot")

    try:
        await ctx.author.send(embed=embed)
        await ctx.send("đã gửi link mời vào tin nhắn riêng")
    except discord.Forbidden:
        await ctx.send("không thể gửi tin nhắn riêng, kiểm tra cài đặt dm")

    logger.info(f"link mời được yêu cầu bởi {ctx.author}")


@bot.command(name="botinfo")
async def bot_info(ctx):
    """Hiển thị thông tin bot."""
    embed = discord.Embed(
        title="thông tin bot",
        color=0x2f3136
    )

    # Thông tin cơ bản
    embed.add_field(name="tên", value=bot.user.name, inline=True)
    embed.add_field(name="id", value=f"`{bot.user.id}`", inline=True)
    embed.add_field(name="tag", value=f"`{bot.user}`", inline=True)

    # Thông tin kỹ thuật
    embed.add_field(name="python", value=platform.python_version(), inline=True)
    embed.add_field(name="discord.py", value=discord.__version__, inline=True)

    # Thông tin quy mô
    total_members = sum(guild.member_count for guild in bot.guilds)
    embed.add_field(name="servers", value=f"{len(bot.guilds)}", inline=True)
    embed.add_field(name="thành viên", value=f"{total_members}", inline=True)
    embed.add_field(name="kênh", value=f"{len(list(bot.get_all_channels()))}", inline=True)

    # Thông tin tác giả
    embed.add_field(name="👨‍💻 tác giả", value="[tanbaycu](https://tanbaycu.is-a.dev)", inline=True)
    embed.add_field(name="🔗 hỗ trợ", value="[linktr.ee/tanbaycu](https://linktr.ee/tanbaycu)", inline=True)
    embed.add_field(name="📝 phiên bản", value="2.1.0", inline=True)

    embed.set_thumbnail(url=bot.user.avatar.url if bot.user.avatar else None)
    embed.set_footer(text=f"Created with ❤️ by tanbaycu • yêu cầu bởi {ctx.author.name}")

    await ctx.send(embed=embed)
    logger.info(f"thông tin bot được yêu cầu bởi {ctx.author}")


@bot.command(name="server")
async def server_command(ctx):
    """Cung cấp thông tin về server hỗ trợ."""
    support_server_link = "https://discord.gg/GknzmQmX"

    embed = discord.Embed(
        title="server hỗ trợ",
        description=f"tham gia server hỗ trợ: {support_server_link}",
        color=0x5865f2
    )

    embed.add_field(name="thành viên", value="20+", inline=True)
    embed.add_field(name="hỗ trợ", value="24/7", inline=True)
    embed.add_field(name="phản hồi", value="15 phút", inline=True)

    embed.add_field(
        name="kênh chính",
        value="• chung: chat\n• product-news: thông báo\n• news-update: cập nhật\n• api-update: api",
        inline=False
    )

    embed.set_footer(text=f"powered by {bot.user.name}")

    try:
        await ctx.author.send(embed=embed)
        await ctx.send("đã gửi thông tin server vào tin nhắn riêng")
    except discord.Forbidden:
        embed_public = discord.Embed(
            title="không thể gửi dm",
            description=f"server hỗ trợ: {support_server_link}",
            color=0xff4757
        )
        await ctx.send(embed=embed_public)

    logger.info(f"thông tin server hỗ trợ được yêu cầu bởi {ctx.author}")


@bot.command(name="serverinfo")
async def server_info(ctx):
    """Hiển thị thông tin về server hiện tại."""
    guild = ctx.guild

    embed = discord.Embed(
        title=f"thông tin server: {guild.name}",
        color=0x2f3136,
        timestamp=datetime.now(timezone.utc),
    )

    # Thông tin cơ bản
    embed.add_field(name="id", value=f"`{guild.id}`", inline=True)
    embed.add_field(
        name="chủ server",
        value=guild.owner.mention if guild.owner else "không xác định",
        inline=True,
    )
    embed.add_field(name="thành viên", value=f"{guild.member_count}", inline=True)
    embed.add_field(
        name="ngày tạo",
        value=guild.created_at.strftime("%d/%m/%Y"),
        inline=True,
    )

    # Thông tin về kênh
    text_channels = len(guild.text_channels)
    voice_channels = len(guild.voice_channels)
    categories = len(guild.categories)
    embed.add_field(
        name="kênh",
        value=f"text: {text_channels}\nvoice: {voice_channels}\ncategories: {categories}",
        inline=True,
    )

    # Thông tin về role
    role_count = len(guild.roles) - 1  # Trừ @everyone
    embed.add_field(name="roles", value=f"{role_count}", inline=True)

    # Thông tin về emoji và sticker
    emoji_count = len(guild.emojis)
    sticker_count = len(guild.stickers) if hasattr(guild, "stickers") else 0
    embed.add_field(
        name="emoji & sticker",
        value=f"emoji: {emoji_count} | sticker: {sticker_count}",
        inline=True,
    )

    # Thông tin về boost
    if guild.premium_tier > 0:
        embed.add_field(
            name="boost",
            value=f"level {guild.premium_tier} ({guild.premium_subscription_count} boost)",
            inline=True,
        )

    # Tính toán tỉ lệ người dùng online
    online_members = sum(
        member.status != discord.Status.offline
        for member in guild.members
        if hasattr(member, "status") and member.status
    )
    online_ratio = online_members / guild.member_count if guild.member_count > 0 else 0
    embed.add_field(
        name="online",
        value=f"{online_members} ({online_ratio:.1%})",
        inline=True,
    )

    # Thiết lập hình ảnh và footer
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    
    embed.set_footer(text=f"yêu cầu bởi {ctx.author.name}")

    await ctx.send(embed=embed)
    logger.info(f"thông tin server '{guild.name}' được yêu cầu bởi {ctx.author.name}")


# Lệnh Fun
async def get_random_fact_or_joke():
    sources = [
        (
            "https://dog-api.kinduff.com/api/facts",
            lambda data: ("🐶 Sự thật về chó", data["facts"][0]),
        ),
        (
            "https://catfact.ninja/fact",
            lambda data: ("🐱 Sự thật về mèo", data["fact"]),
        ),
        (
            "http://numbersapi.com/random/trivia",
            lambda data: ("🔢 Sự thật về số", data),
        ),
        (
            "https://uselessfacts.jsph.pl/random.json?language=en",
            lambda data: ("🤔 Sự thật thú vị", data["text"]),
        ),
        (
            "https://official-joke-api.appspot.com/random_joke",
            lambda data: ("😂 Câu chuyện cười", f"{data['setup']} {data['punchline']}"),
        ),
    ]
    random.shuffle(sources)

    async with aiohttp.ClientSession() as session:
        for source, extract_data in sources:
            try:
                async with session.get(source, ssl=ssl_context) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)
                        title, content = extract_data(data)
                        return title, content
            except Exception as e:
                logger.error(f"Lỗi khi lấy dữ liệu từ {source}: {str(e)}")
                continue

    return (
        "Không thể lấy thông tin",
        "Xin lỗi, không thể lấy sự thật hoặc câu chuyện cười. Vui lòng thử lại sau.",
    )


@bot.command(name="fact")
async def random_fact(ctx):
    """Lấy sự thật hoặc câu chuyện cười ngẫu nhiên."""
    user_id = str(ctx.author.id)
    if user_id in fact_tasks:
        await ctx.send("đã bật fact rồi, dùng /stopfact để dừng")
        return

    async def send_facts():
        while True:
            try:
                async with ctx.typing():
                    title, content = await get_random_fact_or_joke()
                    translator = GoogleTranslator(source="en", target="vi")
                    translated_content = translator.translate(content)
                    
                    message = f"**{title.lower()}**\n\n"
                    message += f"english: {content}\n\n"
                    message += f"tiếng việt: {translated_content}"
                    
                    await ctx.send(message)
                await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"lỗi gửi fact: {str(e)}")
                await ctx.send("lỗi khi gửi fact, đang thử lại...")
                await asyncio.sleep(30)

    fact_tasks[user_id] = asyncio.create_task(send_facts())
    await ctx.send("bắt đầu gửi fact mỗi 30 giây, dùng /stopfact để dừng")
    logger.info(f"bắt đầu gửi fact cho {ctx.author}")


@bot.command(name="stopfact")
async def stop_fact(ctx):
    """Dừng gửi sự thật hoặc câu chuyện cười ngẫu nhiên."""
    user_id = str(ctx.author.id)
    if user_id in fact_tasks:
        fact_tasks[user_id].cancel()
        del fact_tasks[user_id]
        await ctx.send("đã dừng gửi fact")
        logger.info(f"dừng gửi fact cho {ctx.author}")
    else:
        await ctx.send("chưa bật fact, dùng /fact để bắt đầu")


@bot.command(name="quote")
async def random_quote(ctx):
    """Lấy một trích dẫn ngẫu nhiên và dịch sang tiếng Việt."""
    quote_apis = [
        (
            "https://api.quotable.io/random",
            lambda data: (data["content"], data["author"], data.get("tags", [])),
        ),
        (
            "https://api.themotivate365.com/stoic-quote",
            lambda data: (data["quote"], data["author"], []),
        ),
    ]

    async with ctx.typing():
        for api, extract_data in quote_apis:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(api, ssl=ssl_context) as response:
                        if response.status == 200:
                            data = await response.json()
                            quote, author, tags = extract_data(data)

                            translator = GoogleTranslator(source="en", target="vi")
                            translated_quote = translator.translate(quote)
                            translated_author = translator.translate(author)

                            message = f"**trích dẫn ngẫu nhiên**\n\n"
                            message += f"english: \"{quote}\"\n\n"
                            message += f"tiếng việt: \"{translated_quote}\"\n\n"
                            message += f"tác giả: {author} | {translated_author}"
                            
                            if tags:
                                message += f"\ntags: {', '.join(tags)}"

                            await ctx.send(message)
                            logger.info(f"trích dẫn được gửi cho {ctx.author}")
                            return
            except Exception as e:
                logger.error(f"lỗi khi lấy trích dẫn từ {api}: {str(e)}")
                continue

    await ctx.send("không thể lấy trích dẫn, vui lòng thử lại sau")
    logger.error("không thể lấy trích dẫn từ tất cả nguồn")


@bot.command(name="randomimage")
async def random_image(ctx):
    """Lấy và gửi một hình ảnh ngẫu nhiên."""
    image_apis = [
        ("https://source.unsplash.com/random", "unsplash"),
        ("https://picsum.photos/500", "lorem picsum"),
        ("https://api.thecatapi.com/v1/images/search", "cat api"),
        ("https://dog.ceo/api/breeds/image/random", "dog api"),
    ]

    async with ctx.typing():
        for api, source in random.sample(image_apis, len(image_apis)):
            try:
                async with aiohttp.ClientSession() as session:
                    if "thecatapi" in api or "dog.ceo" in api:
                        async with session.get(api, ssl=ssl_context) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                image_url = (
                                    data[0]["url"]
                                    if "thecatapi" in api
                                    else data["message"]
                                )
                                async with session.get(
                                    image_url, ssl=ssl_context
                                ) as img_resp:
                                    if img_resp.status == 200:
                                        data = await img_resp.read()
                                        with io.BytesIO(data) as image:
                                            file = discord.File(
                                                image, "random_image.png"
                                            )
                                            await ctx.send(f"hình ảnh từ {source}", file=file)
                                        logger.info(f"hình ảnh từ {source} gửi cho {ctx.author}")
                                        return
                    else:
                        async with session.get(api, ssl=ssl_context) as resp:
                            if resp.status == 200:
                                data = await resp.read()
                                with io.BytesIO(data) as image:
                                    file = discord.File(image, "random_image.png")
                                    await ctx.send(f"hình ảnh từ {source}", file=file)
                                logger.info(f"hình ảnh từ {source} gửi cho {ctx.author}")
                                return
            except Exception as e:
                logger.error(f"lỗi tải hình từ {api}: {str(e)}")
                continue

    await ctx.send("không thể tải hình ảnh, vui lòng thử lại sau")
    logger.error("không thể tải hình từ tất cả nguồn")


@bot.command(name="coinflip")
async def coin_flip(ctx):
    """Tung đồng xu."""
    result = random.choice(["mặt sấp", "mặt ngửa"])
    await ctx.send(f"tung đồng xu: **{result}**")
    logger.info(f"tung đồng xu cho {ctx.author}: {result}")


# Lệnh Admin
def is_admin():
    async def predicate(ctx):
        return (
            await bot.is_owner(ctx.author) or ctx.author.guild_permissions.administrator
        )

    return commands.check(predicate)


@bot.command(name="shutdown")
@is_admin()
async def shutdown(ctx):
    """Tắt bot (Chỉ dành cho chủ sở hữu hoặc admin)."""
    await ctx.send("đang tắt bot...")
    logger.warning(f"bot được tắt bởi {ctx.author}")
    await bot.close()


@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason=None):
    """Kick một thành viên khỏi server."""
    await member.kick(reason=reason)
    await ctx.send(f"đã kick {member.mention} - lý do: {reason or 'không có'}")
    logger.info(f"{member} đã bị kick bởi {ctx.author} - lý do: {reason}")


@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason=None):
    """Ban một thành viên khỏi server."""
    await member.ban(reason=reason)
    await ctx.send(f"đã ban {member.mention} - lý do: {reason or 'không có'}")
    logger.info(f"{member} đã bị ban bởi {ctx.author} - lý do: {reason}")


@bot.command(name="warning")
@commands.has_permissions(manage_messages=True)
async def warning(ctx, member: discord.Member, *, reason):
    """Cảnh cáo một thành viên."""
    
    # Tin nhắn công khai
    await ctx.send(f"**cảnh cáo** {member.mention}\nlý do: {reason}\nbởi: {ctx.author.mention}\nthời gian: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    # Tin nhắn riêng
    warning_dm = f"**bạn đã nhận cảnh cáo**\n\n"
    warning_dm += f"lý do: {reason}\n"
    warning_dm += f"bởi: {ctx.author.name}\n"
    warning_dm += f"server: {ctx.guild.name}\n"
    warning_dm += f"thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
    warning_dm += "hãy tuân thủ quy tắc server"

    try:
        await member.send(warning_dm)
        logger.info(f"đã gửi cảnh cáo dm đến {member}")
    except discord.Forbidden:
        await ctx.send(f"không thể gửi dm đến {member.mention}")
        logger.warning(f"không thể gửi dm cảnh cáo đến {member}")

    logger.info(f"{member} đã bị cảnh cáo bởi {ctx.author} - lý do: {reason}")


@bot.command(name="say")
@is_admin()
async def say(ctx, *, message):
    """Làm cho bot nói điều gì đó (Chỉ dành cho chủ sở hữu hoặc admin)."""
    await ctx.message.delete()
    await ctx.send(message)
    logger.info(f"bot nói: '{message}' theo yêu cầu của {ctx.author}")


@bot.command(name="embed")
@is_admin()
async def embed(ctx, *, message):
    """Gửi một tin nhắn nhúng (Chỉ dành cho chủ sở hữu hoặc admin)."""
    embed = discord.Embed(description=message, color=0x2f3136)
    embed.set_footer(text=f"bởi {ctx.author.name}")
    await ctx.send(embed=embed)
    logger.info(f"embed được gửi bởi {ctx.author}")


@bot.command(name="reload")
@is_admin()
async def reload(ctx, extension):
    """Tải lại một phần mở rộng của bot (Chỉ dành cho chủ sở hữu hoặc admin)."""
    try:
        await bot.reload_extension(f"cogs.{extension}")
        await ctx.send(f"đã reload {extension}")
        logger.info(f"extension {extension} đã reload bởi {ctx.author}")
    except commands.ExtensionError as e:
        await ctx.send(f"lỗi reload {extension}: {e}")
        logger.error(f"lỗi reload extension {extension}: {str(e)}")


@bot.command(name="sendcontact")
@is_admin()
async def send_contact(ctx, user: Union[discord.Member, str]):
    """Gửi thông tin liên hệ của admin đến một người dùng."""
    if isinstance(user, str):
        found_user = discord.utils.find(
            lambda m: user.lower() in m.name.lower(), ctx.guild.members
        )
        if not found_user:
            await ctx.send(f"không tìm thấy user '{user}'")
            return
        user = found_user

    contact_info = f"**thông tin liên hệ admin**\n\n"
    contact_info += f"tên: {ctx.author.name}\n"
    contact_info += f"id: {ctx.author.id}\n"
    contact_info += f"roles: {', '.join([role.name for role in ctx.author.roles if role.name != '@everyone']) or 'không có'}\n"
    contact_info += f"tham gia: {ctx.author.joined_at.strftime('%d/%m/%Y')}\n"
    contact_info += f"tạo tài khoản: {ctx.author.created_at.strftime('%d/%m/%Y')}"

    try:
        await user.send(contact_info)
        await ctx.send(f"đã gửi thông tin liên hệ đến {user.name}")
        logger.info(f"thông tin liên hệ của {ctx.author} gửi đến {user.name}")
    except discord.Forbidden:
        await ctx.send(f"không thể gửi dm đến {user.name}")
        logger.error(f"không thể gửi dm đến {user.name}")
    except Exception as e:
        await ctx.send(f"lỗi gửi tin nhắn: {str(e)}")
        logger.error(f"lỗi gửi tin nhắn đến {user.name}: {str(e)}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("không tìm thấy lệnh, dùng /helpme để xem danh sách")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("thiếu tham số, dùng /helpme <lệnh> để xem cách dùng")
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("bạn không có quyền sử dụng lệnh này")
    else:
        await ctx.send("đã xảy ra lỗi, vui lòng thử lại sau")
        logger.error(f"lỗi lệnh: {str(error)}")


# Hàm hỗ trợ
def get_context(user_id):
    if user_id not in short_term_memory:
        short_term_memory[user_id] = deque(maxlen=5)
    context = "\n".join(short_term_memory[user_id])

    cursor.execute(
        "SELECT context FROM long_term_memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1",
        (user_id,),
    )
    long_term_context = cursor.fetchone()
    if long_term_context:
        context = f"{long_term_context[0]}\n\n{context}"

    return context


def update_memory(user_id, user_message, bot_response): # Cập nhật bộ nhớ
    if user_id not in short_term_memory: # Nếu không có bộ nhớ  ngắn hạn
        short_term_memory[user_id] = deque(maxlen=5)  # Tạo bộ nhớ ngắn hạn
    short_term_memory[user_id].append(f"Người dùng: {user_message}") # Thêm tin nhắn người dùng
    short_term_memory[user_id].append(f"Trợ lý AI: {bot_response}") # Thêm phản hồi trợ lý AI

    context = "\n".join(short_term_memory[user_id]) # Kết hợp tất cả tin nhắn
    cursor.execute(
        "INSERT INTO long_term_memory (user_id, context) VALUES (?, ?)",
        (user_id, context),
    )
    conn.commit()


if __name__ == "__main__":
    discord_token = os.getenv("DISCORD_TOKEN")
    if not discord_token:
        logger.error("DISCORD_TOKEN không được cấu hình. Vui lòng kiểm tra file .env")
        sys.exit(1)
    bot.run(discord_token)

