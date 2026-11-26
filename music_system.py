import asyncio
from collections import deque
import logging
import os
from pathlib import Path
import random
import re
from typing import Dict, Optional

from colorama import Fore, Style
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

load_dotenv()
logger = logging.getLogger(__name__)

MUSIC_CHANNEL_ID = int(os.getenv("MUSIC_CHANNEL_ID", "0") or 0)
CACHE_DIR = Path(os.getenv("DATA_DIR") or "data") / "music_cache"

search_cache: Dict[int, list] = {}

ytdl_format_options = {
    "format": "bestaudio/best",
    "outtmpl": str(CACHE_DIR / "%(title)s-%(id)s.%(ext)s"),
    "restrictfilenames": True,
    "noplaylist": False,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
}

ytdl_direct_options = {**ytdl_format_options, "noplaylist": True, "extract_flat": False, "skip_download": True}
ytdl_search_options = {**ytdl_format_options, "noplaylist": True, "extract_flat": True}

ffmpeg_options = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": '-vn -filter:a "volume=0.5"',
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)
ytdl_direct = yt_dlp.YoutubeDL(ytdl_direct_options)
ytdl_search = yt_dlp.YoutubeDL(ytdl_search_options)

_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


def safe_format_duration(duration) -> str:
    if not duration:
        return "không rõ"
    try:
        total = int(float(duration))
        minutes, seconds = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        return "không rõ"


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume: float = 0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("url")
        self.duration = data.get("duration")
        self.thumbnail = data.get("thumbnail")
        self.uploader = data.get("uploader")
        self.webpage_url = data.get("webpage_url")

    @classmethod
    async def from_url(cls, url: str, *, loop=None, stream: bool = True):
        loop = loop or asyncio.get_running_loop()
        data = None
        for attempt in range(3):
            try:
                data = await loop.run_in_executor(
                    None, lambda: ytdl_direct.extract_info(url, download=not stream)
                )
                break
            except Exception:
                if attempt == 2:
                    raise
                await asyncio.sleep(2)

        if isinstance(data, dict) and "entries" in data:
            data = data["entries"][0]
        filename = data["url"] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

    @classmethod
    async def direct_process_url(cls, url: str, *, loop=None):
        loop = loop or asyncio.get_running_loop()
        try:
            target = url
            if "youtube.com" in url and "v=" in url:
                vid = url.split("v=")[1].split("&")[0]
                target = f"https://www.youtube.com/watch?v={vid}"
            elif "youtu.be" in url:
                vid = url.rstrip("/").split("/")[-1].split("?")[0]
                target = f"https://www.youtube.com/watch?v={vid}"
            return await loop.run_in_executor(
                None, lambda: ytdl_direct.extract_info(target, download=False)
            )
        except Exception as exc:
            logger.error(f"Lỗi xử lý URL {url}: {exc}")
            return None

    @classmethod
    async def search_youtube(cls, query: str, *, loop=None):
        loop = loop or asyncio.get_running_loop()
        if "youtube.com" in query or "youtu.be" in query:
            direct = await cls.direct_process_url(query, loop=loop)
            if direct:
                return direct

        for search_query in (f"ytsearch:{query}", f"ytsearch5:{query}"):
            for attempt in range(3):
                try:
                    if attempt > 0:
                        await asyncio.sleep(random.uniform(1, 3))
                    data = await loop.run_in_executor(
                        None, lambda sq=search_query: ytdl_search.extract_info(sq, download=False)
                    )
                    if data and data.get("entries"):
                        return data["entries"][0]
                    break
                except Exception as exc:
                    logger.warning(f"Search retry {attempt + 1}/3 ({search_query}): {exc}")
        return None

    @classmethod
    async def search_alternative(cls, query: str, *, loop=None):
        loop = loop or asyncio.get_running_loop()
        for alt_query in (f"soundcloud:{query}", f"bandcamp:{query}"):
            try:
                data = await loop.run_in_executor(
                    None, lambda aq=alt_query: ytdl_search.extract_info(aq, download=False)
                )
                if data and data.get("entries"):
                    return data["entries"][0]
            except Exception as exc:
                logger.warning(f"Alternative source error ({alt_query}): {exc}")
        return None


class Song:
    def __init__(self, data: dict, requester):
        self.title = data.get("title", "unknown")
        self.url = data.get("webpage_url", data.get("url", ""))
        self.duration = data.get("duration", 0)
        self.thumbnail = data.get("thumbnail", "")
        self.uploader = data.get("uploader", "unknown")
        self.requester = requester
        self.stream_url = data.get("url", "")

    def format_duration(self) -> str:
        return safe_format_duration(self.duration)


class MusicPlayer:
    def __init__(self, ctx):
        self.bot = ctx.bot
        self.guild = ctx.guild
        self.channel = ctx.channel
        self.cog = ctx.cog

        self.queue = deque()
        self.next = asyncio.Event()
        self.current: Optional[Song] = None
        self.volume = 0.5
        self.loop_song = False
        self.loop_queue = False
        self.paused = False
        self.auto_disconnect_task: Optional[asyncio.Task] = None
        self.bot.loop.create_task(self.player_loop())

    async def player_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            self.next.clear()
            if not self.queue and not self.current:
                await asyncio.sleep(1)
                continue
            if not self.current and self.queue:
                self.current = self.queue.popleft()
            if self.current:
                try:
                    source = await YTDLSource.from_url(
                        self.current.stream_url, loop=self.bot.loop, stream=True
                    )
                    source.volume = self.volume
                    voice_client = self.guild.voice_client
                    if voice_client and voice_client.is_connected():
                        voice_client.play(
                            source,
                            after=lambda _err: self.bot.loop.call_soon_threadsafe(self.next.set),
                        )
                        embed = discord.Embed(
                            title="đang phát",
                            description=f"**{self.current.title}**",
                            color=0x00FF00,
                        )
                        embed.add_field(
                            name="thời lượng", value=self.current.format_duration(), inline=True
                        )
                        embed.add_field(
                            name="yêu cầu bởi", value=self.current.requester.mention, inline=True
                        )
                        if self.current.thumbnail:
                            embed.set_thumbnail(url=self.current.thumbnail)
                        await self.channel.send(embed=embed)

                        await self.next.wait()
                        if self.loop_song:
                            continue
                        if self.loop_queue:
                            self.queue.append(self.current)
                        self.current = None
                except Exception as exc:
                    logger.error(f"Lỗi phát nhạc: {exc}")
                    await self.channel.send(f"❌ lỗi phát nhạc: {exc}")
                    self.current = None

    def start_auto_disconnect(self):
        if self.auto_disconnect_task:
            self.auto_disconnect_task.cancel()
        self.auto_disconnect_task = asyncio.create_task(self._auto_disconnect())

    async def _auto_disconnect(self):
        await asyncio.sleep(300)
        voice_client = self.guild.voice_client
        if voice_client and voice_client.is_connected():
            members = [m for m in voice_client.channel.members if not m.bot]
            if not members or (not voice_client.is_playing() and not self.queue):
                await voice_client.disconnect()
                await self.channel.send("🔌 đã tự động ngắt kết nối do không hoạt động")


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players: Dict[int, MusicPlayer] = {}
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def get_player(self, ctx) -> MusicPlayer:
        if ctx.guild.id not in self.players:
            self.players[ctx.guild.id] = MusicPlayer(ctx)
        return self.players[ctx.guild.id]

    async def cog_before_invoke(self, ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage("lệnh nhạc không thể dùng trong dm")
        if MUSIC_CHANNEL_ID and ctx.channel.id != MUSIC_CHANNEL_ID:
            await ctx.send(f"❌ lệnh nhạc chỉ có thể sử dụng trong kênh <#{MUSIC_CHANNEL_ID}>")
            raise commands.CheckFailure("Sai kênh nhạc")

    @commands.command(name="join", aliases=["connect", "j"])
    async def join(self, ctx):
        if not ctx.author.voice:
            return await ctx.send("❌ bạn phải ở trong voice channel để bot kết nối")
        channel = ctx.author.voice.channel
        if ctx.voice_client:
            if ctx.voice_client.channel == channel:
                return await ctx.send("ℹ️ bot đã ở trong channel này rồi")
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()
        await ctx.send(f"✅ đã kết nối vào **{channel.name}**")

    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx, *, query: str):
        if not ctx.voice_client:
            if ctx.author.voice:
                await ctx.invoke(self.join)
            else:
                return await ctx.send("❌ bạn cần vào voice channel trước")

        if query.isdigit():
            choice = int(query)
            results = search_cache.get(ctx.guild.id, [])
            if 1 <= choice <= len(results):
                selected = results[choice - 1]
                return await self._enqueue_entry(ctx, selected)
            return await ctx.send("❌ số thứ tự không hợp lệ hoặc chưa tìm kiếm.")

        await ctx.send(f"🔍 đang tìm kiếm: **{query}**...")
        if _URL_PATTERN.match(query):
            data = await YTDLSource.direct_process_url(query)
        else:
            data = await YTDLSource.search_youtube(query) or await YTDLSource.search_alternative(query)

        if not data:
            return await ctx.send("❌ không tìm thấy kết quả phù hợp")
        await self._enqueue_entry(ctx, data)

    async def _enqueue_entry(self, ctx, data: dict):
        song = Song(data, ctx.author)
        player = self.get_player(ctx)
        if player.auto_disconnect_task:
            player.auto_disconnect_task.cancel()

        if not ctx.voice_client.is_playing() and not player.current:
            player.current = song
        else:
            player.queue.append(song)
            embed = discord.Embed(
                title="đã thêm vào hàng đợi", description=f"**{song.title}**", color=0x0099FF
            )
            embed.add_field(name="vị trí", value=f"#{len(player.queue)}", inline=True)
            embed.add_field(name="thời lượng", value=song.format_duration(), inline=True)
            await ctx.send(embed=embed)

    @commands.command(name="search")
    async def search(self, ctx, *, query: Optional[str] = None):
        if not query:
            return await ctx.send("❌ vui lòng nhập từ khóa tìm kiếm!")
        await ctx.send(f"🔍 đang tìm kiếm: **{query}**...")
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None, lambda: yt_dlp.YoutubeDL({"quiet": True}).extract_info(f"ytsearch5:{query}", download=False)
        )
        entries = (data or {}).get("entries") or []
        if not entries:
            return await ctx.send("❌ không tìm thấy kết quả!")
        search_cache[ctx.guild.id] = entries
        lines = [
            f"`{idx}.` **{e.get('title', 'không rõ')}** ({safe_format_duration(e.get('duration'))})"
            for idx, e in enumerate(entries[:5], 1)
        ]
        embed = discord.Embed(title=f"🔍 kết quả: {query}", description="\n".join(lines), color=0x2F3136)
        embed.set_footer(text="dùng /play <số> để phát")
        await ctx.send(embed=embed)

    @commands.command(name="musicstats")
    async def music_stats(self, ctx):
        """Thống kê hệ thống phát nhạc và dung lượng cache."""
        total_players = len(self.players)
        active_players = sum(1 for p in self.players.values() if p.current or p.queue)
        total_songs = sum(len(p.queue) + (1 if p.current else 0) for p in self.players.values())
        files = [f for f in CACHE_DIR.iterdir() if f.is_file()] if CACHE_DIR.exists() else []
        cache_mb = sum(f.stat().st_size for f in files) / (1024 * 1024)

        embed = discord.Embed(title="thống kê hệ thống nhạc", color=0x2F3136)
        embed.add_field(name="servers", value=f"`{total_players}`", inline=True)
        embed.add_field(name="đang phát", value=f"`{active_players}`", inline=True)
        embed.add_field(name="bài hát", value=f"`{total_songs}`", inline=True)
        embed.add_field(name="cache", value=f"`{len(files)}` files | `{cache_mb:.2f}` MB", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="pause")
    async def pause(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            self.get_player(ctx).paused = True
            await ctx.send("⏸️ đã tạm dừng nhạc")
        else:
            await ctx.send("❌ không có nhạc đang phát")

    @commands.command(name="resume")
    async def resume(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            self.get_player(ctx).paused = False
            await ctx.send("▶️ đã tiếp tục phát nhạc")
        else:
            await ctx.send("❌ nhạc không bị tạm dừng")

    @commands.command(name="skip", aliases=["s"])
    async def skip(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("⏭️ đã bỏ qua bài hát")
        else:
            await ctx.send("❌ không có nhạc đang phát")

    @commands.command(name="stopmusic")
    async def stop(self, ctx):
        player = self.get_player(ctx)
        player.queue.clear()
        player.current = None
        if player.auto_disconnect_task:
            player.auto_disconnect_task.cancel()
        if ctx.voice_client:
            if ctx.voice_client.is_playing():
                ctx.voice_client.stop()
            await ctx.voice_client.disconnect()
        await ctx.send("⏹️ đã dừng nhạc và ngắt kết nối")

    @commands.command(name="queue", aliases=["q"])
    async def queue(self, ctx):
        player = self.get_player(ctx)
        if not player.queue and not player.current:
            return await ctx.send("📭 hàng đợi trống")
        embed = discord.Embed(title="📋 hàng đợi nhạc", color=0x0099FF)
        if player.current:
            embed.add_field(
                name="🎵 đang phát",
                value=f"**{player.current.title}** - {player.current.requester.mention}",
                inline=False,
            )
        if player.queue:
            items = [f"`{i}.` **{s.title}**" for i, s in enumerate(list(player.queue)[:10], 1)]
            embed.add_field(name=f"⏭️ tiếp theo ({len(player.queue)})", value="\n".join(items), inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="volume", aliases=["vol"])
    async def volume(self, ctx, volume: Optional[int] = None):
        player = self.get_player(ctx)
        if volume is None:
            return await ctx.send(f"🔊 âm lượng: **{int(player.volume * 100)}%**")
        if not 0 <= volume <= 100:
            return await ctx.send("❌ âm lượng phải từ 0 đến 100")
        player.volume = volume / 100.0
        if ctx.voice_client and ctx.voice_client.source:
            ctx.voice_client.source.volume = player.volume
        await ctx.send(f"🔊 đã đặt âm lượng thành **{volume}%**")

    @commands.command(name="disconnect", aliases=["dc", "leave"])
    async def disconnect(self, ctx):
        if ctx.voice_client:
            player = self.get_player(ctx)
            player.queue.clear()
            player.current = None
            if player.auto_disconnect_task:
                player.auto_disconnect_task.cancel()
            await ctx.voice_client.disconnect()
            await ctx.send("🔌 đã ngắt kết nối")
        else:
            await ctx.send("❌ bot không ở trong voice channel")


async def setup(bot):
    await bot.add_cog(Music(bot))
    logger.info(f"{Fore.GREEN}✅ music system loaded successfully{Style.RESET_ALL}")
