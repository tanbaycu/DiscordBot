import discord
from discord.ext import commands
import asyncio
import yt_dlp
import logging
from collections import deque
import re
import time
from typing import Optional, Dict, List
import aiohttp
from colorama import Fore, Style
import random
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Thêm ID kênh riêng cho nhạc
MUSIC_CHANNEL_ID = int(os.getenv("MUSIC_CHANNEL_ID", "1377887719157665872"))

# Tạo thư mục cache nếu chưa tồn tại
os.makedirs("./music_cache", exist_ok=True)

# Dictionary để lưu kết quả search cho mỗi guild
search_cache = {}

# YouTube-DL options được cập nhật để fix lỗi format
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': './music_cache/%(title)s-%(id)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'referer': 'https://www.youtube.com/',
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-us,en;q=0.5',
        'Accept-Encoding': 'gzip,deflate',
        'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
        'Keep-Alive': '300',
        'Connection': 'keep-alive',
    }
}

# Tạo instance riêng cho URL trực tiếp
ytdl_direct_options = ytdl_format_options.copy()
ytdl_direct_options['noplaylist'] = True
ytdl_direct_options['extract_flat'] = False
ytdl_direct_options['skip_download'] = True

# Tạo instance riêng cho tìm kiếm
ytdl_search_options = ytdl_format_options.copy()
ytdl_search_options['noplaylist'] = True
ytdl_search_options['extract_flat'] = True

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -filter:a "volume=0.5"'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)
ytdl_direct = yt_dlp.YoutubeDL(ytdl_direct_options)
ytdl_search = yt_dlp.YoutubeDL(ytdl_search_options)

def safe_format_duration(duration):
    """Hàm an toàn để format thời lượng từ float/int thành string"""
    if not duration:
        return "không rõ"
    
    try:
        duration_int = int(float(duration))
        minutes, seconds = divmod(duration_int, 60)
        hours, minutes = divmod(minutes, 60)
        
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        return "không rõ"

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')
        self.uploader = data.get('uploader')
        self.webpage_url = data.get('webpage_url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        try:
            for attempt in range(3):
                try:
                    data = await loop.run_in_executor(None, lambda: ytdl_direct.extract_info(url, download=not stream))
                    break
                except Exception as e:
                    if attempt == 2:
                        raise e
                    await asyncio.sleep(2)
                    logger.warning(f"{Fore.YELLOW}Thử lại lần {attempt + 2}/3 cho URL: {url}{Style.RESET_ALL}")
            
            if 'entries' in data:
                data = data['entries'][0]
            
            filename = data['url'] if stream else ytdl.prepare_filename(data)
            return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)
        except Exception as e:
            logger.error(f"{Fore.RED}lỗi tải nhạc từ {url}: {str(e)}{Style.RESET_ALL}")
            raise e

    @classmethod
    async def direct_process_url(cls, url, *, loop=None):
        """Xử lý URL trực tiếp không qua tìm kiếm"""
        loop = loop or asyncio.get_event_loop()
        try:
            logger.info(f"{Fore.CYAN}Xử lý URL trực tiếp: {url}{Style.RESET_ALL}")
            
            if "youtube.com" in url or "youtu.be" in url:
                video_id = None
                if "youtube.com" in url and "v=" in url:
                    video_id = url.split("v=")[1].split("&")[0]
                elif "youtu.be" in url:
                    video_id = url.split("/")[-1].split("?")[0]
                
                if video_id:
                    direct_url = f"https://www.youtube.com/watch?v={video_id}"
                    logger.info(f"{Fore.CYAN}Xử lý YouTube ID: {video_id}{Style.RESET_ALL}")
                    
                    data = await loop.run_in_executor(
                        None, 
                        lambda: ytdl_direct.extract_info(direct_url, download=False)
                    )
                    return data
            
            data = await loop.run_in_executor(
                None, 
                lambda: ytdl_direct.extract_info(url, download=False)
            )
            return data
            
        except Exception as e:
            logger.error(f"{Fore.RED}Lỗi xử lý URL trực tiếp {url}: {str(e)}{Style.RESET_ALL}")
            return None

    @classmethod
    async def search_youtube(cls, query, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        
        if "youtube.com" in query or "youtu.be" in query:
            try:
                return await cls.direct_process_url(query, loop=loop)
            except Exception as e:
                logger.error(f"{Fore.RED}Lỗi xử lý URL YouTube: {str(e)}{Style.RESET_ALL}")
        
        search_queries = [
            f"ytsearch:{query}",
            f"ytsearch5:{query}",
        ]
        
        for search_query in search_queries:
            try:
                logger.info(f"{Fore.CYAN}Đang tìm kiếm: {search_query}{Style.RESET_ALL}")
                
                for attempt in range(3):
                    try:
                        if attempt > 0:
                            delay = random.uniform(1, 3)
                            await asyncio.sleep(delay)
                        
                        data = await loop.run_in_executor(
                            None, 
                            lambda: ytdl_search.extract_info(search_query, download=False)
                        )
                        
                        if 'entries' in data and data['entries']:
                            logger.info(f"{Fore.GREEN}Tìm thấy kết quả từ: {search_query}{Style.RESET_ALL}")
                            return data['entries'][0]
                        break
                        
                    except Exception as e:
                        error_msg = str(e).lower()
                        if "sign in" in error_msg or "bot" in error_msg:
                            logger.warning(f"{Fore.YELLOW}YouTube bot detection, thử lại sau {attempt + 1}/3{Style.RESET_ALL}")
                            if attempt < 2:
                                await asyncio.sleep(random.uniform(2, 5))
                                continue
                        else:
                            logger.error(f"{Fore.RED}Lỗi tìm kiếm {search_query}: {str(e)}{Style.RESET_ALL}")
                            break
                            
            except Exception as e:
                logger.error(f"{Fore.RED}Lỗi với query {search_query}: {str(e)}{Style.RESET_ALL}")
                continue
        
        return None

    @classmethod
    async def search_alternative(cls, query, *, loop=None):
        """Tìm kiếm từ các nguồn thay thế"""
        loop = loop or asyncio.get_event_loop()
        
        alternative_queries = [
            f"soundcloud:{query}",
            f"bandcamp:{query}",
            f"generic:{query}",
        ]
        
        for alt_query in alternative_queries:
            try:
                logger.info(f"{Fore.CYAN}Thử nguồn thay thế: {alt_query}{Style.RESET_ALL}")
                data = await loop.run_in_executor(
                    None, 
                    lambda: ytdl_search.extract_info(alt_query, download=False)
                )
                
                if 'entries' in data and data['entries']:
                    logger.info(f"{Fore.GREEN}Tìm thấy từ nguồn thay thế: {alt_query}{Style.RESET_ALL}")
                    return data['entries'][0]
                    
            except Exception as e:
                logger.error(f"{Fore.RED}Lỗi nguồn thay thế {alt_query}: {str(e)}{Style.RESET_ALL}")
                continue
        
        return None

class Song:
    def __init__(self, data, requester):
        self.title = data.get('title', 'unknown')
        self.url = data.get('webpage_url', data.get('url', ''))
        self.duration = data.get('duration', 0)
        self.thumbnail = data.get('thumbnail', '')
        self.uploader = data.get('uploader', 'unknown')
        self.requester = requester
        self.stream_url = data.get('url', '')
        
    def format_duration(self):
        """Format thời lượng an toàn"""
        return safe_format_duration(self.duration)

class MusicPlayer:
    def __init__(self, ctx):
        self.bot = ctx.bot
        self.guild = ctx.guild
        self.channel = ctx.channel
        self.cog = ctx.cog
        
        self.queue = deque()
        self.next = asyncio.Event()
        self.current = None
        self.volume = 0.5
        self.loop_song = False
        self.loop_queue = False
        self.shuffle = False
        self.paused = False
        self.auto_disconnect_task = None
        
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
                    source = await YTDLSource.from_url(self.current.stream_url, loop=self.bot.loop, stream=True)
                    source.volume = self.volume
                    
                    voice_client = self.guild.voice_client
                    if voice_client and voice_client.is_connected():
                        voice_client.play(source, after=lambda e: self.bot.loop.call_soon_threadsafe(self.next.set))
                        
                        embed = discord.Embed(
                            title="đang phát",
                            description=f"**{self.current.title}**",
                            color=0x00ff00
                        )
                        embed.add_field(name="thời lượng", value=self.current.format_duration(), inline=True)
                        embed.add_field(name="yêu cầu bởi", value=self.current.requester.mention, inline=True)
                        embed.add_field(name="kênh", value=self.current.uploader, inline=True)
                        
                        if self.current.thumbnail:
                            embed.set_thumbnail(url=self.current.thumbnail)
                            
                        await self.channel.send(embed=embed)
                        logger.info(f"{Fore.GREEN}phát nhạc: {self.current.title} tại {self.guild.name}{Style.RESET_ALL}")
                        
                        await self.next.wait()
                        
                        if self.loop_song:
                            continue
                        elif self.loop_queue:
                            self.queue.append(self.current)
                            
                        self.current = None
                        
                except Exception as e:
                    logger.error(f"{Fore.RED}lỗi phát nhạc: {str(e)}{Style.RESET_ALL}")
                    await self.channel.send(f"❌ lỗi phát nhạc: {str(e)}")
                    self.current = None

    def start_auto_disconnect(self):
        """Bắt đầu đếm ngược tự động ngắt kết nối"""
        if self.auto_disconnect_task:
            self.auto_disconnect_task.cancel()
        self.auto_disconnect_task = asyncio.create_task(self._auto_disconnect())

    async def _auto_disconnect(self):
        """Tự động ngắt kết nối sau 300 giây (5 phút) không hoạt động"""
        await asyncio.sleep(300)
        voice_client = self.guild.voice_client
        if voice_client and voice_client.is_connected():
            members = [m for m in voice_client.channel.members if not m.bot]
            if not members or (not voice_client.is_playing() and not self.queue):
                await voice_client.disconnect()
                await self.channel.send("🔌 đã tự động ngắt kết nối do không hoạt động")
                logger.info(f"{Fore.YELLOW}tự động ngắt kết nối tại {self.guild.name}{Style.RESET_ALL}")

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players: Dict[int, MusicPlayer] = {}
        
    def get_player(self, ctx):
        try:
            player = self.players[ctx.guild.id]
        except KeyError:
            player = MusicPlayer(ctx)
            self.players[ctx.guild.id] = player
        return player

    async def cog_before_invoke(self, ctx):
        """Kiểm tra trước khi thực hiện lệnh nhạc"""
        if not ctx.guild:
            raise commands.NoPrivateMessage("lệnh nhạc không thể dùng trong dm")
            
        # Kiểm tra xem lệnh có được gọi từ kênh nhạc không
        if ctx.channel.id != MUSIC_CHANNEL_ID:
            music_channel = self.bot.get_channel(MUSIC_CHANNEL_ID)
            if music_channel:
                await ctx.send(f"❌ lệnh nhạc chỉ có thể sử dụng trong kênh <#{MUSIC_CHANNEL_ID}>")
            else:
                await ctx.send(f"❌ lệnh nhạc chỉ có thể sử dụng trong kênh nhạc")
            raise commands.CheckFailure("Lệnh nhạc chỉ có thể sử dụng trong kênh nhạc")

    @commands.command(name="join", aliases=["connect", "j"])
    async def join(self, ctx):
        """kết nối bot vào voice channel"""
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
        logger.info(f"{Fore.GREEN}kết nối voice tại {ctx.guild.name} - {channel.name}{Style.RESET_ALL}")

    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx, *, query):
        """phát nhạc từ youtube url hoặc tìm kiếm"""
        if not ctx.voice_client:
            if ctx.author.voice:
                await ctx.invoke(self.join)
            else:
                return await ctx.send("❌ bạn cần vào voice channel hoặc bot cần được kết nối trước")
        
        # Kiểm tra nếu query là số (chọn từ kết quả search)
        if query.isdigit():
            choice = int(query)
            guild_id = ctx.guild.id
            
            # Kiểm tra xem có kết quả search cache không
            if guild_id in search_cache and search_cache[guild_id]:
                if 1 <= choice <= len(search_cache[guild_id]):
                    # Lấy bài hát từ cache
                    selected_entry = search_cache[guild_id][choice - 1]
                    await ctx.send(f"🎯 đã chọn bài số {choice}: **{selected_entry.get('title', 'unknown')}**")
                    
                    # Xử lý bài hát được chọn
                    song = Song(selected_entry, ctx.author)
                    player = self.get_player(ctx)
                    
                    if player.auto_disconnect_task:
                        player.auto_disconnect_task.cancel()
                    
                    if not ctx.voice_client.is_playing() and not player.current:
                        player.current = song
                    else:
                        player.queue.append(song)
                        embed = discord.Embed(
                            title="đã thêm vào hàng đợi",
                            description=f"**{song.title}**",
                            color=0x0099ff
                        )
                        embed.add_field(name="vị trí", value=f"#{len(player.queue)}", inline=True)
                        embed.add_field(name="thời lượng", value=song.format_duration(), inline=True)
                        embed.add_field(name="yêu cầu bởi", value=ctx.author.mention, inline=True)
                        
                        if song.thumbnail:
                            embed.set_thumbnail(url=song.thumbnail)
                            
                        await ctx.send(embed=embed)
                    return
                else:
                    return await ctx.send(f"❌ số {choice} không hợp lệ! chọn từ 1-{len(search_cache[guild_id])}")
            else:
                return await ctx.send("❌ không có kết quả search nào! sử dụng `/search <từ khóa>` trước")
            
        # Gửi thông báo đang xử lý
        processing_msg = await ctx.send(f"🔍 đang tìm kiếm: **{query}**...")
        
        url_pattern = re.compile(
            r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\$$\$$,]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        )
        
        data = None
        
        if url_pattern.match(query):
            try:
                data = await YTDLSource.direct_process_url(query)
                if not data:
                    return await ctx.send("❌ không thể tải nhạc từ url này")
            except Exception as e:
                logger.error(f"{Fore.RED}Lỗi với URL: {str(e)}{Style.RESET_ALL}")
                return await ctx.send(f"❌ lỗi tải từ url: {str(e)}")
        else:
            try:
                data = await YTDLSource.search_youtube(query)
                
                if not data:
                    await ctx.send("⚠️ youtube gặp vấn đề, đang thử nguồn khác...")
                    data = await YTDLSource.search_alternative(query)
                    
                if not data:
                    return await ctx.send("❌ không tìm thấy kết quả từ tất cả nguồn")
                    
            except Exception as e:
                logger.error(f"{Fore.RED}Lỗi tìm kiếm: {str(e)}{Style.RESET_ALL}")
                return await ctx.send(f"❌ lỗi tìm kiếm: {str(e)}")
                
        song = Song(data, ctx.author)
        player = self.get_player(ctx)
        
        if player.auto_disconnect_task:
            player.auto_disconnect_task.cancel()
        
        if not ctx.voice_client.is_playing() and not player.current:
            player.current = song
        else:
            player.queue.append(song)
            embed = discord.Embed(
                title="đã thêm vào hàng đợi",
                description=f"**{song.title}**",
                color=0x0099ff
            )
            embed.add_field(name="vị trí", value=f"#{len(player.queue)}", inline=True)
            embed.add_field(name="thời lượng", value=song.format_duration(), inline=True)
            embed.add_field(name="yêu cầu bởi", value=ctx.author.mention, inline=True)
            
            if song.thumbnail:
                embed.set_thumbnail(url=song.thumbnail)
                
            await ctx.send(embed=embed)

    @commands.command(name="search")
    async def search(self, ctx, *, query=None):
        """tìm kiếm nhạc trên youtube và hiển thị kết quả"""
        if not query:
            return await ctx.send("❌ vui lòng nhập từ khóa tìm kiếm!")
            
        await ctx.send(f"🔍 đang tìm kiếm: **{query}**...")
        
        try:
            search_query = f"ytsearch5:{query}"
            data = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: yt_dlp.YoutubeDL({'quiet': True}).extract_info(search_query, download=False)
            )
            
            if not data or 'entries' not in data or not data['entries']:
                return await ctx.send("❌ không tìm thấy kết quả!")
                
            # Lưu kết quả vào cache
            guild_id = ctx.guild.id
            search_cache[guild_id] = data['entries']
            
            embed = discord.Embed(
                title=f"🔍 kết quả tìm kiếm: {query}",
                color=0x2f3136
            )
            
            results = []
            for i, entry in enumerate(data['entries'][:5], 1):
                duration_str = safe_format_duration(entry.get('duration', 0))
                    
                results.append(
                    f"`{i}.` **{entry.get('title', 'không rõ')}**\n"
                    f"    ⏱️ {duration_str} | 👤 {entry.get('uploader', 'không rõ')}"
                )
                
            embed.description = "\n\n".join(results)
            embed.set_footer(text="dùng /play <số> hoặc /play <url> để phát")
            
            await ctx.send(embed=embed)
            logger.info(f"lệnh search được thực hiện bởi {ctx.author} - lưu {len(data['entries'])} kết quả")
            
        except Exception as e:
            logger.error(f"lỗi tìm kiếm: {str(e)}")
            await ctx.send("❌ lỗi khi tìm kiếm!")

    @commands.command(name="clearsearch")
    async def clear_search(self, ctx):
        """xóa cache kết quả search"""
        guild_id = ctx.guild.id
        if guild_id in search_cache:
            del search_cache[guild_id]
            await ctx.send("✅ đã xóa cache kết quả search")
        else:
            await ctx.send("ℹ️ không có cache search nào để xóa")

    @commands.command(name="pause")
    async def pause(self, ctx):
        """tạm dừng nhạc"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            player = self.get_player(ctx)
            player.paused = True
            await ctx.send("⏸️ đã tạm dừng nhạc")
        else:
            await ctx.send("❌ không có nhạc đang phát")

    @commands.command(name="resume")
    async def resume(self, ctx):
        """tiếp tục phát nhạc"""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            player = self.get_player(ctx)
            player.paused = False
            await ctx.send("▶️ đã tiếp tục phát nhạc")
        else:
            await ctx.send("❌ nhạc không bị tạm dừng")

    @commands.command(name="skip", aliases=["s"])
    async def skip(self, ctx):
        """bỏ qua bài hát hiện tại"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("⏭️ đã bỏ qua bài hát")
        else:
            await ctx.send("❌ không có nhạc đang phát")

    @commands.command(name="stopmusic")
    async def stop(self, ctx):
        """dừng nhạc và xóa hàng đợi"""
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
        logger.info(f"{Fore.YELLOW}dừng nhạc tại {ctx.guild.name}{Style.RESET_ALL}")

    @commands.command(name="queue", aliases=["q"])
    async def queue(self, ctx):
        """hiển thị hàng đợi nhạc"""
        player = self.get_player(ctx)
        
        if not player.queue and not player.current:
            return await ctx.send("📭 hàng đợi trống")
            
        embed = discord.Embed(title="📋 hàng đợi nhạc", color=0x0099ff)
        
        if player.current:
            embed.add_field(
                name="🎵 đang phát",
                value=f"**{player.current.title}** - {player.current.requester.mention}",
                inline=False
            )
            
        if player.queue:
            queue_list = []
            for i, song in enumerate(list(player.queue)[:10], 1):
                queue_list.append(f"`{i}.` **{song.title}** - {song.requester.mention}")
                
            embed.add_field(
                name=f"⏭️ tiếp theo ({len(player.queue)} bài)",
                value="\n".join(queue_list),
                inline=False
            )
            
            if len(player.queue) > 10:
                embed.add_field(
                    name="➕ và hơn thế nữa",
                    value=f"còn {len(player.queue) - 10} bài khác",
                    inline=False
                )
                
        await ctx.send(embed=embed)

    @commands.command(name="volume", aliases=["vol"])
    async def volume(self, ctx, volume: int = None):
        """điều chỉnh âm lượng (0-100)"""
        if volume is None:
            player = self.get_player(ctx)
            return await ctx.send(f"🔊 âm lượng hiện tại: **{int(player.volume * 100)}%**")
            
        if not 0 <= volume <= 100:
            return await ctx.send("❌ âm lượng phải từ 0 đến 100")
            
        player = self.get_player(ctx)
        player.volume = volume / 100
        
        if ctx.voice_client and ctx.voice_client.source:
            ctx.voice_client.source.volume = player.volume
            
        await ctx.send(f"🔊 đã đặt âm lượng thành **{volume}%**")

    @commands.command(name="disconnect", aliases=["dc", "leave"])
    async def disconnect(self, ctx):
        """ngắt kết nối bot khỏi voice channel"""
        if ctx.voice_client:
            player = self.get_player(ctx)
            player.queue.clear()
            player.current = None
            
            if player.auto_disconnect_task:
                player.auto_disconnect_task.cancel()
                
            await ctx.voice_client.disconnect()
            await ctx.send("🔌 đã ngắt kết nối")
            logger.info(f"{Fore.YELLOW}ngắt kết nối voice tại {ctx.guild.name}{Style.RESET_ALL}")
        else:
            await ctx.send("❌ bot không ở trong voice channel")

# Async setup function
async def setup(bot):
    await bot.add_cog(Music(bot))
    logger.info(f"{Fore.GREEN}✅ music system loaded successfully{Style.RESET_ALL}")
