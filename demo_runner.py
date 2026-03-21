import argparse
import re
import sys
from pathlib import Path

import config
from audio_capture import Recorder, check_audio_level, create_silence_fixture
from chat_client import stream_response
from image_client import generate_image
from intent_router import route_user_request
from stt_client import transcribe
from tts_client import TTSPlayer


def _trim_history(history: list[dict]) -> list[dict]:
    max_msgs = config.CONVERSATION_HISTORY_LENGTH * 2
    return history[-max_msgs:]


def cmd_check(_: argparse.Namespace) -> int:
    config.ensure_dirs()
    config.print_config()
    print(f"OUTPUT_DIR             = {config.OUTPUT_DIR}")
    print(f"IMAGE_OUTPUT_DIR       = {config.IMAGE_OUTPUT_DIR}")
    print(f"FIXTURES_DIR           = {config.FIXTURES_DIR}")
    return 0


def cmd_make_silence(args: argparse.Namespace) -> int:
    target = Path(args.output or (config.FIXTURES_DIR / "silence.wav"))
    created = create_silence_fixture(target, duration_sec=args.seconds)
    print(f"[fixture] created {created}")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    recorder = Recorder()
    output = recorder.record_interactive(args.output or config.DEFAULT_WAV_PATH)
    rms = check_audio_level(output)
    print(f"[record] rms={rms:.0f}")
    return 0


def cmd_stt(args: argparse.Namespace) -> int:
    wav = Path(args.wav)
    rms = check_audio_level(wav)
    print(f"[stt] rms={rms:.0f}")
    if rms < config.SILENCE_RMS_THRESHOLD:
        print("[stt] warning: audio looks silent or near-silent")
    transcript = transcribe(wav)
    print(transcript)
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    text = args.text or input("Prompt: ").strip()
    if not text:
        print("[chat] empty prompt")
        return 1
    player = TTSPlayer() if args.speak else None
    _run_user_turn(text, [], player)
    if player:
        player.cancel()
    return 0


def cmd_image(args: argparse.Namespace) -> int:
    prompt = args.prompt or input("Image prompt: ").strip()
    if not prompt:
        print("[image] empty prompt")
        return 1
    try:
        image_path = generate_image(prompt)
    except Exception as exc:
        print(f"[image] error: {exc}")
        return 1
    print(f"[image] saved {image_path}")
    return 0


def cmd_tts(args: argparse.Namespace) -> int:
    text = args.text or input("Text to speak: ").strip()
    if not text:
        print("[tts] empty text")
        return 1
    player = TTSPlayer()
    output = player.speak_once(text)
    print(f"[tts] wrote {output}")
    return 0


def cmd_fixture_record(args: argparse.Namespace) -> int:
    name = args.name.strip().lower().replace(" ", "_")
    target = config.FIXTURES_DIR / f"{name}.wav"
    recorder = Recorder()
    recorder.record_interactive(target)
    print(f"[fixture] recorded {target}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    config.ensure_dirs()
    history: list[dict] = []
    recorder = Recorder()
    player = TTSPlayer() if config.ENABLE_TTS and not args.no_tts else None

    print("Voice prototype ready.")
    print("Commands: Enter=start/stop recording, /wav PATH, /text, /image PROMPT, /quit")

    while True:
        try:
            cmd = input("\nPress Enter to record or type a command: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[demo] exiting")
            break

        if cmd == "/quit":
            break

        if cmd.startswith("/wav "):
            wav_path = Path(cmd[5:].strip()).expanduser()
        elif cmd.startswith("/image "):
            prompt = cmd[7:].strip()
            if not prompt:
                print("[demo] empty image prompt")
                continue
            try:
                image_path = generate_image(prompt)
            except Exception as exc:
                print(f"[image] error: {exc}")
                continue
            print(f"[image] saved {image_path}")
            continue
        elif cmd == "/text":
            transcript = input("Typed transcript: ").strip()
            if not transcript:
                print("[demo] empty transcript")
                continue
            _run_user_turn(transcript, history, player)
            continue
        else:
            wav_path = recorder.record_interactive(config.DEFAULT_WAV_PATH)

        rms = check_audio_level(wav_path)
        print(f"[demo] audio rms={rms:.0f}")
        if rms < config.SILENCE_RMS_THRESHOLD:
            print("[demo] no speech detected; try again")
            continue

        transcript = transcribe(wav_path)
        if not transcript:
            print("[demo] empty transcript")
            continue
        _run_user_turn(transcript, history, player)

    if player:
        player.cancel()
    return 0


def _run_user_turn(transcript: str, history: list[dict], player: TTSPlayer | None) -> None:
    print(f"[user] {transcript}")
    route = route_user_request(transcript)
    image_prompt = route.get("image_prompt") if route.get("mode") == "image" else None
    if image_prompt:
        try:
            image_path = generate_image(image_prompt)
        except Exception as exc:
            print(f"[image] error: {exc}")
            return
        print(f"[assistant] [image mode]")
        print(f"[image] saved {image_path}")
        history.append({"role": "user", "content": transcript})
        history.append({"role": "assistant", "content": f"Displayed an image of {image_prompt}."})
        history[:] = _trim_history(history)
        return

    print("[assistant] ", end="", flush=True)
    full_response = _stream_and_optionally_speak(transcript, history, player)
    history.append({"role": "user", "content": transcript})
    history.append({"role": "assistant", "content": full_response})
    history[:] = _trim_history(history)


def _stream_and_optionally_speak(
    user_text: str,
    history: list[dict],
    player: TTSPlayer | None,
) -> str:
    full_response = ""
    tts_buffer = ""
    for chunk in stream_response(user_text, history=history):
        full_response += chunk
        tts_buffer += chunk
        if player:
            sentence_ends = list(re.finditer(r"[.!?]\s|\n", tts_buffer))
            if len(sentence_ends) >= 2:
                cut = sentence_ends[1].end()
                speak_chunk = tts_buffer[:cut].strip()
                tts_buffer = tts_buffer[cut:]
                if speak_chunk:
                    player.submit(_postprocess_response(speak_chunk))

    final_response = _postprocess_response(full_response)
    print(final_response)

    if player and tts_buffer.strip():
        player.submit(_postprocess_response(tts_buffer.strip()))
    if player and final_response.strip():
        player.flush()
    return final_response


def _postprocess_response(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"\(\[[^\)]*\]\)", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text.endswith("?"):
        text = text[:-1].rstrip() + "."
    return text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Voice workflow prototype runner")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="Print config and validate setup")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("make-silence", help="Create a silence WAV fixture")
    p.add_argument("--output", help="Output WAV path")
    p.add_argument("--seconds", type=float, default=1.0, help="Duration in seconds")
    p.set_defaults(func=cmd_make_silence)

    p = sub.add_parser("record", help="Record a WAV from the microphone")
    p.add_argument("--output", help="Output WAV path")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("stt", help="Transcribe a WAV file")
    p.add_argument("--wav", required=True, help="Path to a WAV file")
    p.set_defaults(func=cmd_stt)

    p = sub.add_parser("chat", help="Send text directly to the chat model")
    p.add_argument("--text", help="Text prompt")
    p.add_argument("--speak", action="store_true", help="Speak the final response")
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("image", help="Generate an image and save it locally")
    p.add_argument("--prompt", help="Image prompt")
    p.set_defaults(func=cmd_image)

    p = sub.add_parser("tts", help="Speak text with OpenAI TTS")
    p.add_argument("--text", help="Text to speak")
    p.set_defaults(func=cmd_tts)

    p = sub.add_parser("fixture-record", help="Record a named WAV fixture")
    p.add_argument("name", help="Fixture name, without extension")
    p.set_defaults(func=cmd_fixture_record)

    p = sub.add_parser("demo", help="Run the full speech -> answer -> speech loop")
    p.add_argument("--no-tts", action="store_true", help="Disable speech playback for this run")
    p.set_defaults(func=cmd_demo)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
