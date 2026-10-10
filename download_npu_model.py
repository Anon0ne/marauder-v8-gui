"""Download pinned model data only; never execute downloaded Python code."""
from pathlib import Path
from huggingface_hub import snapshot_download

MODEL_ID = 'OpenVINO/Phi-3.5-mini-instruct-int4-gq-ov'
REVISION = 'a978384bf94364f0962e0d3d2a9e1912d81fe214'

if __name__ == '__main__':
    target = Path(__file__).resolve().parent / 'models' / 'phi35-npu'
    print('Downloading about 2.1 GB from', MODEL_ID, flush=True)
    snapshot_download(MODEL_ID, revision=REVISION, local_dir=str(target),
                      allow_patterns=['*.xml', '*.bin', '*.json', '*.txt', 'README.md', 'LICENSE*'])
    print('NPU model folder:', target, flush=True)
