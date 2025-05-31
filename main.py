import os
import torrent_file
from pyrogram import Client, filters
from pyrogram.types import Message
import hashlib

# Replace with your own API ID, API Hash, and Bot Token
api_id = "27394279"
api_hash = "90a9aa4c31afa3750da5fd686c410851"
bot_token = "7567477886:AAEMI6V1ImkbEkwUIkMfHNfVrQFFB4GKNtI"

# Initialize the Pyrogram client
app = Client("torrent_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

# Public trackers for the torrent
TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://tracker.leechers-paradise.org:6969/announce",
    "udp://open.stealth.si:80/announce",
]

# Function to create a torrent file and magnet link
def create_torrent(file_path, output_dir):
    try:
        # Create torrent using torrent-file
        torrent = torrent_file.Torrent()
        torrent.add_file(file_path)
        torrent.set_trackers(TRACKERS)
        torrent.set_creator("TorrentBot")
        
        # Generate torrent file
        torrent_file = os.path.join(output_dir, f"{os.path.basename(file_path)}.torrent")
        torrent.generate()
        with open(torrent_file, "wb") as f:
            f.write(torrent.to_bytes())
        
        # Generate magnet link
        with open(file_path, "rb") as f:
            file_hash = hashlib.sha1(f.read()).hexdigest()
        magnet = f"magnet:?xt=urn:btih:{file_hash}&dn={os.path.basename(file_path)}&tr={'&tr='.join(TRACKERS)}"
        
        return torrent_file, magnet
    except Exception as e:
        raise Exception(f"Failed to create torrent: {str(e)}")

# Handle the /start command
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply_text("Send me a file, and I'll create a torrent and magnet link for it!")

# Handle file uploads
@app.on_message(filters.document | filters.photo | filters.video | filters.audio)
async def handle_file(client: Client, message: Message):
    try:
        # Download the file
        file = await message.download()
        await message.reply_text("File received! Creating torrent...")

        # Create a directory for torrents if it doesn't exist
        output_dir = "torrents"
        os.makedirs(output_dir, exist_ok=True)

        # Create torrent and magnet link
        torrent_file, magnet_link = create_torrent(file, output_dir)

        # Send the torrent file
        await message.reply_document(
            document=torrent_file,
            caption=f"Here’s your torrent file!\n\nMagnet Link: `{magnet_link}`"
        )

        # Clean up the downloaded file and torrent file
        os.remove(file)
        os.remove(torrent_file)

    except Exception as e:
        await message.reply_text(f"Error: {str(e)}")

# Run the bot
if __name__ == "__main__":
    print("Bot is running...")
    app.run()
