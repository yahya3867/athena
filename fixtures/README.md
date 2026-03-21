# Fixture Guide

Use this folder for repeatable WAV inputs while validating the workflow.

Suggested fixtures:

- `silence.wav`
- `clean_short.wav`
- `latest_query.wav`
- `evergreen_query.wav`
- `long_reply.wav`

Create the silence fixture:

```bash
python3 demo_runner.py make-silence
```

Record the speech fixtures:

```bash
python3 demo_runner.py fixture-record clean_short
python3 demo_runner.py fixture-record latest_query
python3 demo_runner.py fixture-record evergreen_query
python3 demo_runner.py fixture-record long_reply
```

Suggested spoken prompts:

- `clean_short`: "Tell me a short joke."
- `latest_query`: "What are the latest major AI announcements this week?"
- `evergreen_query`: "Explain what recursion is in simple terms."
- `long_reply`: "Give me a three-part summary of how solar eclipses work."
