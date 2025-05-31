import asyncio
import os
import libtorrent as lt
from pyrogram import Client, filters

API_ID = 27394279   # <-- your API ID here
API_HASH = "90a9aa4c31afa3750da5fd686c410851"
BOT_TOKEN = "your_bot_token_here"

DOWNLOADS_DIR = "downloads"
TORRENTS_DIR = "torrents"

os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(TORRENTS_DIR, exist_ok=True)

app = Client("torrent_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def create_torrent(file_path):
    fs = lt.file_storage()
    lt.add_files(fs, file_path)
    t = lt.create_torrent(fs)
    t.add_tracker("udp://tracker.openbittorrent.com:80/announce")
    t.set_creator("Pyrogram Torrent Bot")
    lt.set_piece_hashes(t, os.path.dirname(file_path))
    torrent = t.generate()
    torrent_path = os.path.join(TORRENTS_DIR, os.path.basename(file_path) + ".torrent")
    with open(torrent_path, "wb") as f:
        f.write(lt.bencode(torrent))
    # Generate magnet URI
    info = lt.torrent_info(torrent_path)
    magnet_uri = lt.make_magnet_uri(info)
    return torrent_path, magnet_uri

async def seed_torrent(torrent_path, file_path):
    ses = lt.session()
    ses.listen_on(6881, 6891)
    params = {
        "save_path": os.path.dirname(file_path),
        "storage_mode": lt.storage_mode_t.storage_mode_sparse,
    }
    info = lt.torrent_info(torrent_path)
    h = ses.add_torrent({'ti': info, 'save_path': params["save_path"]})
    print("Seeding started for:", file_path)
    # To keep seeding, you may want to run this in a background process/thread
    # For now, just seed for 5 minutes
    for i in range(300):
        await asyncio.sleep(1)
    print("Seeding finished for:", file_path)

@app.on_message(filters.document | filters.video | filters.audio)
async def handle_file(client, message):
    # Download file
    sent = await message.reply_text("Downloading your file...")
    downloaded = await message.download(DOWNLOADS_DIR)
    await sent.edit("Creating torrent file...")
    torrent_path, magnet_uri = create_torrent(downloaded)
    await sent.edit("Seeding the torrent (for 5 minutes)...")
    asyncio.create_task(seed_torrent(torrent_path, downloaded))
    await sent.edit(
        f"✅ Torrent created!\n\n"
        f"**Magnet link:**\n`{magnet_uri}`\n\n"
        f"**Torrent file:**",
        disable_web_page_preview=True,
    )
    await message.reply_document(torrent_path, caption="Here is your .torrent file!")

if __name__ == "__main__":
    print("Bot is running...")
    app.run()
