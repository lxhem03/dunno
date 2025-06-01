import os
import asyncio
import time
import math
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
import libtorrent as lt
from script import START_TEXT, HELP_TEXT, ABOUT_TEXT
from config import API_ID, API_HASH, BOT_TOKEN

DOWNLOADS_DIR = "downloads"
TORRENTS_DIR = "torrents"
BATCHES = {}
USER_TASKS = {}

os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(TORRENTS_DIR, exist_ok=True)

app = Client("torrent_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- Utility Functions ---
def human_readable_size(size):
    # Return size as e.g. 10.2 MB
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"

def progress_bar(progress, total=20):
    done = int(progress * total)
    return '▣' * done + '▢' * (total - done)

def time_format(seconds):
    if seconds == 0 or seconds is None or math.isinf(seconds):
        return "∞"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h, {m}m, {s}s"
    elif m:
        return f"{m}m, {s}s"
    else:
        return f"{s}s"

# --- Download Progress ---
async def download_with_progress(message, pyrogram_file, dest, is_batch=False, batch_total=1, batch_index=1, user_id=None):
    start_time = time.time()
    last_update = start_time
    cancel_event = asyncio.Event()
    USER_TASKS[user_id] = {'type': 'download', 'cancel': cancel_event}

    sent = await message.reply_text("🚀 Downloading...  ⚡", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_download")]
    ]))

    total_size = pyrogram_file.file_size or 1
    downloaded = 0
    speed = 0
    eta = 0
    percentage = 0
    progress = 0
    last_downloaded = 0
    last_time = start_time

    async def update_progress(current, total):
        nonlocal downloaded, speed, eta, percentage, progress, last_downloaded, last_time
        now = time.time()
        downloaded = current
        percentage = (current / total_size) * 100
        progress = current / total_size
        speed = (current - last_downloaded) / (now - last_time) if (now - last_time) > 0 else 0
        eta = (total_size - current) / speed if speed > 0 else 0
        last_downloaded = current
        last_time = now

    async def progress_loop():
        while not cancel_event.is_set() and downloaded < total_size:
            bar = progress_bar(progress)
            if is_batch:
                text = (f"🚀 Downloading...  ⚡\n\n"
                        f"{bar}\n\n"
                        f"🔗 Files : {batch_index} | {batch_total}\n"
                        f"️ ⏳️ Done : {percentage:.2f}%\n"
                        f"🚀 Speed : {human_readable_size(speed)}/s\n"
                        f"️ ⏰️ ETA : {time_format(eta)}")
            else:
                text = (f"🚀 Downloading...  ⚡\n\n"
                        f"{bar}\n\n"
                        f"🔗 Size : {human_readable_size(downloaded)} | {human_readable_size(total_size)}\n"
                        f"️ ⏳️ Done : {percentage:.2f}%\n"
                        f"🚀 Speed : {human_readable_size(speed)}/s\n"
                        f"️ ⏰️ ETA : {time_format(eta)}")
            try:
                await sent.edit_text(text, reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Cancel", callback_data="cancel_download")]
                ]))
            except:
                pass
            await asyncio.sleep(10)
        # Final update
        bar = progress_bar(progress)
        if is_batch:
            text = (f"🚀 Downloading...  ⚡\n\n"
                    f"{bar}\n\n"
                    f"🔗 Files : {batch_index} | {batch_total}\n"
                    f"️ ⏳️ Done : {percentage:.2f}%\n"
                    f"🚀 Speed : {human_readable_size(speed)}/s\n"
                    f"️ ⏰️ ETA : {time_format(eta)}")
        else:
            text = (f"🚀 Downloading...  ⚡\n\n"
                    f"{bar}\n\n"
                    f"🔗 Size : {human_readable_size(downloaded)} | {human_readable_size(total_size)}\n"
                    f"️ ⏳️ Done : {percentage:.2f}%\n"
                    f"🚀 Speed : {human_readable_size(speed)}/s\n"
                    f"️ ⏰️ ETA : {time_format(eta)}")
        try:
            await sent.edit_text(text)
        except:
            pass

    progress_task = asyncio.create_task(progress_loop())

    async def progress_wrapper(current, total):
        await update_progress(current, total)
        if cancel_event.is_set():
            raise Exception("Cancelled")

    try:
        await pyrogram_file.download(
            file_name=dest,
            progress=progress_wrapper,
            progress_args=()
        )
        cancel_event.set()
        await asyncio.sleep(1)
        await sent.edit_text("✅ Download complete!")
        del USER_TASKS[user_id]
        return dest
    except Exception as e:
        cancel_event.set()
        await sent.edit_text("❌ Download cancelled or failed.")
        if os.path.exists(dest):
            os.remove(dest)
        del USER_TASKS[user_id]
        return None

# --- Torrent Creation ---
def create_torrent(file_path, torrent_name=None):
    fs = lt.file_storage()
    lt.add_files(fs, file_path)
    t = lt.create_torrent(fs)
    t.add_tracker("udp://tracker.openbittorrent.com:80/announce")
    t.set_creator("Pyrogram Torrent Bot")
    lt.set_piece_hashes(t, os.path.dirname(file_path))
    torrent = t.generate()
    if not torrent_name:
        torrent_name = os.path.basename(file_path)
    torrent_path = os.path.join(TORRENTS_DIR, f"{torrent_name}.torrent")
    with open(torrent_path, "wb") as f:
        f.write(lt.bencode(torrent))
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
    for i in range(300):
        await asyncio.sleep(1)
    print("Seeding finished for:", file_path)

# --- Command Handlers ---
@app.on_message(filters.command("start"))
async def start_cmd(client, message: Message):
    await message.reply_text(START_TEXT, parse_mode=enums.ParseMode.HTML)

@app.on_message(filters.command("help"))
async def help_cmd(client, message: Message):
    await message.reply_text(HELP_TEXT, parse_mode=enums.ParseMode.HTML)

@app.on_message(filters.command("about"))
async def about_cmd(client, message: Message):
    await message.reply_text(ABOUT_TEXT, parse_mode=enums.ParseMode.HTML)

@app.on_message(filters.command("cancel"))
async def cancel_cmd(client, message: Message):
    user_id = message.from_user.id
    if user_id in USER_TASKS:
        USER_TASKS[user_id]['cancel'].set()
        del USER_TASKS[user_id]
        await message.reply_text("❌ Your current process has been cancelled.")
    elif user_id in BATCHES:
        del BATCHES[user_id]
        await message.reply_text("❌ Your current batch has been cancelled.")
    else:
        await message.reply_text("You have no ongoing tasks.")

@app.on_callback_query(filters.regex("^cancel_download$"))
async def cancel_download_cb(client, callback_query):
    user_id = callback_query.from_user.id
    if user_id in USER_TASKS:
        USER_TASKS[user_id]['cancel'].set()
        del USER_TASKS[user_id]
        await callback_query.edit_message_text("❌ Download cancelled by user.")
    elif user_id in BATCHES:
        del BATCHES[user_id]
        await callback_query.edit_message_text("❌ Batch cancelled by user.")
    else:
        await callback_query.answer("No active download to cancel.", show_alert=True)

# --- File Handling ---
@app.on_message((filters.document | filters.video | filters.audio) & ~filters.command(["batch"]))
async def save_file(client, message: Message):
    user_id = message.from_user.id
    if user_id in BATCHES:
        # Handle batch
        batch_list = BATCHES[user_id]
        dest = os.path.join(DOWNLOADS_DIR, message.file_name or f"file_{int(time.time())}")
        downloaded = await download_with_progress(message, message, dest, is_batch=True, batch_total=0, batch_index=len(batch_list)+1, user_id=user_id)
        if downloaded:
            batch_list.append(downloaded)
            await message.reply_text(f"Added to batch: <b>{os.path.basename(downloaded)}</b>", parse_mode=enums.ParseMode.HTML)
    else:
        # Single file
        dest = os.path.join(DOWNLOADS_DIR, message.file_name or f"file_{int(time.time())}")
        downloaded = await download_with_progress(message, message, dest, is_batch=False, user_id=user_id)
        if downloaded:
            await message.reply_text(f"File saved! Now reply to this file with <b>/create</b> to generate torrent/magnet.", parse_mode=enums.ParseMode.HTML)

# --- Create Torrent on Reply ---
@app.on_message(filters.command("create") & filters.reply)
async def create_torrent_cmd(client, message: Message):
    reply = message.reply_to_message
    if not (reply and (reply.document or reply.video or reply.audio)):
        return await message.reply_text("Please reply to a file message with /create.", parse_mode=enums.ParseMode.HTML)
    file_name = reply.document.file_name if reply.document else reply.video.file_name if reply.video else reply.audio.file_name
    file_path = os.path.join(DOWNLOADS_DIR, file_name)
    if not os.path.exists(file_path):
        return await message.reply_text("File not found. Please resend the file.", parse_mode=enums.ParseMode.HTML)
    sent = await message.reply_text("Creating torrent...")
    torrent_path, magnet_uri = create_torrent(file_path, torrent_name=os.path.splitext(file_name)[0])
    await sent.edit(f"<b>Torrent created!</b>\n\n<code>{magnet_uri}</code>\n\nSending .torrent file...", parse_mode=enums.ParseMode.HTML)
    await message.reply_document(torrent_path, caption=".torrent file")
    asyncio.create_task(seed_torrent(torrent_path, file_path))

# --- Batch Handling ---
@app.on_message(filters.command("batch"))
async def batch_start(client, message: Message):
    user_id = message.from_user.id
    BATCHES[user_id] = []
    await message.reply_text("Batch mode started! Send me files one by one. When done, send /done &lt;batch_name&gt; to generate a torrent.", parse_mode=enums.ParseMode.HTML)

@app.on_message(filters.command("done"))
async def batch_done(client, message: Message):
    user_id = message.from_user.id
    if user_id not in BATCHES or not BATCHES[user_id]:
        return await message.reply_text("No files in your batch. Use /batch to start.", parse_mode=enums.ParseMode.HTML)
    try:
        batch_name = message.text.split(None, 1)[1].strip()
    except Exception:
        batch_name = f"batch_{user_id}"
    folder_path = os.path.join(DOWNLOADS_DIR, batch_name)
    os.makedirs(folder_path, exist_ok=True)
    # Move files to the batch folder
    for f in BATCHES[user_id]:
        os.rename(f, os.path.join(folder_path, os.path.basename(f)))
    sent = await message.reply_text(f"Creating batch torrent: <b>{batch_name}</b>...", parse_mode=enums.ParseMode.HTML)
    torrent_path, magnet_uri = create_torrent(folder_path, torrent_name=batch_name)
    await sent.edit(f"<b>Batch torrent created!</b>\n\n<code>{magnet_uri}</code>\n\nSending .torrent file...", parse_mode=enums.ParseMode.HTML)
    await message.reply_document(torrent_path, caption="Batch .torrent file")
    asyncio.create_task(seed_torrent(torrent_path, folder_path))
    del BATCHES[user_id]

if __name__ == "__main__":
    print("Bot is running...")
    app.run()
