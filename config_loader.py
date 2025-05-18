import json
import os

CREDENTIALS_FILE = "cisco_ai_assistant/credentials.json"

def load_config():
    """Loads configuration from the credentials file."""
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(
            f"{CREDENTIALS_FILE} not found. "
            f"Please create it by copying and modifying credentials.json.example."
        )
    try:
        with open(CREDENTIALS_FILE, 'r') as f:
            config = json.load(f)
        
        required_keys = ["switch_username", "switch_password", "switch_enable_password", "gemini_api_key"]
        for key in required_keys:
            if key not in config or not config[key]:
                raise ValueError(f"Missing or empty value for '{key}' in {CREDENTIALS_FILE}")
        return config
    except json.JSONDecodeError:
        raise ValueError(f"Error decoding JSON from {CREDENTIALS_FILE}.")
    except Exception as e:
        raise RuntimeError(f"Could not load configuration: {e}")