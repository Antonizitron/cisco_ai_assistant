import serial
import time
import re

# DEBUG FLAG - TO SEE DETAILED SERIAL I/O
SERIAL_DEBUG = False

# Regex patterns for prompts
PROMPT_PATTERNS = {
    re.compile(r"[\w.-]+\(config-if\)#\s*$"): "CONF_IF",
    re.compile(r"[\w.-]+\(config-vlan\)#\s*$"): "CONF_VLAN",
    re.compile(r"[\w.-]+\(config-line\)#\s*$"): "CONF_LINE",
    re.compile(r"[\w.-]+\(config\)#\s*$"): "CONF_TERM",
    re.compile(r"[\w.-]+#\s*$"): "PRIVEXEC",
    re.compile(r"[\w.-]+>\s*$"): "EXEC",
    re.compile(r"(?i)Username:\s*$"): "LOGIN_USER", # Case insensitive
    re.compile(r"(?i)Password:\s*$"): "LOGIN_PASS", # Case insensitive
    re.compile(r"--More--\s*$"): "MORE",
    re.compile(r"\(yes\/no\)\?:?\s*$"): "CONFIRM_YN",
    re.compile(r"\[confirm\]\s*$"): "CONFIRM_ENTER",
    re.compile(r"confirm.*\[yes\/no\]:\s*$"): "CONFIRM_FULL_YN",
}


class SwitchCommunicator:
    def __init__(self, port, baudrate=9600, timeout=10):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.connection = None
        self.current_prompt_str = ""
        self.current_mode = "DISCONNECTED"
        self.logged_in = False
        self.enable_mode_active = False
        self.last_full_output = "" # Store last full raw output from _read_until_prompt

    def _log_debug(self, message):
        if SERIAL_DEBUG:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            print(f"DEBUG {timestamp} [SwitchComm]: {message}")

    def _read_until_prompt(self, custom_timeout=None, expected_specific_prompts=None):
        output_buffer = ""
        start_time = time.time()
        read_timeout = custom_timeout if custom_timeout is not None else self.timeout
        self._log_debug(f"_read_until_prompt: Timeout={read_timeout}s. Expecting specific: {expected_specific_prompts}")

        while True:
            if self.connection and self.connection.in_waiting > 0:
                try:
                    chunk = self.connection.read(self.connection.in_waiting).decode('utf-8', errors='replace')
                    self._log_debug(f"Read chunk: {repr(chunk)}")
                    output_buffer += chunk
                except Exception as e:
                    self._log_debug(f"Error decoding serial data: {e}")

            # Check for specific expected prompts first if provided
            if expected_specific_prompts:
                for mode_name_expected in expected_specific_prompts:
                    for pattern, mode_name_map in PROMPT_PATTERNS.items():
                        if mode_name_map == mode_name_expected:
                            match = pattern.search(output_buffer)
                            if match:
                                self.current_prompt_str = match.group(0).strip()
                                self.current_mode = mode_name_map
                                self.last_full_output = output_buffer
                                self._log_debug(f"Matched EXPECTED prompt! Mode='{self.current_mode}', Prompt='{self.current_prompt_str}'. Raw: {repr(output_buffer)}")
                                return output_buffer # Return everything including the prompt
            
            # Check all known prompts
            for pattern, mode_name in PROMPT_PATTERNS.items():
                match = pattern.search(output_buffer) # Search anywhere in the buffer
                if match:
                    self.current_prompt_str = match.group(0).strip() # The matched prompt string
                    self.current_mode = mode_name
                    self.last_full_output = output_buffer # Store raw output up to prompt
                    self._log_debug(f"Matched prompt! Mode='{self.current_mode}', Prompt='{self.current_prompt_str}'. Raw: {repr(output_buffer)}")
                    return output_buffer # Return everything including the prompt

            if time.time() - start_time > read_timeout:
                self.last_full_output = output_buffer # Store what we got
                self._log_debug(f"Timeout in _read_until_prompt. Buffer: {repr(output_buffer)}")
                self.current_prompt_str = output_buffer.splitlines()[-1].strip() if output_buffer.strip() else "TIMEOUT_NO_OUTPUT"
                self.current_mode = "UNKNOWN_TIMEOUT"
                return output_buffer # Return what we have

            time.sleep(0.15)

    def _send_and_read(self, data_bytes: bytes, read_timeout: int, expected_prompts=None):
        """Helper to send bytes and read response until prompt or timeout."""
        if not self.connection or not self.connection.is_open:
            self._log_debug("_send_and_read: Not connected.")
            return "Error: Not connected."
        self._log_debug(f"Writing bytes: {repr(data_bytes)}")
        self.connection.write(data_bytes)
        self.connection.flush()
        time.sleep(0.2) 
        return self._read_until_prompt(custom_timeout=read_timeout, expected_specific_prompts=expected_prompts)

    def connect(self):
        if self.connection and self.connection.is_open:
            self._log_debug("Connect: Already connected.")
            return True
        try:
            self._log_debug(f"Attempting to connect to {self.port} at {self.baudrate} baud...")
            self.connection = serial.Serial(self.port, self.baudrate, timeout=0.1)
            self._log_debug(f"Serial port {self.port} opened.")
            
            # Send an initial CRNL to clear buffers and elicit a prompt.
            self._log_debug("Sending initial CRNL to elicit prompt.")
            self.connection.write(b'\r\n') # CRNL
            self.connection.flush()
            time.sleep(1) # Give the switch more time to respond initially

            initial_output_raw = self._read_until_prompt(custom_timeout=15)
            self._log_debug(f"Initial connection raw output: {repr(initial_output_raw)}")
            self._log_debug(f"Post-connect state: Mode='{self.current_mode}', Prompt='{self.current_prompt_str}'")

            # If still no recognized prompt, try one more CR
            if self.current_mode == "UNKNOWN_TIMEOUT" and not self.current_prompt_str.strip().endswith(tuple(PROMPT_PATTERNS.keys())): # Check if prompt is known
                 self._log_debug("Warning: No clear prompt detected. Sending another CR.")
                 self.connection.write(b'\r')
                 self.connection.flush()
                 time.sleep(0.5)
                 second_attempt_raw = self._read_until_prompt(custom_timeout=5)
                 self._log_debug(f"Second attempt raw output: {repr(second_attempt_raw)}")
                 self._log_debug(f"Post-connect 2nd attempt state: Mode='{self.current_mode}', Prompt='{self.current_prompt_str}'")
            
            if self.current_mode in ["DISCONNECTED", "UNKNOWN_TIMEOUT"] or not self.current_prompt_str:
                print(f"Error: Could not establish a clear initial prompt on {self.port}. Last mode: {self.current_mode}, last prompt: '{self.current_prompt_str}'. Raw: {repr(self.last_full_output)}")
                self.disconnect() # Ensure port is closed if connect fails
                return False
            
            print(f"Connected. Initial mode: {self.current_mode}, prompt: '{self.current_prompt_str}'")
            return True
        except serial.SerialException as e:
            print(f"FATAL: Error connecting to switch on {self.port}: {e}")
            self.connection = None
            self.current_mode = "DISCONNECTED"
            return False
        except Exception as e: # Catch any other unexpected error during connection
            print(f"FATAL: Unexpected error during connect: {e}")
            if self.connection: self.connection.close()
            self.connection = None
            self.current_mode = "DISCONNECTED"
            return False

    def login(self, username, password, enable_password):
        if not self.connection or not self.connection.is_open:
            self._log_debug("Login: Not connected.")
            print("Not connected. Cannot login.")
            return False

        if self.logged_in and self.enable_mode_active:
            self._log_debug("Login: Already logged in and in enable mode.")
            return True

        self._log_debug(f"Login process started. Current mode: {self.current_mode}, Prompt: '{self.current_prompt_str}'")

        # Step 0: Ensure we are at a login prompt or already past it.
        # If the initial prompt is already EXEC or PRIVEXEC, we might be auto-logged in or session resumed.
        if self.current_mode in ["EXEC", "PRIVEXEC"]:
            self._log_debug("Login: Detected EXEC or PRIVEXEC mode initially. Assuming logged in.")
            self.logged_in = True
        # If not at a specific login prompt, send a CR to see if it produces one.
        elif self.current_mode not in ["LOGIN_USER", "LOGIN_PASS"]:
            self._log_debug("Login: Not at a login prompt. Sending CR to elicit Username/Password prompt.")
            self._send_and_read(b'\r', read_timeout=5, expected_prompts=["LOGIN_USER", "LOGIN_PASS", "EXEC", "PRIVEXEC"])
            self._log_debug(f"Login: After CR. Mode: {self.current_mode}, Prompt: '{self.current_prompt_str}'")


        # Step 1: Username
        if self.current_mode == "LOGIN_USER":
            self._log_debug(f"Sending username: '{username}'")
            self._send_and_read(f"{username}\r".encode('ascii'), read_timeout=10, expected_prompts=["LOGIN_PASS"])
            self._log_debug(f"Login: After username. Mode: {self.current_mode}, Prompt: '{self.current_prompt_str}'")
            if self.current_mode != "LOGIN_PASS":
                print(f"Login Error: Expected password prompt after username, got mode '{self.current_mode}' (prompt: '{self.current_prompt_str}'). Raw: {repr(self.last_full_output)}")
                return False
        elif self.current_mode == "LOGIN_PASS":
            self._log_debug("Login: Already at password prompt.")
        elif not self.logged_in: # If not EXEC/PRIVEXEC and not LOGIN_USER/LOGIN_PASS
            print(f"Login Error: Unexpected state before username. Mode: '{self.current_mode}' (prompt: '{self.current_prompt_str}'). Raw: {repr(self.last_full_output)}")
            return False

        # Step 2: Password
        if self.current_mode == "LOGIN_PASS" and not self.logged_in:
            self._log_debug("Sending user password: '********'")
            self._send_and_read(f"{password}\r".encode('ascii'), read_timeout=15, expected_prompts=["EXEC", "PRIVEXEC", "LOGIN_USER"]) # Expect EXEC/PRIVEXEC, or LOGIN_USER on failure
            self._log_debug(f"Login: After user password. Mode: {self.current_mode}, Prompt: '{self.current_prompt_str}'")
            if self.current_mode not in ["EXEC", "PRIVEXEC"]:
                print(f"Login Error: Authentication failed or unexpected mode after password. Mode: '{self.current_mode}' (prompt: '{self.current_prompt_str}'). Raw: {repr(self.last_full_output)}")
                # A common failure is to be returned to "Username:" prompt.
                if self.current_mode == "LOGIN_USER" or "Login invalid" in self.last_full_output:
                    print("Login Error: Credentials likely incorrect.")
                return False
            self.logged_in = True
            print("User login successful.")

        if not self.logged_in: # Should be logged_in if previous steps were successful
            print(f"Login Error: Failed to confirm user login. Final mode before enable: {self.current_mode}")
            return False

        # Step 3: Enable Mode
        if self.current_mode == "EXEC" and not self.enable_mode_active:
            self._log_debug("Entering enable mode...")
            self._send_and_read(b"enable\r", read_timeout=10, expected_prompts=["LOGIN_PASS", "PRIVEXEC"])
            self._log_debug(f"Login: After 'enable' command. Mode: {self.current_mode}, Prompt: '{self.current_prompt_str}'")

            if self.current_mode == "LOGIN_PASS": # Expecting enable password
                self._log_debug("Sending enable password: '********'")
                self._send_and_read(f"{enable_password}\r".encode('ascii'), read_timeout=10, expected_prompts=["PRIVEXEC", "EXEC"]) # Expect PRIVEXEC, or EXEC on failure
                self._log_debug(f"Login: After enable password. Mode: {self.current_mode}, Prompt: '{self.current_prompt_str}'")
                if self.current_mode != "PRIVEXEC":
                    print(f"Login Error: Enable password failed or unexpected mode. Mode: '{self.current_mode}' (prompt: '{self.current_prompt_str}'). Raw: {repr(self.last_full_output)}")
                    return False
            elif self.current_mode != "PRIVEXEC": # 'enable' command failed to get to PRIVEXEC or ask for password
                 print(f"Login Error: Failed to enter enable mode or get password prompt. Mode: '{self.current_mode}' (prompt: '{self.current_prompt_str}'). Raw: {repr(self.last_full_output)}")
                 return False
        
        if self.current_mode == "PRIVEXEC":
            self.enable_mode_active = True
            print("Enable mode active.")
            # Disable paging - critical for automation
            self.send_command("terminal length 0", expect_prompt_after=True, timeout_override=5)
            self._log_debug("Paging disabled ('terminal length 0'). Current prompt after term len 0: " + self.current_prompt_str)
            return True
        elif self.enable_mode_active: # Already in enable from start
             print("Already in enable mode.")
             # Check and set terminal length if not already set
             show_term_output = self.send_command("show terminal", timeout_override=5)
             if "Length: 0 lines" not in show_term_output:
                 self.send_command("terminal length 0", expect_prompt_after=True, timeout_override=5)
                 self._log_debug("Paging disabled ('terminal length 0') for pre-existing enable mode.")
             return True
        else: # Should not happen if logic is correct
            print(f"Login Error: Could not confirm enable mode. Final mode: {self.current_mode}")
            return False

    def send_command(self, command: str, timeout_override=None, expect_prompt_after=True):
        if not self.connection or not self.connection.is_open:
            self._log_debug(f"Send_command: Not connected for command '{command}'.")
            return "Error: Not connected."
        
        if not command.strip():
            self._log_debug("Send_command: Empty command received, not sending.")
            return ""

        effective_timeout = timeout_override if timeout_override is not None else self.timeout
        self._log_debug(f"Sending command ({self.current_mode}): '{command}' with timeout {effective_timeout}s")
        
        # Send command with CR
        raw_output_from_send = self._send_and_read(f"{command}\r".encode('ascii'), read_timeout=effective_timeout)
        
        # The raw_output_from_send includes the command echo (usually) and the prompt.
        output_lines = raw_output_from_send.splitlines()
        cleaned_output_lines = []

        if output_lines:
            # Check if the first non-empty line is the command echo
            first_content_line_idx = 0
            while first_content_line_idx < len(output_lines) and not output_lines[first_content_line_idx].strip():
                first_content_line_idx += 1
            
            if first_content_line_idx < len(output_lines):
                if output_lines[first_content_line_idx].strip() == command.strip():
                    self._log_debug(f"Send_command ('{command}'): Stripping echo: '{output_lines[first_content_line_idx]}'")
                    cleaned_output_lines = output_lines[first_content_line_idx+1:]
                else:
                    cleaned_output_lines = output_lines
            else: # All lines were empty
                cleaned_output_lines = output_lines
        else: # No output lines
            cleaned_output_lines = output_lines
            
        # Join back and then strip the prompt from the end
        interim_output = "\n".join(cleaned_output_lines).strip()
        
        # Strip the detected prompt from the very end of the interim_output
        final_cleaned_output = interim_output
        if self.current_prompt_str and interim_output.endswith(self.current_prompt_str):
            final_cleaned_output = interim_output[:-len(self.current_prompt_str)].strip()
            self._log_debug(f"Send_command ('{command}'): Stripped prompt '{self.current_prompt_str}' from end.")

        if final_cleaned_output == command.strip():
            final_cleaned_output = ""


        # Handle "--More--"
        full_response_so_far = final_cleaned_output
        while self.current_mode == "MORE":
            self._log_debug(f"Send_command ('{command}'): Detected --More--. Sending space.")
            if full_response_so_far.endswith("--More--"): # Simple check
                 full_response_so_far = full_response_so_far[:-len("--More--")].strip()
            elif "--More--" in full_response_so_far: # If it's not exactly at the end
                 full_response_so_far = full_response_so_far.replace("--More--", "").strip()


            more_raw_output = self._send_and_read(b" ", read_timeout=effective_timeout) # Send space
            
            more_output_lines = more_raw_output.splitlines()
            more_cleaned_interim = "\n".join(more_output_lines).strip() # No echo to strip for space typically
            more_final_cleaned = more_cleaned_interim
            if self.current_prompt_str and more_cleaned_interim.endswith(self.current_prompt_str) and self.current_mode != "MORE":
                more_final_cleaned = more_cleaned_interim[:-len(self.current_prompt_str)].strip()

            full_response_so_far += "\n" + more_final_cleaned.strip()
            self._log_debug(f"Send_command ('{command}'): Appended more data. Current mode: {self.current_mode}")
        
        self._log_debug(f"Send_command ('{command}') RSP (final cleaned):\n{full_response_so_far.strip()}")
        return full_response_so_far.strip()

    def get_current_mode_and_prompt(self):
        if self.connection and self.connection.is_open:
            self._log_debug("get_current_mode_and_prompt: Sending CR to refresh prompt.")
            self._send_and_read(b'\r', read_timeout=3) # Short timeout for prompt refresh
        self._log_debug(f"get_current_mode_and_prompt: Mode='{self.current_mode}', Prompt='{self.current_prompt_str}'")
        return self.current_mode, self.current_prompt_str
        
    def disconnect(self):
        if self.connection and self.connection.is_open:
            self._log_debug("Disconnecting...")
            try:
                # Graceful exit attempts
                if self.current_mode.startswith("CONF_") and self.current_mode != "CONF_TERM":
                    self.send_command("exit", expect_prompt_after=True, timeout_override=3)
                if self.current_mode == "CONF_TERM":
                    self.send_command("end", expect_prompt_after=True, timeout_override=3)
                if self.current_mode == "PRIVEXEC":
                     self.send_command("exit", expect_prompt_after=True, timeout_override=3) # To EXEC
                if self.current_mode == "EXEC":
                     self._log_debug("Sending final 'exit' from EXEC mode.")
                     self.connection.write(b"exit\r")
                     self.connection.flush()
                     time.sleep(0.5)
            except Exception as e:
                self._log_debug(f"Minor error during graceful disconnect sequence: {e}")
            finally:
                self.connection.close()
                self._log_debug("Serial port closed.")
                print("Disconnected from switch.")
        else:
            self._log_debug("Disconnect: No active connection or already closed.")
            
        self.connection = None # Ensure connection object is cleared
        self.current_mode = "DISCONNECTED"
        self.current_prompt_str = ""
        self.logged_in = False
        self.enable_mode_active = False

    def ensure_mode(self, target_mode: str, config_details: str = None):
        self.get_current_mode_and_prompt() # Refresh current state
        current_m, current_p = self.current_mode, self.current_prompt_str
        self._log_debug(f"ensure_mode: Target='{target_mode}', Current='{current_m}', Config='{config_details}'")

        if target_mode == current_m:
            if target_mode == "CONF_IF" and config_details and config_details.split()[-1].lower() not in current_p.lower(): # e.g. "interface GigabitEthernet0/1"
                self._log_debug(f"ensure_mode: In {target_mode} but not for '{config_details}'. Re-entering.")
                # Fall through to re-enter logic
            elif target_mode == "CONF_VLAN" and config_details and config_details.split()[-1] not in current_p: # e.g. "vlan 100"
                self._log_debug(f"ensure_mode: In {target_mode} but not for '{config_details}'. Re-entering.")
                # Fall through to re-enter logic
            else:
                self._log_debug(f"ensure_mode: Already in target mode '{target_mode}'.")
                return True

        # Path to PRIVEXEC
        if target_mode == "PRIVEXEC":
            if current_m == "EXEC":
                self._log_debug("ensure_mode: In EXEC, attempting 'enable'.")
                self.send_command("enable", expect_prompt_after=True) # Assumes enable pw handled by login
                return self.current_mode == "PRIVEXEC"
            elif current_m.startswith("CONF_"):
                self._log_debug(f"ensure_mode: In {current_m}, sending 'end'.")
                self.send_command("end", expect_prompt_after=True)
                return self.current_mode == "PRIVEXEC"
            else:
                self._log_debug(f"ensure_mode: Cannot ensure PRIVEXEC from {current_m}. Login issue?")
                return False

        # Path to CONF_TERM
        elif target_mode == "CONF_TERM":
            if current_m == "PRIVEXEC":
                self._log_debug("ensure_mode: In PRIVEXEC, sending 'configure terminal'.")
                self.send_command("configure terminal", expect_prompt_after=True)
                return self.current_mode == "CONF_TERM"
            elif current_m.startswith("CONF_") and current_m != "CONF_TERM": # e.g. CONF_IF
                self._log_debug(f"ensure_mode: In {current_m}, sending 'exit' to reach CONF_TERM.")
                self.send_command("exit", expect_prompt_after=True) 
                return self.current_mode == "CONF_TERM"
            else:
                if self.ensure_mode("PRIVEXEC"):
                    return self.ensure_mode("CONF_TERM")
                return False
        
        # Path to specific sub-config modes (e.g., CONF_IF)
        elif target_mode.startswith("CONF_") and config_details:
            if not self.ensure_mode("CONF_TERM"):
                self._log_debug(f"ensure_mode: Failed to reach CONF_TERM for {config_details}.")
                return False
            self._log_debug(f"ensure_mode: In CONF_TERM, sending '{config_details}'.")
            self.send_command(config_details, expect_prompt_after=True)
            # Check if the mode matches the *general type* (CONF_IF, CONF_VLAN)
            # More specific check (e.g. self.current_mode == target_mode) is good.
            if self.current_mode == target_mode:
                 self._log_debug(f"ensure_mode: Successfully entered {target_mode} for {config_details}.")
                 return True
            self._log_debug(f"ensure_mode: After sending '{config_details}', mode is {self.current_mode}, expected {target_mode}.")
            return False # Be strict: if not exact target_mode, it failed.

        self._log_debug(f"ensure_mode: Unsupported target_mode '{target_mode}' or path not implemented.")
        return False