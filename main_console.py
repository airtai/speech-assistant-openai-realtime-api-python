import asyncio
import os
from typing import Annotated
from dotenv import load_dotenv

from openai_client import OpenAIRealtimeClient

from observers.openai_observer import OpenAIVoiceObserver as OpenAIVoiceAudioAdapter

load_dotenv()

# Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
PORT = int(os.getenv('PORT', 5050))

llm_config = {
    "timeout": 600,
    "cache_seed": 45,  # change the seed for different trials
    "config_list": [
        {
            "model": "gpt-4o-realtime-preview-2024-10-01",
            "api_key": OPENAI_API_KEY,
        }
    ],
    "temperature": 0.8,
}


async def main():
    audio_adapter = OpenAIVoiceAudioAdapter()
    openai_client = OpenAIRealtimeClient(
        system_message="Hello there! I am an AI voice assistant powered by Twilio and the OpenAI Realtime API. You can ask me for facts, jokes, or anything you can imagine. How can I help you?",
        llm_config=llm_config,
        audio_adapter=audio_adapter
    )

    @openai_client.register_tool(name="get_weather", description="Get the current weather")
    def get_weather(location: Annotated[str, "city"]) -> str:
        ...
        return "The weather is cloudy." if location == "Seattle" else "The weather is sunny."

    await openai_client.run()
            

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    loop.close()
