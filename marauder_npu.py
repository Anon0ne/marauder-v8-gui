"""Optional local OpenVINO GenAI backend. An explicit NPU target never falls back."""
from pathlib import Path
import threading

_pipeline = None
_model_path = None
_lock = threading.Lock()
MAX_PROMPT_TOKENS = 2048
MAX_RESPONSE_TOKENS = 256


def devices():
    import openvino as ov
    core = ov.Core()
    return {name: core.get_property(name, 'FULL_DEVICE_NAME') for name in core.available_devices}


def load(model_path):
    global _pipeline, _model_path
    import openvino_genai as genai
    path = Path(model_path).expanduser().resolve()
    required = ('openvino_model.xml', 'openvino_model.bin',
                'openvino_tokenizer.xml', 'openvino_detokenizer.xml')
    missing = [name for name in required if not (path / name).is_file()]
    if missing:
        raise RuntimeError('Incomplete OpenVINO model folder: ' + ', '.join(missing))
    found = devices()
    if not any(name == 'NPU' or name.startswith('NPU.') for name in found):
        raise RuntimeError('OpenVINO cannot access an NPU. Check the Intel NPU driver. '
                           'Detected devices: ' + ', '.join(found))
    with _lock:
        if _pipeline is not None and _model_path == str(path):
            return 'NPU'
        # Release an older pipeline before compiling a different model.
        _pipeline = None
        _model_path = None
        _pipeline = genai.LLMPipeline(str(path), 'NPU',
                                     MAX_PROMPT_LEN=MAX_PROMPT_TOKENS,
                                     MIN_RESPONSE_LEN=MAX_RESPONSE_TOKENS)
        _model_path = str(path)
    return 'NPU'


def chat(messages, system='', model=None, stream_cb=None, **kwargs):
    if model:
        load(model)
    with _lock:
        if _pipeline is None:
            raise RuntimeError('Select and verify an OpenVINO NPU model first.')
        # Render role boundaries through the model's own template. Limit history
        # by complete turns and token count instead of silently truncating prompts.
        turns = ([{'role': 'system', 'content': system}] if system else []) + list(messages)
        tokenizer = _pipeline.get_tokenizer()
        prompt = tokenizer.apply_chat_template(turns, add_generation_prompt=True)
        tokens = tokenizer.encode(prompt).input_ids
        if tokens.get_size() > MAX_PROMPT_TOKENS:
            raise RuntimeError('NPU context limit reached (2048 tokens). Start a new chat '
                               'or shorten the observations/question.')
        result = _pipeline.generate(prompt, max_new_tokens=MAX_RESPONSE_TOKENS,
                                    do_sample=False, apply_chat_template=False,
                                    repetition_penalty=1.12)
        text = str(result)
        if stream_cb:
            stream_cb(text)
        return text


def smoke_test(model_path):
    load(model_path)
    return chat([{'role': 'user', 'content': 'Reply with one short greeting.'}])


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--model')
    args = parser.parse_args()
    print('OpenVINO devices:', devices())
    if args.model:
        print('NPU generation:', smoke_test(args.model))
