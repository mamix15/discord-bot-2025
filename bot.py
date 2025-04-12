import discord
from discord import app_commands
from yt_dlp import YoutubeDL
from dotenv import load_dotenv
import os
import re
import asyncio

# Ładujemy token z .env
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
print(f"Token wczytany: {DISCORD_TOKEN}")  # Debugowanie

# Ustawiamy intencje
intents = discord.Intents.default()
intents.message_content = True

# Tworzymy klienta bota
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Opcje dla yt-dlp
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,  # Wyłącza ostrzeżenia
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'extractor_retries': 3,  # Ponawia próby
    'socket_timeout': 20,  # Zwiększa limit czasu
}

# Opcje dla FFmpeg (globalne)
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

# Kolejka piosenek (lista tupli: URL i tytuł)
queue = []

# Zmienna do przechowywania aktualnego źródła i URL
current_source = None
current_url = None

# Funkcja do odtwarzania następnej piosenki
async def play_next(interaction: discord.Interaction):
    global current_source, current_url
    if len(queue) > 0:
        # Pobierz następną piosenkę z kolejki
        next_song = queue.pop(0)  # Usuwa i zwraca pierwszą piosenkę
        current_url = next_song['url']
        current_source = discord.FFmpegPCMAudio(current_url, **FFMPEG_OPTIONS)
        
        # Callback po zakończeniu piosenki
        def after_playing(error):
            if error:
                print(f"Błąd po odtwarzaniu: {error}")
            asyncio.run_coroutine_threadsafe(play_next(interaction), client.loop)
        
        interaction.guild.voice_client.play(current_source, after=after_playing)
        await interaction.followup.send(f"🎵 Odtwarzam: **{next_song['title']}**")
    else:
        current_source = None
        current_url = None

# Gdy bot jest gotowy
@client.event
async def on_ready():
    print(f'Bot zalogowany jako {client.user}')
    try:
        synced = await tree.sync()
        print(f"Zsynchronizowano {len(synced)} komend(y)")
    except Exception as e:
        print(f"Błąd synchronizacji: {e}")

# Komenda /ping
@tree.command(name="ping", description="Sprawdza, czy bot działa")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")

# Komenda /play
@tree.command(name="play", description="Odtwarza piosenkę z YouTube lub dodaje do kolejki")
@app_commands.describe(query="Nazwa piosenki lub link do YouTube")
async def play(interaction: discord.Interaction, query: str):
    global current_source, current_url
    await interaction.response.defer(thinking=True)  # Deferujemy odpowiedź
    if not interaction.user.voice:
        await interaction.followup.send("Musisz być na kanale głosowym!")
        return

    voice_channel = interaction.user.voice.channel
    if not interaction.guild.voice_client:
        await voice_channel.connect()

    try:
        with YoutubeDL(YDL_OPTIONS) as ydl:
            if "youtube.com" not in query and "youtu.be" not in query:
                info = ydl.extract_info(f"ytsearch:{query}", download=False)
                info = info['entries'][0]
            else:
                info = ydl.extract_info(query, download=False)

            url = info['url']
            title = info.get('title', 'Nieznany tytuł')

            # Jeśli nic nie gra, odtwórz od razu
            if not interaction.guild.voice_client.is_playing() and not interaction.guild.voice_client.is_paused():
                current_url = url
                current_source = discord.FFmpegPCMAudio(current_url, **FFMPEG_OPTIONS)
                
                def after_playing(error):
                    if error:
                        print(f"Błąd po odtwarzaniu: {error}")
                    asyncio.run_coroutine_threadsafe(play_next(interaction), client.loop)
                
                interaction.guild.voice_client.play(current_source, after=after_playing)
                await interaction.followup.send(f"🎵 Odtwarzam: **{title}**")
            else:
                # Dodaj do kolejki, jeśli coś gra
                queue.append({'url': url, 'title': title})
                await interaction.followup.send(f"🎵 Dodano do kolejki: **{title}**")

    except Exception as e:
        await interaction.followup.send("Coś poszło nie tak... Sprawdź, czy podałeś dobry link lub nazwę piosenki!")
        print(f"Błąd: {e}")

# Komenda /stop
@tree.command(name="stop", description="Zatrzymuje muzykę i rozłącza bota")
async def stop(interaction: discord.Interaction):
    global current_source, current_url
    if interaction.guild.voice_client:
        interaction.guild.voice_client.stop()
        queue.clear()  # Czyści kolejkę
        current_source = None
        current_url = None
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("Bot się rozłączył.")
    else:
        await interaction.response.send_message("Nie jestem na żadnym kanale głosowym!")

# Komenda /pause
@tree.command(name="pause", description="Wstrzymuje odtwarzanie")
async def pause(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.pause()
        await interaction.response.send_message("⏸️ Piosenka wstrzymana.")
    else:
        await interaction.response.send_message("Nic nie gra lub już wstrzymane!")

# Komenda /resume
@tree.command(name="resume", description="Wznawia wstrzymaną piosenkę")
async def resume(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_paused():
        interaction.guild.voice_client.resume()
        await interaction.response.send_message("▶️ Piosenka wznowiona.")
    else:
        await interaction.response.send_message("Nic nie jest wstrzymane!")

# Komenda /seek
@tree.command(name="seek", description="Przewija piosenkę do podanego czasu")
@app_commands.describe(time="Czas w formacie MM:SS lub w sekundach (np. 90)")
async def seek(interaction: discord.Interaction, time: str):
    global current_source, current_url
    if not interaction.guild.voice_client or not interaction.guild.voice_client.is_playing():
        await interaction.response.send_message("Nic nie gra, nie mogę przewinąć!")
        return

    if not current_url:
        await interaction.response.send_message("Nie mam zapisanego URL do przewinięcia!")
        return

    # Parsowanie czasu (np. "1:30" lub "90" w sekundach)
    time_seconds = 0
    if re.match(r"^\d+:\d+$", time):  # Format MM:SS
        minutes, seconds = map(int, time.split(":"))
        time_seconds = minutes * 60 + seconds
    elif time.isdigit():  # Tylko sekundy
        time_seconds = int(time)
    else:
        await interaction.response.send_message("Podaj czas w formacie `MM:SS` lub w sekundach (np. `90`)!")
        return

    try:
        interaction.guild.voice_client.stop()
        seek_options = FFMPEG_OPTIONS.copy()
        seek_options['before_options'] += f" -ss {time_seconds}"
        current_source = discord.FFmpegPCMAudio(current_url, **seek_options)
        
        def after_playing(error):
            if error:
                print(f"Błąd po odtwarzaniu: {error}")
            asyncio.run_coroutine_threadsafe(play_next(interaction), client.loop)
        
        interaction.guild.voice_client.play(current_source, after=after_playing)
        await interaction.response.send_message(f"⏩ Przewinięto do {time_seconds} sekund.")

    except Exception as e:
        await interaction.response.send_message("Coś poszło nie tak przy przewijaniu!")
        print(f"Błąd seek: {e}")

# Komenda /skip
@tree.command(name="skip", description="Pomija aktualną piosenkę")
async def skip(interaction: discord.Interaction):
    if not interaction.guild.voice_client:
        await interaction.response.send_message("Nie jestem na kanale głosowym!")
        return

    if interaction.guild.voice_client.is_playing() or interaction.guild.voice_client.is_paused():
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ Pominięto piosenkę.")
        if len(queue) > 0:
            await play_next(interaction)
    else:
        await interaction.response.send_message("Nic nie gra, nie ma co pominąć!")

# Komenda /listclear
@tree.command(name="listclear", description="Czyści kolejkę piosenek")
async def listclear(interaction: discord.Interaction):
    global current_source, current_url
    if interaction.guild.voice_client:
        if interaction.guild.voice_client.is_playing() or interaction.guild.voice_client.is_paused():
            interaction.guild.voice_client.stop()
            current_source = None
            current_url = None
        queue.clear()
        await interaction.response.send_message("🧹 Kolejka wyczyszczona!")
    else:
        await interaction.response.send_message("Nie jestem na kanale głosowym, ale i tak wyczyszczę kolejkę!")
        queue.clear()

# Uruchamiamy bota
client.run(DISCORD_TOKEN)