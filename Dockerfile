FROM python:3.10-slim

# Install system dependencies for libtorrent
RUN apt-get update && \
    apt-get install -y python3-libtorrent && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy your main.py into the container
COPY main.py .

# Install Python dependencies
RUN pip install pyrogram tgcrypto

# Run your bot
CMD gunicorn app:app  & python main.py
