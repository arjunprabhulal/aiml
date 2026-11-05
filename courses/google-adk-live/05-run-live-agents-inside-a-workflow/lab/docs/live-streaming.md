# Live streaming in the docs assistant

ADK is the Agent Development Kit, Google's open-source framework for building agents.
The docs assistant answers spoken questions through ADK's bidirectional streaming:
`Runner.run_live()` holds one open connection to the Gemini Live API while the user talks.

- Microphone audio goes in as 16-bit PCM, 16 kHz, mono (`audio/pcm;rate=16000`).
- The model answers with audio, 16-bit PCM at 24 kHz, and a text transcription.
- A Live API connection closes after about 10 minutes; enable session resumption to continue.
- An audio-only Live session is limited to 15 minutes, an audio and video session to 2 minutes.
