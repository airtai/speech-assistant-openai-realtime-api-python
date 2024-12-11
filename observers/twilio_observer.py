import base64
import json

from fastapi import WebSocketDisconnect

from .openai_observer import RealtimeObserver

SYSTEM_MESSAGE = (
    "You are a helpful and bubbly AI assistant who loves to chat about weather"
    "when the user queries about the waether at some location, call the get_weather tool"
    "to get the current weather at that location."
)
VOICE = 'alloy'
LOG_EVENT_TYPES = [
    'error', 'response.content.done', 'rate_limits.updated',
    'response.done', 'input_audio_buffer.committed',
    'input_audio_buffer.speech_stopped', 'input_audio_buffer.speech_started',
    'session.created'
]
SHOW_TIMING_MATH = False

class TwilioObserver(RealtimeObserver):
    def __init__(self, websocket):
        super().__init__()

        self.websocket = websocket

        # Connection specific state
        self.stream_sid = None
        self.latest_media_timestamp = 0
        self.last_assistant_item = None
        self.mark_queue = []
        self.response_start_timestamp_twilio = None

    async def update(self, response):
        """Receive events from the OpenAI Realtime API, send audio back to Twilio."""
        if response['type'] in LOG_EVENT_TYPES:
            print(f"Received event: {response['type']}", response)

        if response.get('type') == 'response.audio.delta' and 'delta' in response:
            audio_payload = base64.b64encode(base64.b64decode(response['delta'])).decode('utf-8')
            audio_delta = {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {
                    "payload": audio_payload
                }
            }
            await self.websocket.send_json(audio_delta)

            if self.response_start_timestamp_twilio is None:
                self.response_start_timestamp_twilio = self.latest_media_timestamp
                if SHOW_TIMING_MATH:
                    print(f"Setting start timestamp for new response: {self.response_start_timestamp_twilio}ms")

            # Update last_assistant_item safely
            if response.get('item_id'):
                self.last_assistant_item = response['item_id']

            await self.send_mark()

        # Trigger an interruption. Your use case might work better using `input_audio_buffer.speech_stopped`, or combining the two.
        if response.get('type') == 'input_audio_buffer.speech_started':
            print("Speech started detected.")
            if self.last_assistant_item:
                print(f"Interrupting response with id: {self.last_assistant_item}")
                await self.handle_speech_started_event()

    async def handle_speech_started_event(self):
        """Handle interruption when the caller's speech starts."""
        print("Handling speech started event.")
        if self.mark_queue and self.response_start_timestamp_twilio is not None:
            elapsed_time = self.latest_media_timestamp - self.response_start_timestamp_twilio
            if SHOW_TIMING_MATH:
                print(f"Calculating elapsed time for truncation: {self.latest_media_timestamp} - {self.response_start_timestamp_twilio} = {elapsed_time}ms")

            if self.last_assistant_item:
                if SHOW_TIMING_MATH:
                    print(f"Truncating item with ID: {self.last_assistant_item}, Truncated at: {elapsed_time}ms")

                truncate_event = {
                    "type": "conversation.item.truncate",
                    "item_id": self.last_assistant_item,
                    "content_index": 0,
                    "audio_end_ms": elapsed_time
                }
                await self.client.openai_ws.send(json.dumps(truncate_event))

            await self.websocket.send_json({
                "event": "clear",
                "streamSid": self.stream_sid
            })

            self.mark_queue.clear()
            self.last_assistant_item = None
            self.response_start_timestamp_twilio = None

    async def send_mark(self):
        if self.stream_sid:
            mark_event = {
                "event": "mark",
                "streamSid": self.stream_sid,
                "mark": {"name": "responsePart"}
            }
            await self.websocket.send_json(mark_event)
            self.mark_queue.append('responsePart')

    async def run(self, openai_ws):
        await self.initialize_session(openai_ws)

        try:
            async for message in self.websocket.iter_text():
                data = json.loads(message)
                if data['event'] == 'media' and openai_ws.open:
                    self.latest_media_timestamp = int(data['media']['timestamp'])
                    audio_append = {
                        "type": "input_audio_buffer.append",
                        "audio": data['media']['payload']
                    }
                    await openai_ws.send(json.dumps(audio_append))
                elif data['event'] == 'start':
                    self.stream_sid = data['start']['streamSid']
                    print(f"Incoming stream has started {self.stream_sid}")
                    self.response_start_timestamp_twilio = None
                    self.latest_media_timestamp = 0
                    self.last_assistant_item = None
                elif data['event'] == 'mark':
                    if self.mark_queue:
                        self.mark_queue.pop(0)
        except WebSocketDisconnect:
            print("Client disconnected.")
            if openai_ws.open:
                    await openai_ws.close()


    async def initialize_session(self, openai_ws):
        """Control initial session with OpenAI."""
        session_update = {
            "type": "session.update",
            "session": {
                "turn_detection": {"type": "server_vad"},
                "input_audio_format": "g711_ulaw",
                "output_audio_format": "g711_ulaw",
                "voice": VOICE,
                "instructions": SYSTEM_MESSAGE,
                "modalities": ["text", "audio"],
                "temperature": 0.8,
            }
        }
        print('Sending session update:', json.dumps(session_update))
        await openai_ws.send(json.dumps(session_update))
