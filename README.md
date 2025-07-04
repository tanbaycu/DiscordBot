# DiscordBot# 🤖 Discord Bot with AI Integration

**Created by [tanbaycu](https://tanbaycu.is-a.dev)** | **Support: [linktr.ee/tanbaycu](https://linktr.ee/tanbaycu)**

## 📚 Overview

This is a sophisticated, multi-functional Discord bot developed in Python, featuring advanced AI integration through Google's Gemini API. The bot is designed to enhance user experience on Discord servers by combining intelligent conversational AI, smart memory management, music playback capabilities, and various entertainment features.

## 🌟 Core Features

### 1. 💬 Intelligent AI Chat System
- **Gemini API Integration**: Utilizes Google's Gemini 2.0 Flash Lite model for natural, context-aware responses
- **Advanced Prompt Engineering**: Implements optimized prompts for GenZ-style conversational flow
- **Multi-API Key Management**: Supports multiple API keys with automatic failover and rate limiting
- **Context-Aware Responses**: Maintains conversation flow with intelligent context understanding

### 2. 🧠 Advanced Memory Management
- **Short-term Memory**: In-memory conversation context using Python deques (last 5 exchanges)
- **Long-term Memory**: SQLite database for persistent conversation history
- **Memory Controls**: Commands to clear specific or all memory contexts
- **User-specific Memory**: Individual memory contexts for each user

### 3. 🎵 Comprehensive Music System
- **YouTube Integration**: Full YouTube search and playback support via yt-dlp
- **Queue Management**: Advanced queue system with skip, pause, resume functionality
- **Multiple Sources**: Support for direct URLs and search queries
- **Auto-disconnect**: Intelligent voice channel management with auto-disconnect
- **Volume Control**: Adjustable audio volume and playback settings

### 4. 🛠️ Powerful Administration Tools
- **Moderation Commands**: Kick, ban, warning system with DM notifications
- **Permission Management**: Role-based command access control
- **Server Information**: Detailed server and user information displays
- **Bot Control**: Stop/continue bot responses, shutdown commands

### 5. 🎉 Entertainment & Utility Features
- **Random Content**: Facts, quotes, images from multiple API sources
- **Coin Flip**: Simple entertainment command
- **Fact Streaming**: Continuous fact delivery with start/stop controls
- **Embed Creation**: Rich message formatting for administrators

### 6. 🔒 Security & Error Handling
- **Environment Variables**: Secure configuration using .env files
- **Comprehensive Logging**: Detailed logging system with colored output
- **Error Recovery**: Robust error handling with automatic retry mechanisms
- **Rate Limiting**: Smart API rate limit management across multiple keys

### 7. 📊 Monitoring & Debugging
- **Real-time Logging**: Comprehensive logging to both file and console
- **Command Tracking**: User action logging for moderation purposes
- **Performance Monitoring**: Bot latency and response time tracking
- **Error Reporting**: Detailed error traceback and reporting

## 🏗️ Architecture & Design

### Core Components

#### 1. **Discord Event Handling**
The bot leverages `discord.py` for comprehensive Discord integration:

```python
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    if message.content.startswith(bot.command_prefix):
        await bot.process_commands(message)
    elif gemini_responses_active:
        # Process regular messages with AI
```

#### 2. **AI Integration Architecture**
Advanced Gemini API integration with failover support:

```python
class APIKeyManager:
    def __init__(self, api_keys: List[str]):
        self.api_keys = api_keys
        self.current_index = 0
        self.rate_limits: Dict[str, float] = {}
    
    def switch_to_next_key(self):
        # Automatic API key rotation
```

#### 3. **Memory Management System**
Dual-layer memory system for optimal performance:

```python
def update_memory(user_id, user_message, bot_response):
    # Update short-term memory (RAM)
    # Persist to long-term memory (SQLite)
```

#### 4. **Music System Architecture**
Comprehensive music playback system:

```python
class MusicPlayer:
    def __init__(self, ctx):
        self.queue = asyncio.Queue()
        self.voice_client = None
        self.current_song = None
    
    async def player_loop(self):
        # Continuous music playback loop
```

#### 5. **Command System**
Structured command implementation with permission controls:

```python
@bot.command(name="command_name")
@is_admin()  # Permission decorator
async def command_function(ctx):
    # Command implementation
```

## 🔧 Advanced Configuration

### Environment Variables
The bot uses environment variables for secure configuration:

- `DISCORD_TOKEN`: Discord bot token
- `GEMINI_API_KEY_1/2/3`: Multiple Gemini API keys
- `GITHUB_TOKEN`: GitHub token for Gist creation
- `MUSIC_CHANNEL_ID`: Dedicated music channel ID
- `ADMIN_USER_ID`: Bot administrator user ID

### Music System Configuration
Advanced yt-dlp configuration for optimal audio quality:

```python
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': './music_cache/%(title)s-%(id)s.%(ext)s',
    'restrictfilenames': True,
    'user_agent': 'Mozilla/5.0...',
    # Additional optimization options
}
```

### AI Prompt Engineering
Sophisticated prompt design for GenZ conversational style:

```python
OPTIMIZED_PROMPT = """
# Pure Text GenZ AI
Bạn là chubedan - một AI GenZ của tanbaycu
- Zero icons, pure markdown
- Natural flow, smart responses
- Casual chat với độ sâu
"""
```

## 📋 Command Reference

### Basic Commands
| Command | Description | Usage |
|---------|-------------|-------|
| `/ping` | Check bot latency | `/ping` |
| `/helpme` | Command help system | `/helpme [command]` |
| `/botinfo` | Bot information | `/botinfo` |
| `/serverinfo` | Server statistics | `/serverinfo` |

### Memory Management
| Command | Description | Usage |
|---------|-------------|-------|
| `/clearmemory` | Clear short-term memory | `/clearmemory` |
| `/clearall` | Clear all memory | `/clearall` |
| `/stop` | Pause AI responses | `/stop` |
| `/continue` | Resume AI responses | `/continue` |

### Music System
| Command | Description | Usage |
|---------|-------------|-------|
| `/play <query>` | Play music | `/play Never Gonna Give You Up` |
| `/pause` | Pause playback | `/pause` |
| `/resume` | Resume playback | `/resume` |
| `/skip` | Skip current song | `/skip` |
| `/queue` | Show music queue | `/queue` |
| `/volume <level>` | Set volume (0-100) | `/volume 50` |
| `/disconnect` | Leave voice channel | `/disconnect` |

### Entertainment
| Command | Description | Usage |
|---------|-------------|-------|
| `/fact` | Start fact streaming | `/fact` |
| `/stopfact` | Stop fact streaming | `/stopfact` |
| `/quote` | Random inspirational quote | `/quote` |
| `/randomimage` | Random image from APIs | `/randomimage` |
| `/coinflip` | Flip a coin | `/coinflip` |

### Administration (Admin Only)
| Command | Description | Usage |
|---------|-------------|-------|
| `/kick <user> [reason]` | Kick member | `/kick @user Spam` |
| `/ban <user> [reason]` | Ban member | `/ban @user Inappropriate behavior` |
| `/warning <user> <reason>` | Warn member | `/warning @user Breaking rules` |
| `/say <message>` | Bot speak | `/say Hello everyone!` |
| `/embed <message>` | Send embed | `/embed Welcome to our server!` |
| `/shutdown` | Shutdown bot | `/shutdown` |

## 🚀 Technical Features

### Performance Optimizations
- **Async/Await Pattern**: Full asynchronous operation for scalability
- **Connection Pooling**: Efficient HTTP session management
- **Caching System**: Music file caching for faster playback
- **Memory Optimization**: Intelligent memory usage with deque limits

### Error Handling & Recovery
- **Graceful Degradation**: Continues operation even with partial failures
- **Automatic Retry**: Smart retry mechanisms for API calls
- **Logging System**: Comprehensive error tracking and debugging
- **Failover Support**: Multiple API key rotation on failures

### Security Features
- **Environment Configuration**: Secure storage of sensitive data
- **Permission System**: Role-based access control
- **Input Validation**: Secure command parameter handling
- **SSL Configuration**: Secure HTTP connections

## 🔄 Extensibility

### Adding New Commands
The bot architecture supports easy command expansion:

```python
@bot.command(name="new_command")
async def new_command(ctx):
    await ctx.send("New functionality!")
```

### Custom Cogs
Supports Discord.py cog system for modular functionality:

```python
class CustomCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command()
    async def custom_command(self, ctx):
        # Custom functionality
```

### API Integration
Easy integration with external APIs:

```python
async def api_call(endpoint, params):
    async with aiohttp.ClientSession() as session:
        # API call implementation
```

## 🐛 Troubleshooting

### Common Issues
1. **Bot Not Responding**: Check token validity and internet connection
2. **Music Not Playing**: Verify voice channel permissions and yt-dlp installation
3. **Memory Issues**: Monitor SQLite database size and clear old memories
4. **API Rate Limits**: Ensure multiple valid API keys are configured

### Debug Information
- Check `bot.log` for detailed error information
- Use `/ping` to verify bot connectivity
- Monitor console output for real-time status
- Verify environment variable configuration

### Performance Monitoring
- Track response times with built-in latency monitoring
- Monitor memory usage patterns
- Review error frequency in logs
- Check API usage statistics

## 📈 Statistics & Analytics

The bot includes built-in analytics for:
- Command usage frequency
- User interaction patterns
- Error rate monitoring
- Performance metrics
- Memory usage statistics

## 🔮 Future Enhancements

Planned features for future releases:
- Advanced AI conversation modes
- Database migration tools
- Web dashboard for bot management
- Advanced music filtering and effects
- Multi-language support
- Custom AI training capabilities

---

## 👨‍💻 About the Developer

**[tanbaycu](https://tanbaycu.is-a.dev)** - Full-stack developer passionate about AI, automation, and Discord bot development.

### 🔗 Connect & Support
- **Portfolio**: [tanbaycu.is-a.dev](https://tanbaycu.is-a.dev)
- **All Links**: [linktr.ee/tanbaycu](https://linktr.ee/tanbaycu)
- **Issues & Support**: Create an issue on this repository
- **Feature Requests**: Submit via GitHub Issues

### 📞 Contact
For support, questions, or collaboration opportunities, reach out through any of the links above!

---

This Discord bot represents a comprehensive solution for server management, entertainment, and AI-powered interactions, built with modern Python practices and scalable architecture principles.

**Created with ❤️ by [tanbaycu](https://tanbaycu.is-a.dev)**
