import os


class InferenceSettings:
    def __init__(self):
        self.model_name = os.getenv("MODEL_NAME", "google/gemma-4-12B-it-qat-w4a16-ct")
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.6"))
        self.timeout = float(os.getenv("LLM_TIMEOUT", "30.0"))
        self.max_retries = int(os.getenv("LLM_MAX_RETRIES", "2"))
        self.max_context_turns = int(os.getenv("MAX_CONTEXT_TURNS", "20"))
        self.max_tool_iterations = int(os.getenv("MAX_TOOL_ITERATIONS", "5"))


settings = InferenceSettings()
