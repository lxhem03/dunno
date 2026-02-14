import os
import asyncio
import time
import math
import logging
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
import libtorrent as lt
import mimetypes
from script import START_TEXT, HELP_TEXT, ABOUT_TEXT
from config import API_ID, API_HASH, BOT_TOKEN

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('torrent_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

DOWNLOADS_DIR = "downloads"
TORRENTS_DIR = "torrents"
BATCHES = {}  # Stores user_id: [Message objects]
USER_TASKS = {}  # Stores user_id: {'type': 'download' or 'upload', 'cancel': Event}
trackers = [
    # Nyaa related public tracker
    "http://nyaa.tracker.wf:7777/announce",

    # Most reliable public trackers
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.cyberia.is:6969/announce",
    "udp://tracker.moeking.me:6969/announce",
    "udp://tracker.bittor.pw:1337/announce",
    "udp://tracker.uw0.xyz:6969/announce",

    # HTTP trackers (fallback)
    "http://tracker.opentrackr.org:1337/announce",
    "http://tracker.openbittorrent.com:80/announce"
]



os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(TORRENTS_DIR, exist_ok=True)

app = Client("torrent_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- Utility Functions ---
def human_readable_size(size):
    try:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"
    except Exception as e:
        logger.error(f"Error in human_readable_size: {e}")
        return "Unknown size"

def progress_bar(progress, total=20):
    try:
        done = int(progress * total)
        return '▣' * done + '▢' * (total - done)
    except Exception as e:
        logger.error(f"Error in progress_bar: {e}")
        return ""

def time_format(seconds):
    try:
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
    except Exception as e:
        logger.error(f"Error in time_format: {e}")
        return "Unknown time"

async def delete_file_later(file_path, delay=300):
    """Delete a file after a specified delay (default 5 minutes)."""
    try:
        await asyncio.sleep(delay)
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Deleted file after {delay} seconds: {file_path}")
    except Exception as e:
        logger.error(f"Error deleting file {file_path}: {e}")

def get_file_duration(file_path):
    """Get duration for video files (dummy implementation; replace with ffmpeg or similar)."""
    try:
        # Placeholder: Use ffmpeg-python or similar to get actual duration
        return 0  # Return 0 for non-video files or if duration cannot be determined
    except Exception as e:
        logger.error(f"Error getting duration for {file_path}: {e}")
        return 0

# --- Download Progress ---
async def download_with_progress(message, pyrogram_file, dest, is_batch=False, batch_total=1, batch_index=1, user_id=None):
    logger.info(f"Starting download for user {user_id}, file: {dest}, batch: {is_batch}")
    start_time = time.time()
    cancel_event = asyncio.Event()
    USER_TASKS[user_id] = {'type': 'download', 'cancel': cancel_event}

    try:
        sent = await message.reply_text("🚀 Downloading...  ⚡", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_download")]
        ]))
    except Exception as e:
        logger.error(f"Error sending download message for user {user_id}: {e}")
        return None

    # Get file size based on media type
    total_size = 1  # Default to avoid division by zero
    try:
        if pyrogram_file.document:
            total_size = pyrogram_file.document.file_size or 1
        elif pyrogram_file.video:
            total_size = pyrogram_file.video.file_size or 1
        elif pyrogram_file.audio:
            total_size = pyrogram_file.audio.file_size or 1
        logger.info(f"File size for {dest}: {total_size} bytes")
    except Exception as e:
        logger.error(f"Error getting file size for {dest}: {e}")

    downloaded = 0
    speed = 0
    eta = 0
    percentage = 0
    progress = 0
    last_downloaded = 0
    last_time = start_time

    async def update_progress(current, total):
        nonlocal downloaded, speed, eta, percentage, progress, last_downloaded, last_time
        try:
            now = time.time()
            downloaded = current
            percentage = (current / total_size) * 100
            progress = current / total_size
            speed = (current - last_downloaded) / (now - last_time) if (now - last_time) > 0 else 0
            eta = (total_size - current) / speed if speed > 0 else 0
            last_downloaded = current
            last_time = now
        except Exception as e:
            logger.error(f"Error in update_progress for {dest}: {e}")

    async def progress_loop():
        try:
            while not cancel_event.is_set() and downloaded < total_size:
                bar = progress_bar(progress)
                if is_batch:
                    text = (f"🚀 Downloading...  ⚡\n\n"
                            f"{bar}\n\n"
                            f"🔗 Files: {batch_index}/{batch_total}\n"
                            f"⏳ Done: {percentage:.2f}%\n"
                            f"🚀 Speed: {human_readable_size(speed)}/s\n"
                            f"⏰ ETA: {time_format(eta)}")
                else:
                    text = (f"🚀 Downloading...  ⚡\n\n"
                            f"{bar}\n\n"
                            f"🔗 Size: {human_readable_size(downloaded)}/{human_readable_size(total_size)}\n"
                            f"⏳ Done: {percentage:.2f}%\n"
                            f"🚀 Speed: {human_readable_size(speed)}/s\n"
                            f"⏰ ETA: {time_format(eta)}")
                try:
                    await sent.edit_text(text, reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_download")]
                    ]))
                except Exception:
                    pass
                await asyncio.sleep(5)  # Update every 5 seconds
        except Exception as e:
            logger.error(f"Error in progress_loop for {dest}: {e}")

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
        await progress_task
        try:
            await sent.edit_text("✅ Download complete!")
            await asyncio.sleep(2)  # Show completion for 2 seconds
            await sent.delete()  # Delete progress bar
        except Exception as e:
            logger.error(f"Error updating/deleting progress message for {dest}: {e}")
        logger.info(f"Download completed for {dest}")
        del USER_TASKS[user_id]
        asyncio.create_task(delete_file_later(dest, delay=300))
        return dest
    except Exception as e:
        cancel_event.set()
        await progress_task
        try:
            await sent.edit_text("❌ Download cancelled or failed.")
            await asyncio.sleep(2)
            await sent.delete()
        except Exception:
            pass
        if os.path.exists(dest):
            os.remove(dest)
        logger.error(f"Download failed for {dest}: {e}")
        del USER_TASKS[user_id]
        return None

# --- Upload Progress ---
async def upload_with_progress(message, file_path, user_id, is_video=False, duration=0):
    logger.info(f"Starting upload for user {user_id}, file: {file_path}")
    start_time = time.time()
    cancel_event = asyncio.Event()
    USER_TASKS[user_id] = {'type': 'upload', 'cancel': cancel_event}

    try:
        sent = await message.reply_text("📤 Uploading...  ⚡", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_upload")]
        ]))
    except Exception as e:
        logger.error(f"Error sending upload message for user {user_id}: {e}")
        return None

    total_size = os.path.getsize(file_path) if os.path.exists(file_path) else 1
    uploaded = 0
    speed = 0
    eta = 0
    percentage = 0
    progress = 0
    last_uploaded = 0
    last_time = start_time

    async def update_progress(current, total):
        nonlocal uploaded, speed, eta, percentage, progress, last_uploaded, last_time
        try:
            now = time.time()
            uploaded = current
            percentage = (current / total_size) * 100
            progress = current / total_size
            speed = (current - last_uploaded) / (now - last_time) if (now - last_time) > 0 else 0
            eta = (total_size - current) / speed if speed > 0 else 0
            last_uploaded = current
            last_time = now
        except Exception as e:
            logger.error(f"Error in upload update_progress for {file_path}: {e}")

    async def progress_loop():
        try:
            while not cancel_event.is_set() and uploaded < total_size:
                bar = progress_bar(progress)
                text = (f"📤 Uploading...  ⚡\n\n"
                        f"{bar}\n\n"
                        f"🔗 Size: {human_readable_size(uploaded)}/{human_readable_size(total_size)}\n"
                        f"⏳ Done: {percentage:.2f}%\n"
                        f"🚀 Speed: {human_readable_size(speed)}/s\n"
                        f"⏰ ETA: {time_format(eta)}")
                try:
                    await sent.edit_text(text, reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_upload")]
                    ]))
                except Exception:
                    pass
                await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Error in upload progress_loop for {file_path}: {e}")

    progress_task = asyncio.create_task(progress_loop())

    async def progress_wrapper(current, total):
        await update_progress(current, total)
        if cancel_event.is_set():
            raise Exception("Cancelled")

    try:
        if is_video:
            await message.reply_video(
                video=file_path,
                duration=duration,
                progress=progress_wrapper,
                progress_args=()
            )
        else:
            await message.reply_document(
                document=file_path,
                progress=progress_wrapper,
                progress_args=()
            )
        cancel_event.set()
        await progress_task
        try:
            await sent.edit_text("✅ Upload complete!")
            await asyncio.sleep(2)
            await sent.delete()
        except Exception as e:
            logger.error(f"Error updating/deleting upload progress message for {file_path}: {e}")
        logger.info(f"Upload completed for {file_path}")
        del USER_TASKS[user_id]
        return True
    except Exception as e:
        cancel_event.set()
        await progress_task
        try:
            await sent.edit_text("❌ Upload cancelled or failed.")
            await asyncio.sleep(2)
            await sent.delete()
        except Exception:
            pass
        logger.error(f"Upload failed for {file_path}: {e}")
        del USER_TASKS[user_id]
        return False

# --- Torrent Creation ---
def create_torrent(file_path, torrent_name=None):
    logger.info(f"Creating torrent for {file_path}")
    try:
        fs = lt.file_storage()
        lt.add_files(fs, file_path)
        t = lt.create_torrent(fs)
        for tkr in trackers:
            t.add_tracker(tkr)
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
        logger.info(f"Torrent created: {torrent_path}, Magnet: {magnet_uri}")
        asyncio.create_task(delete_file_later(torrent_path, delay=300))
        return torrent_path, magnet_uri
    except Exception as e:
        logger.error(f"Error creating torrent for {file_path}: {e}")
        return None, None

async def seed_torrent(torrent_path, file_path):
    logger.info(f"Starting seeding for {torrent_path}")

    try:
        ses = lt.session()
        ses.listen_on(6881, 6891)

        # Enable peer discovery (VERY IMPORTANT)
        ses.start_dht()
        ses.start_lsd()
        ses.start_upnp()
        ses.start_natpmp()

        info = lt.torrent_info(torrent_path)
        handle = ses.add_torrent({
            'ti': info,
            'save_path': os.path.dirname(file_path)
        })

        logger.info(f"Seeding started for: {file_path}")

        # Wait until seeding starts properly
        for _ in range(300):  # 5 minutes
            s = handle.status()

            logger.info(
                f"Progress: {s.progress * 100:.2f}% | "
                f"Peers: {s.num_peers} | "
                f"Upload: {human_readable_size(s.total_upload)}"
            )

            await asyncio.sleep(1)

        logger.info(f"Seeding finished after 5 minutes")

    except Exception as e:
        logger.error(f"Error seeding {torrent_path}: {e}")
        
# --- Torrent Download (for /seedr) ---
async def download_torrent(message, torrent_input, user_id):
    logger.info(f"Starting torrent download for user {user_id}")
    try:
        ses = lt.session()
        ses.listen_on(6881, 6891)
        params = {
            "save_path": DOWNLOADS_DIR,
            "storage_mode": lt.storage_mode_t.storage_mode_sparse,
        }

        if torrent_input.startswith("magnet:"):
            h = lt.add_magnet_uri(ses, torrent_input, params)
        else:
            info = lt.torrent_info(torrent_input)
            h = ses.add_torrent({'ti': info, 'save_path': params["save_path"]})

        sent = await message.reply_text("🚀 Downloading torrent...  ⚡", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_download")]
        ]))
        USER_TASKS[user_id] = {'type': 'download', 'cancel': asyncio.Event()}

        total_size = h.status().total_wanted
        downloaded = 0
        start_time = time.time()
        last_downloaded = 0
        last_time = start_time

        while not h.is_seed() and not USER_TASKS[user_id]['cancel'].is_set():
            s = h.status()
            downloaded = s.total_wanted_done
            progress = downloaded / total_size if total_size > 0 else 0
            percentage = progress * 100
            speed = (downloaded - last_downloaded) / (time.time() - last_time) if (time.time() - last_time) > 0 else 0
            eta = (total_size - downloaded) / speed if speed > 0 else 0
            bar = progress_bar(progress)

            text = (f"🚀 Downloading torrent...  ⚡\n\n"
                    f"{bar}\n\n"
                    f"🔗 Size: {human_readable_size(downloaded)}/{human_readable_size(total_size)}\n"
                    f"⏳ Done: {percentage:.2f}%\n"
                    f"🚀 Speed: {human_readable_size(speed)}/s\n"
                    f"⏰ ETA: {time_format(eta)}")
            try:
                await sent.edit_text(text, reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Cancel", callback_data="cancel_download")]
                ]))
            except Exception:
                pass
            last_downloaded = downloaded
            last_time = time.time()
            await asyncio.sleep(5)

        if USER_TASKS[user_id]['cancel'].is_set():
            await sent.edit_text("❌ Torrent download cancelled.")
            await asyncio.sleep(2)
            await sent.delete()
            logger.info(f"Torrent download cancelled for user {user_id}")
            del USER_TASKS[user_id]
            return None

        await sent.edit_text("✅ Torrent download complete!")
        await asyncio.sleep(2)
        await sent.delete()
        logger.info(f"Torrent download completed for user {user_id}")
        del USER_TASKS[user_id]

        # Return downloaded file(s) or directory
        save_path = os.path.join(DOWNLOADS_DIR, h.name())
        return save_path if os.path.exists(save_path) else None
    except Exception as e:
        logger.error(f"Error downloading torrent for user {user_id}: {e}")
        try:
            await sent.edit_text("❌ Torrent download failed.")
            await asyncio.sleep(2)
            await sent.delete()
        except Exception:
            pass
        if user_id in USER_TASKS:
            del USER_TASKS[user_id]
        return None

# --- Command Handlers ---
@app.on_message(filters.command("start"))
async def start_cmd(client, message: Message):
    logger.info(f"Start command received from user {message.from_user.id}")
    try:
        await message.reply_text(START_TEXT, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"Error in start_cmd for user {message.from_user.id}: {e}")

@app.on_message(filters.command("help"))
async def help_cmd(client, message: Message):
    logger.info(f"Help command received from user {message.from_user.id}")
    try:
        await message.reply_text(HELP_TEXT, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"Error in help_cmd for user {message.from_user.id}: {e}")

@app.on_message(filters.command("about"))
async def about_cmd(client, message: Message):
    logger.info(f"About command received from user {message.from_user.id}")
    try:
        await message.reply_text(ABOUT_TEXT, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"Error in about_cmd for user {message.from_user.id}: {e}")

@app.on_message(filters.command("cancel"))
async def cancel_cmd(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Cancel command received from user {user_id}")
    try:
        if user_id in USER_TASKS:
            USER_TASKS[user_id]['cancel'].set()
            del USER_TASKS[user_id]
            await message.reply_text("❌ Your current process has been cancelled.")
        elif user_id in BATCHES:
            del BATCHES[user_id]
            await message.reply_text("❌ Your current batch queue has been cancelled.")
        else:
            await message.reply_text("You have no ongoing tasks.")
    except Exception as e:
        logger.error(f"Error in cancel_cmd for user {user_id}: {e}")

@app.on_callback_query(filters.regex("^(cancel_download|cancel_upload)$"))
async def cancel_callback(client, callback_query):
    user_id = callback_query.from_user.id
    logger.info(f"Cancel callback ({callback_query.data}) received from user {user_id}")
    try:
        if user_id in USER_TASKS:
            USER_TASKS[user_id]['cancel'].set()
            del USER_TASKS[user_id]
            await callback_query.edit_message_text(f"❌ {USER_TASKS[user_id]['type'].capitalize()} cancelled by user.")
            await asyncio.sleep(2)
            await callback_query.message.delete()
        elif user_id in BATCHES:
            del BATCHES[user_id]
            await callback_query.edit_message_text("❌ Batch queue cancelled by user.")
            await asyncio.sleep(2)
            await callback_query.message.delete()
        else:
            await callback_query.answer("No active download/upload or batch to cancel.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in cancel_callback for user {user_id}: {e}")

# --- File Handling ---
@app.on_message(filters.document | filters.video | filters.audio)
async def save_file(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"File received from user {user_id}")
    if user_id not in BATCHES:
        try:
            await message.reply_text("Please start batch mode with /batch before sending files, or reply to this file with /create to generate a torrent.", parse_mode=enums.ParseMode.HTML)
            logger.info(f"User {user_id} not in batch mode, prompted to use /batch or /create")
            return
        except Exception as e:
            logger.error(f"Error replying to user {user_id} in save_file: {e}")
            return

    try:
        batch_list = BATCHES[user_id]
        batch_list.append(message)
        queue_position = len(batch_list)
        await message.reply_text(f"File added to queue {queue_position} of batch", parse_mode=enums.ParseMode.HTML)
        logger.info(f"File queued for user {user_id}, position: {queue_position}")
    except Exception as e:
        logger.error(f"Error queuing file for user {user_id}: {e}")

# --- Create Torrent on Reply ---
@app.on_message(filters.command("create") & filters.reply)
async def create_torrent_cmd(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Create command received from user {user_id}")
    reply = message.reply_to_message
    if not (reply and (reply.document or reply.video or reply.audio)):
        try:
            await message.reply_text("Please reply to a file message with /create.", parse_mode=enums.ParseMode.HTML)
            logger.info(f"User {user_id} did not reply to a valid file with /create")
            return
        except Exception as e:
            logger.error(f"Error replying to user {user_id} in create_torrent_cmd: {e}")
            return

    try:
        file_name = reply.document.file_name if reply.document else reply.video.file_name if reply.video else reply.audio.file_name
        file_path = os.path.join(DOWNLOADS_DIR, file_name or f"file_{user_id}_{int(time.time())}")
        logger.info(f"Checking file for user {user_id}: {file_path}")

        if not os.path.exists(file_path):
            sent = await message.reply_text("Downloading file to create torrent...")
            logger.info(f"Downloading file for user {user_id}: {file_path}")
            downloaded = await download_with_progress(reply, reply, file_path, is_batch=False, user_id=user_id)
            if not downloaded:
                await sent.edit_text("Failed to download the file.")
                await asyncio.sleep(2)
                await sent.delete()
                logger.warning(f"Failed to download file {file_path} for user {user_id}")
                return
        else:
            sent = await message.reply_text("Creating torrent...")
            logger.info(f"File {file_path} already exists for user {user_id}, creating torrent")

        torrent_path, magnet_uri = create_torrent(file_path, torrent_name=os.path.splitext(file_name)[0])
        if not torrent_path or not magnet_uri:
            await sent.edit_text("Failed to create torrent.")
            await asyncio.sleep(2)
            await sent.delete()
            logger.error(f"Failed to create torrent for {file_path}")
            return
        await sent.edit(f"<b>Torrent created!</b>\n\n<code>{magnet_uri}</code>\n\nSending .torrent file...", parse_mode=enums.ParseMode.HTML)
        await message.reply_document(torrent_path, caption=".torrent file")
        await asyncio.sleep(2)
        await sent.delete()
        logger.info(f"Torrent sent to user {user_id}: {torrent_path}")
        asyncio.create_task(seed_torrent(torrent_path, file_path))
    except Exception as e:
        logger.error(f"Error in create_torrent_cmd for user {user_id}: {e}")
        try:
            await message.reply_text("An error occurred while creating the torrent.")
        except Exception as e2:
            logger.error(f"Error replying to user {user_id} in create_torrent_cmd: {e2}")

# --- Batch Handling ---
@app.on_message(filters.command("batch"))
async def batch_start(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Batch command received from user {user_id}")
    try:
        if user_id in BATCHES:
            await message.reply_text("You are already in batch mode. Send files or use /done <batch_name> to finish.", parse_mode=enums.ParseMode.HTML)
            logger.info(f"User {user_id} already in batch mode")
            return
        BATCHES[user_id] = []
        await message.reply_text("Batch mode started! Send me files one by one. When done, send /done <batch_name> to generate a torrent.", parse_mode=enums.ParseMode.HTML)
        logger.info(f"Batch mode started for user {user_id}")
    except Exception as e:
        logger.error(f"Error in batch_start for user {user_id}: {e}")

@app.on_message(filters.command("done"))
async def batch_done(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Done command received from user {user_id}")
    if user_id not in BATCHES or not BATCHES[user_id]:
        try:
            await message.reply_text("No files in your batch. Use /batch to start.", parse_mode=enums.ParseMode.HTML)
            logger.info(f"No batch files for user {user_id}")
            return
        except Exception as e:
            logger.error(f"Error replying to user {user_id} in batch_done: {e}")
            return

    try:
        try:
            batch_name = message.text.split(None, 1)[1].strip()
        except IndexError:
            batch_name = f"batch_{user_id}_{int(time.time())}"
        logger.info(f"Creating batch torrent for user {user_id}: {batch_name}")

        folder_path = os.path.join(DOWNLOADS_DIR, batch_name)
        os.makedirs(folder_path, exist_ok=True)

        batch_list = BATCHES[user_id]
        total_files = len(batch_list)
        completed_files = 0
        downloaded_paths = []

        sent = await message.reply_text(f"Downloading {total_files} files for batch: <b>{batch_name}</b>...", parse_mode=enums.ParseMode.HTML)
        for index, file_message in enumerate(batch_list, 1):
            if USER_TASKS.get(user_id, {}).get('cancel', asyncio.Event()).is_set():
                await sent.edit_text("❌ Batch download cancelled.")
                await asyncio.sleep(2)
                await sent.delete()
                logger.info(f"Batch download cancelled for user {user_id}")
                break

            file_name = file_message.document.file_name if file_message.document else file_message.video.file_name if file_message.video else file_message.audio.file_name
            dest = os.path.join(folder_path, file_name or f"file_{user_id}_{int(time.time())}_{index}")
            logger.info(f"Downloading batch file {index}/{total_files} for user {user_id}: {dest}")
            downloaded = await download_with_progress(
                message,
                file_message,
                dest,
                is_batch=True,
                batch_total=total_files,
                batch_index=index,
                user_id=user_id
            )
            if downloaded:
                completed_files += 1
                downloaded_paths.append(downloaded)
                try:
                    await sent.edit_text(
                        f"Downloading files for batch: <b>{batch_name}</b>\n\n"
                        f"🔗 Files: {completed_files}/{total_files}",
                        parse_mode=enums.ParseMode.HTML
                    )
                except Exception:
                    pass
            else:
                logger.warning(f"Failed to download batch file {dest} for user {user_id}")

        if completed_files == 0:
            await sent.edit_text("❌ No files were downloaded for the batch.")
            await asyncio.sleep(2)
            await sent.delete()
            logger.warning(f"No files downloaded for batch {batch_name} for user {user_id}")
            del BATCHES[user_id]
            return

        await sent.edit_text(f"Creating batch torrent: <b>{batch_name}</b>...", parse_mode=enums.ParseMode.HTML)
        torrent_path, magnet_uri = create_torrent(folder_path, torrent_name=batch_name)
        if not torrent_path or not magnet_uri:
            await sent.edit_text("Failed to create batch torrent.")
            await asyncio.sleep(2)
            await sent.delete()
            logger.error(f"Failed to create batch torrent for {folder_path}")
            del BATCHES[user_id]
            return

        await sent.edit(f"<b>Batch torrent created!</b>\n\n<code>{magnet_uri}</code>\n\nSending .torrent file...", parse_mode=enums.ParseMode.HTML)
        await message.reply_document(torrent_path, caption="Batch .torrent file")
        await asyncio.sleep(2)
        await sent.delete()
        logger.info(f"Batch torrent sent to user {user_id}: {torrent_path}")
        asyncio.create_task(seed_torrent(torrent_path, folder_path))
        del BATCHES[user_id]
        logger.info(f"Batch completed and cleared for user {user_id}")
    except Exception as e:
        logger.error(f"Error in batch_done for user {user_id}: {e}")
        try:
            await message.reply_text("An error occurred while creating the batch torrent.")
            await asyncio.sleep(2)
            await sent.delete()
        except Exception as e2:
            logger.error(f"Error replying to user {user_id} in batch_done: {e2}")

# --- Seedr Command ---
@app.on_message(filters.command("seedr") & filters.reply)
async def seedr_cmd(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Seedr command received from user {user_id}")
    reply = message.reply_to_message
    torrent_input = None

    try:
        if reply.text and reply.text.startswith("magnet:"):
            torrent_input = reply.text
            logger.info(f"Magnet link received for user {user_id}: {torrent_input[:50]}...")
        elif reply.document and reply.document.file_name.endswith(".torrent"):
            torrent_path = os.path.join(TORRENTS_DIR, reply.document.file_name)
            await reply.download(file_name=torrent_path)
            torrent_input = torrent_path
            logger.info(f"Torrent file downloaded for user {user_id}: {torrent_path}")
        else:
            await message.reply_text("Please reply to a magnet link or a .torrent file with /seedr.", parse_mode=enums.ParseMode.HTML)
            logger.info(f"User {user_id} did not reply to a valid magnet link or torrent file")
            return

        save_path = await download_torrent(message, torrent_input, user_id)
        if not save_path:
            logger.warning(f"Torrent download failed for user {user_id}")
            return

        # Handle downloaded files
        if os.path.isfile(save_path):
            files = [(save_path, os.path.basename(save_path))]
        else:
            files = [(os.path.join(save_path, f), f) for f in os.listdir(save_path) if os.path.isfile(os.path.join(save_path, f))]

        sent = await message.reply_text(f"Uploading {len(files)} file(s)...", parse_mode=enums.ParseMode.HTML)
        for file_path, file_name in files:
            is_video = mimetypes.guess_type(file_path)[0].startswith('video') if mimetypes.guess_type(file_path)[0] else False
            duration = get_file_duration(file_path) if is_video else 0
            logger.info(f"Uploading file for user {user_id}: {file_path}, is_video: {is_video}, duration: {duration}")
            success = await upload_with_progress(message, file_path, user_id, is_video=is_video, duration=duration)
            if not success:
                logger.warning(f"Failed to upload file {file_path} for user {user_id}")
                continue
            asyncio.create_task(delete_file_later(file_path, delay=300))

        await sent.edit_text(f"✅ Uploaded {len(files)} file(s)!")
        await asyncio.sleep(2)
        await sent.delete()
        logger.info(f"Completed uploading {len(files)} file(s) for user {user_id}")
    except Exception as e:
        logger.error(f"Error in seedr_cmd for user {user_id}: {e}")
        try:
            await message.reply_text("An error occurred while processing the torrent.")
        except Exception as e2:
            logger.error(f"Error replying to user {user_id} in seedr_cmd: {e2}")

if __name__ == "__main__":
    logger.info("Starting torrent bot...")
    app.run()
