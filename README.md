# Athena

Athena Whisplay voice assistant. This is now the Pi-target codebase: clone it onto the Raspberry Pi, add your `.env`, and run `main.py` or the included service.

Core device flow:

1. Press button to record audio
2. Transcribe with `gpt-4o-mini-transcribe`
3. Route the request with `gpt-5-mini`
4. Stream a reply from `gpt-5.4` when it is a chat turn
5. Let the model use OpenAI web search when needed
6. Speak the reply with `gpt-4o-mini-tts`
7. Show status and response text on the Whisplay display

Image mode:

- Explicit image requests such as “show me a picture of …” or “draw …” use `gpt-image-1.5`
- Athena shows the image full-screen and does not speak for that turn
- On the Pi, the next button press clears the image and returns to the normal voice flow

## Hardware

- Raspberry Pi Zero 2 W / WH
- PiSugar Whisplay HAT
- PiSugar battery board

## Pi Setup

### Prerequisites

- Raspberry Pi OS
- Python 3.11+
- Whisplay driver installed at `/home/pi/Whisplay/Driver/`
- `alsa-utils` for `arecord` / `aplay`

### Install dependencies

On the Pi:

```bash
sudo apt install python3-numpy python3-pil alsa-utils ffmpeg
```

Then in the repo:

```bash
cp .env.example .env
./bootstrap.sh
```

Then edit `.env`:

```bash
OPENAI_API_KEY="sk-..."
```

Optional image settings:

```bash
OPENAI_INTENT_MODEL="gpt-5-mini"
OPENAI_IMAGE_MODEL="gpt-image-1.5"
OPENAI_IMAGE_SIZE="1024x1024"
OPENAI_IMAGE_QUALITY="medium"
```

### Run on the Pi

```bash
source .venv/bin/activate
python3 main.py
```

### Run on boot with systemd

This repo includes `athena-whisplay.service`.

If the repo lives at `/home/pi/athena-whisplay`, install it with:

```bash
sudo cp athena-whisplay.service /etc/systemd/system/athena-whisplay.service
sudo systemctl daemon-reload
sudo systemctl enable athena-whisplay
sudo systemctl restart athena-whisplay
sudo journalctl -u athena-whisplay -f
```

Or use `sync.sh` from your laptop to deploy and restart it on the Pi.

## Laptop Test Mode

The CLI prototype is still available for off-device testing with `demo_runner.py`.

Useful laptop commands:

```bash
python3 demo_runner.py check
python3 demo_runner.py record
python3 demo_runner.py stt --wav output/utterance.wav
python3 demo_runner.py chat --text "What is your name?"
python3 demo_runner.py image --prompt "a calm owl in ancient Athens"
python3 demo_runner.py tts --text "Hello from the prototype."
python3 demo_runner.py demo
```

Image-request examples for `demo`:

```bash
Athena, show me a picture of ancient Athens at sunset
Athena, draw a calm owl on a marble column
```

## Notes

- `main.py` is the real Pi entrypoint.
- `demo_runner.py` is only for laptop/off-device testing.
- Conversation history is kept in memory and trimmed to the last few exchanges.
- Web search is enabled, but the model is instructed to use it only for current or time-sensitive questions.
- Image-vs-chat routing is handled by `gpt-5-mini` with regex fallback if the router call fails.
- Image generation uses OpenAI image generation separately from GPT-5.4 chat.
- In laptop CLI mode, generated images are saved locally and the file path is printed.
- The Whisplay driver is still required separately.
