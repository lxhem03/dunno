FROM python:3.10-slim

WORKDIR /app

COPY main.py .

# Install Python dependencies, including libtorrent via pip
RUN pip install pyrogram tgcrypto "libtorrent>=2.0.7"

CMD ["python", "main.py"]
