# Cisco AI Assistant

**Cisco AI Assistant** is an experimental tool designed to explore the potential of Large Language Models (LLMs) as intelligent network device configurators.

While the current version demonstrates only simple command generation and interaction, it serves as proof-of-concept for a much broader vision. LLMs have the potential to:

- Equalize configurations across numerous devices
- Identify and correct configuration mistakes
- Summarize logs and alert data
- Configure multiple devices simultaneously
- Answer network troubleshooting questions
- And much more...

This tool is built to inspire experimentation and future development in the space of AI-driven network automation.

## Features

- LLM-based interaction for Cisco command suggestions
- Modular code structure for extension
- Simple command-line interface

## Requirements

- Python 3.8+
- [Install dependencies](#installation)

## Installation

1. Clone this repository:

    ```bash
    git clone https://github.com/Antonizitron/cisco_ai_assistant.git
    cd cisco_ai_assistant
    ```

2. (Optional but recommended) Create a virtual environment:

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3. Create file configuration.json by coping configuration.json.example and fill-in API key for using Gemini

4. Install dependencies:

    ```bash
    pip install -r requirements.txt
    ```

## Running the App

To run the Cisco AI Assistant, make sure you are in the directory that contains the `cisco_ai_assistant` folder, and run:

```bash
python -m cisco_ai_assistant.app
```

This will launch the assistant interface and allow you to interact with it via the command line.

## Example Use Cases

Even though this tool currently demonstrates basic command generation, future versions can be extended to:

- Audit existing device configurations
- Automatically generate remediation actions
- Validate against predefined network policies
- Generate configuration snippets for specific network roles

## Contributing
This is an experimental and evolving project. Contributions and ideas are welcome! Feel free to fork the repo, submit issues, or open pull requests.

## License
This project is licensed under the MIT License.
