import os


class InferenceSettings:
    def __init__(self):
        self.model_name = os.getenv("MODEL_NAME", "google/gemma-4-12B-it-qat-w4a16-ct")
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.6"))
        self.timeout = float(os.getenv("LLM_TIMEOUT", "30.0"))
        self.max_retries = int(os.getenv("LLM_MAX_RETRIES", "2"))
        self.max_context_turns = int(os.getenv("MAX_CONTEXT_TURNS", "20"))
        self.max_tool_iterations = int(os.getenv("MAX_TOOL_ITERATIONS", "5"))

        if not self.model_name:
            raise ValueError("model_name must not be empty")
        if not (0.0 <= self.temperature <= 2.0):
            raise ValueError("temperature must be between 0.0 and 2.0")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.max_context_turns < 1:
            raise ValueError("max_context_turns must be at least 1")
        if self.max_tool_iterations < 1:
            raise ValueError("max_tool_iterations must be at least 1")


settings = InferenceSettings()
