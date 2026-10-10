# Intel NPU setup

The 0.4.0b Beta offers **Ollama** and **Intel NPU (OpenVINO)** as separate local engines. The NPU backend explicitly compiles for `NPU`; it does not silently fall back to CPU or GPU.

## This computer

Verified on an Intel Core Ultra 9 275HX with Intel AI Boost. OpenVINO 2026.4.1 detected the NPU, ran a tensor inference test on it, and generated `Hello!` using Phi-3.5 Mini. The model is `OpenVINO/Phi-3.5-mini-instruct-int4-gq-ov`, pinned to revision `a978384bf94364f0962e0d3d2a9e1912d81fe214`.

## Automatic setup

On Windows you can double-click `SETUP_NPU.cmd`; it invokes the setup script
with a one-time execution-policy bypass and leaves your saved policy unchanged.

From PowerShell in the alpha folder:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\SETUP_NPU.ps1
```

This creates `.npu-venv`, installs dependencies, downloads about 2.1 GB of model data, and runs an actual NPU generation test. An installed Intel NPU driver and internet access for downloads are required. Downloaded model data is not executed as Python code. Observations are not sent as part of setup.

## Use the AI assistant

1. Run `RUN_NPU.cmd`.
2. Open **AI Assistant** in the Workspace sidebar.
3. Choose **Intel NPU (OpenVINO)**.
4. Use the default `models\phi35-npu` folder, then click **Enable / verify**.
5. Wait for **Ready on Intel NPU**, then analyze observations or ask a question.

First model loading/compilation may take several minutes. The alpha uses a 2048-token prompt limit and up to 256 output tokens. Start a new chat or shorten observations if the context limit is reached. Responses are displayed when generation completes rather than token by token.

## Manual setup

```powershell
py -3.12 -m venv .npu-venv
.\.npu-venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-npu.txt
.\.npu-venv\Scripts\python.exe download_npu_model.py
.\.npu-venv\Scripts\python.exe marauder_npu.py --model models\phi35-npu
.\.npu-venv\Scripts\python.exe marauder_workspace.py
```

Ollama models are not OpenVINO NPU models. Choose Ollama if you want to keep using your existing model. The backend choices do not combine NPU and GPU processing for the same request. A detected NPU alone does not guarantee that every model or driver combination will work.

Upstream compatibility and model preparation: [OpenVINO GenAI on NPU](https://docs.openvino.ai/2026/openvino-workflow-generative/inference-with-genai/inference-with-genai-on-npu.html).

## Beta limitations

Earlier hardware smoke tests passed, but the latest NPU conversational retest returned ZE_RESULT_ERROR_DEVICE_LOST. NPU response quality and concurrent Hybrid execution are not yet validated for this beta. Restart Windows and check the Intel NPU driver if it reports a lost device. Use Ollama while diagnosing the NPU.
