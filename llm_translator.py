import google.generativeai as genai
import json
from .prompts import GEMINI_SYSTEM_PROMPT, GEMINI_ANSWER_EXTRACTION_PROMPT

class LLMTranslator:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Gemini API key is required.")
        genai.configure(api_key=api_key)
        #self.model = genai.GenerativeModel('gemini-2.5-pro-preview-05-06')
        self.model = genai.GenerativeModel('gemini-2.0-flash')
        #self.model = genai.GenerativeModel('gemini-1.5-flash-latest') 

    def _parse_llm_json_response(self, response_text: str, expected_keys: list) -> dict:
        """Helper to clean and parse JSON from LLM response."""
        cleaned_response_text = response_text.strip()
        if cleaned_response_text.startswith("```json"):
            cleaned_response_text = cleaned_response_text[7:]
        if cleaned_response_text.endswith("```"):
            cleaned_response_text = cleaned_response_text[:-3]
        cleaned_response_text = cleaned_response_text.strip()

        json_start = cleaned_response_text.find('{')
        json_end = cleaned_response_text.rfind('}')
        if json_start != -1 and json_end != -1 and json_end > json_start:
            json_str = cleaned_response_text[json_start : json_end+1]
            parsed_response = json.loads(json_str)
            for key in expected_keys:
                if key not in parsed_response:
                    if key == "commands_to_execute": parsed_response[key] = []
                    elif key == "information_retrieval_command": parsed_response[key] = ""
                    elif key == "requires_answer_extraction": parsed_response[key] = False
                    elif key == "query_type": parsed_response[key] = "UNKNOWN"
                    else:
                        raise ValueError(f"LLM response missing required key: '{key}'")
            return parsed_response
        else:
            raise ValueError(f"Could not parse JSON from LLM response: '{cleaned_response_text}'")

    def get_cisco_commands(self, user_query: str, switch_model: str, current_mode: str, current_prompt: str) -> dict:
        """
        Translates natural language query to Cisco commands or info retrieval plan.
        Returns a dictionary with "query_type", "commands_to_execute",
        "information_retrieval_command", and "requires_answer_extraction".
        """
        prompt_template = GEMINI_SYSTEM_PROMPT
        full_query = prompt_template.format(
            switch_model=switch_model,
            current_mode=current_mode,
            current_prompt=current_prompt
        )
        
        full_query += f"\n\nUser Request: \"{user_query}\"\nExample JSON Output:"

        try:
            response = self.model.generate_content(full_query)
            
            expected_keys = ["query_type", "commands_to_execute", "information_retrieval_command", "requires_answer_extraction"]
            parsed_data = self._parse_llm_json_response(response.text, expected_keys)
            return parsed_data

        except json.JSONDecodeError as e:
            print(f"LLM Error (get_cisco_commands): Failed to decode JSON: {e}")
            print(f"Problematic response text: {response.text if 'response' in locals() else 'N/A'}")
            return {"query_type": "ERROR", "error": f"JSON Decode Error: {e}"}
        except ValueError as e: # Catch our custom ValueError from _parse_llm_json_response
            print(f"LLM Error (get_cisco_commands): Invalid response structure: {e}")
            return {"query_type": "ERROR", "error": f"Invalid LLM response: {e}"}
        except Exception as e:
            print(f"LLM Error (get_cisco_commands): An unexpected error occurred: {e}")
            return {"query_type": "ERROR", "error": str(e)}

    def extract_answer_from_output(self, original_question: str, switch_output: str) -> str:
        """
        Uses LLM to extract a concise answer from switch output based on the original question.
        """
        prompt = GEMINI_ANSWER_EXTRACTION_PROMPT.format(
            original_question=original_question,
            switch_output=switch_output
        )
        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"LLM Error (extract_answer): An unexpected error occurred: {e}")
            return f"Error extracting answer: {e}"