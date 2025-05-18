import time
import re
from .config_loader import load_config
from .switch_communicator import SwitchCommunicator
from .llm_translator import LLMTranslator


DEFAULT_SWITCH_MODEL = "Cisco 2960X" 
SERIAL_PORT = "COM4"
APP_NAME = "OT-AI"


class CiscoAIAssistant:
    def __init__(self):
        print("Initializing Cisco AI Assistant...")
        try:
            self.config = load_config()
        except Exception as e:
            print(f"FATAL: Could not load configuration: {e}")
            exit(1)

        self.switch_comm = SwitchCommunicator(port=SERIAL_PORT)
        self.llm_translator = LLMTranslator(api_key=self.config['gemini_api_key'])
        self.switch_model = DEFAULT_SWITCH_MODEL

    def _initial_setup(self):
        print("\nAttempting to connect to the switch...")
        if not self.switch_comm.connect():
            print(f"Failed to connect to switch on {SERIAL_PORT}. Please check connection and port.")
            return False
        
        print("\nAttempting to login to the switch...")
        if not self.switch_comm.login(
            self.config['switch_username'],
            self.config['switch_password'],
            self.config['switch_enable_password']
        ):
            print("Failed to login to the switch. Please check credentials.")
            self.switch_comm.disconnect()
            return False
        
        print("\nSuccessfully connected and logged into the switch.")
        time.sleep(0.5) 
        self.switch_comm.get_current_mode_and_prompt()
        print(f"Switch is in mode: {self.switch_comm.current_mode} (Prompt: '{self.switch_comm.current_prompt_str}')")
        return True


    def _parse_initial_user_statement(self, statement: str):
        global SERIAL_PORT 
        
        words = statement.lower().split()
        try:
            cisco_idx = words.index("cisco")
            if cisco_idx + 1 < len(words) and words[cisco_idx+1] not in ["over", "on", "port"]:
                self.switch_model = f"Cisco {words[cisco_idx+1].upper()}"
                print(f"SYSTEM: Switch model identified as {self.switch_model}.")
        except ValueError:
            pass

        try:
            port_idx = -1
            for i, word in enumerate(words):
                if word.startswith("com") and len(word) > 3 and word[3:].isdigit():
                    port_idx = i
                    new_port = word.upper()
                    break
                if word == "port" and i + 1 < len(words) and words[i+1].upper().startswith("COM"):
                    port_idx = i +1
                    new_port = words[i+1].upper()
                    break
            
            if port_idx != -1:
                if new_port != SERIAL_PORT:
                    SERIAL_PORT = new_port 
                    self.switch_comm.port = SERIAL_PORT 
                    print(f"SYSTEM: Serial port updated to {SERIAL_PORT}.")
        except ValueError:
            pass


    def run(self):
        print("Welcome to the Cisco AI Assistant!")
        print("Type 'exit' or 'quit' to end the session.")
        
        initial_query = input("You: ")
        if initial_query.lower() in ["exit", "quit"]:
            print(f"{APP_NAME}: Exiting.")
            return

        self._parse_initial_user_statement(initial_query)

        if not self._initial_setup():
            print(f"{APP_NAME}: Could not establish connection with the switch. Exiting.")
            return
        
        task_query = initial_query
        cleaned_query = initial_query
        patterns_to_remove = [
            r"you are connected to .*?(cisco \w+)? (over|on) serial port (com\d+)\s*\.?",
            r"(connect(ed)? to )?(cisco \w+)? (on|over|via) (port )?(com\d+)\s*\.?",
        ]
        for pattern in patterns_to_remove:
            cleaned_query = re.sub(pattern, "", cleaned_query, flags=re.IGNORECASE).strip(" .")
        
        if cleaned_query and len(cleaned_query) < len(initial_query) / 1.5 : # Heuristic: if significantly shorter, it's likely the task
            task_query = cleaned_query
        elif not cleaned_query and ("cisco" in initial_query.lower() or "com" in initial_query.lower()):
            task_query = input(f"{APP_NAME}: Setup seems complete. What is your actual request for {self.switch_model}?\nYou: ")
        
        if task_query:
             self._process_user_query(task_query)
        else:
            print(f"{APP_NAME}: No specific task identified in the initial statement.")


        while True:
            user_input = input("You: ")
            if user_input.lower() in ["exit", "quit"]:
                break
            if not user_input.strip():
                continue
            self._process_user_query(user_input)

        print(f"{APP_NAME}: Session ended. Disconnecting from switch...")
        self.switch_comm.disconnect()
        print(f"{APP_NAME}: Goodbye!")

    def _execute_commands(self, commands_to_run: list) -> tuple[list, bool]:
        """Helper to execute a list of commands and collect outputs."""
        all_outputs = []
        success = True
        if not commands_to_run:
            return all_outputs, success

        print(f"{APP_NAME}: I will run the following preparatory/task commands:")
        for cmd in commands_to_run:
            print(f"  - {cmd}")
        
        for cmd_idx, cmd in enumerate(commands_to_run):
            print(f"\n{APP_NAME}: Executing command {cmd_idx+1}/{len(commands_to_run)}: {cmd}")
            output = self.switch_comm.send_command(cmd)
            all_outputs.append(f"--- Output for '{cmd}' ---\n{output}")
            
            if "%" in output.splitlines()[0] if output.strip() else False:
                error_line = next((line for line in output.splitlines() if "%" in line), "Error indication found.")
                print(f"{APP_NAME}: Potential error detected executing '{cmd}': {error_line}")
                all_outputs.append(f"Error detected: {error_line}")
                success = False
                print(f"{APP_NAME}: Stopping command execution due to potential error.")
                break 
        return all_outputs, success

    def _process_user_query(self, user_query: str):
        print(f"\n{APP_NAME}: Processing '{user_query}'...")
        
        current_mode, current_prompt = self.switch_comm.get_current_mode_and_prompt()
        if current_mode == "DISCONNECTED":
            print(f"{APP_NAME}: Switch is disconnected. Attempting to reconnect...")
            if not self._initial_setup():
                print(f"{APP_NAME}: Reconnection failed. Cannot process query.")
                return
            current_mode, current_prompt = self.switch_comm.get_current_mode_and_prompt()

        print(f"{APP_NAME}: Current switch state: Mode='{current_mode}', Prompt='{current_prompt}' for model '{self.switch_model}'")

        llm_data = self.llm_translator.get_cisco_commands(
            user_query,
            self.switch_model,
            current_mode,
            current_prompt
        )

        if llm_data.get("query_type") == "ERROR" or not llm_data:
            error_msg = llm_data.get("error", "LLM did not return a valid plan.")
            print(f"{APP_NAME}: I couldn't understand or plan for that request. LLM said: {error_msg}")
            return

        query_type = llm_data.get("query_type")
        commands_to_run = llm_data.get("commands_to_execute", [])
        info_retrieval_cmd = llm_data.get("information_retrieval_command", "")
        requires_extraction = llm_data.get("requires_answer_extraction", False)

        prep_outputs, prep_success = [], True
        if commands_to_run:
            if query_type == "QUESTION" and commands_to_run:
                 print(f"{APP_NAME}: LLM suggested preparatory commands before information retrieval.")
            prep_outputs, prep_success = self._execute_commands(commands_to_run)
        
        if not prep_success:
            print(f"{APP_NAME}: Failed to execute preparatory/task commands. Aborting further actions for this query.")
            final_response = f"{APP_NAME}: Task execution failed.\n"
            final_response += "\n--- Combined raw output from commands ---\n"
            final_response += "\n\n".join(prep_outputs)
            final_response += "\n--- End of raw output ---\n"
            print(f"\n{final_response}")
            self.switch_comm.get_current_mode_and_prompt()
            return

        if query_type == "TASK":
            print(f"{APP_NAME}: Task execution sequence complete.")
            if info_retrieval_cmd:
                print(f"\n{APP_NAME}: Now running verification command: {info_retrieval_cmd}")
                time.sleep(0.5)
                verification_output = self.switch_comm.send_command(info_retrieval_cmd, timeout_override=15)
                
                response_message = f"{APP_NAME}: VLAN 100 Management is created:"
                response_message = f"{APP_NAME}: Task completed. Verification output for '{info_retrieval_cmd}':"
                print(f"{response_message}\n{verification_output}")
            else:
                print(f"{APP_NAME}: Task completed. No verification command was suggested.")
            
            if prep_outputs:
                print("\n--- Raw output from task commands ---")
                print("\n\n".join(prep_outputs))
                print("--- End of raw output ---")


        elif query_type == "QUESTION":
            if not info_retrieval_cmd:
                print(f"{APP_NAME}: I understood it as a question, but I don't have a specific command to get that information.")
                return

            print(f"\n{APP_NAME}: To answer your question, I will run: {info_retrieval_cmd}")
            retrieval_output = self.switch_comm.send_command(info_retrieval_cmd, timeout_override=15)
            
            if requires_extraction:
                print(f"{APP_NAME}: Extracting a concise answer from the output...")
                extracted_answer = self.llm_translator.extract_answer_from_output(user_query, retrieval_output)
                print(f"{APP_NAME} Answer: {extracted_answer}")
                if "information is not found" not in extracted_answer.lower() and \
                   "error extracting answer" not in extracted_answer.lower():
                     show_raw = input(f"{APP_NAME}: Would you like to see the full raw output? (yes/no): ").lower()
                     if show_raw == 'yes':
                         print(f"\n--- Raw output for '{info_retrieval_cmd}' ---\n{retrieval_output}")
                else:
                    print(f"\n--- Raw output for '{info_retrieval_cmd}' ---\n{retrieval_output}")

            else:
                print(f"{APP_NAME}: Here is the information from command '{info_retrieval_cmd}':")
                print(f"\n{retrieval_output}")
        
        else:
            print(f"{APP_NAME}: I'm not sure how to handle that request (LLM type: {query_type}).")
            if prep_outputs:
                print("\n--- Raw output from attempted commands ---")
                print("\n\n".join(prep_outputs))
                print("--- End of raw output ---")


        current_mode, current_prompt = self.switch_comm.get_current_mode_and_prompt()
        print(f"\n{APP_NAME}: Switch is now in mode: {current_mode} (Prompt: '{current_prompt}')")


def main():
    assistant = CiscoAIAssistant()
    try:
        assistant.run()
    except KeyboardInterrupt:
        print("\n{APP_NAME}: Keyboard interrupt detected. Shutting down...")
    except Exception as e:
        print(f"\n{APP_NAME}: An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if hasattr(assistant, 'switch_comm') and assistant.switch_comm and assistant.switch_comm.connection:
            print(f"{APP_NAME}: Ensuring final disconnect.")
            assistant.switch_comm.disconnect()

if __name__ == "__main__":
    main()