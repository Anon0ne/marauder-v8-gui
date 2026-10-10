# Getting help

For reproducible bugs, use the repository's bug report form. For suggestions, use the feature request form. Security problems go through [SECURITY.md](SECURITY.md); community conduct reports go through [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Connection problems

1. Confirm the board appears as a COM port on Windows or a serial device on Linux.
2. Select the correct port and firmware baud rate (normally 115200).
3. Close other serial monitors, firmware tools, and extra GUI instances.
4. Check the GUI's serial console and event log for the actual connection error.
5. Verify the USB cable supports data and the board's serial driver is installed. On Linux, verify device permissions.

## Windows build problems

Use Python 3.10–3.13. Report the first error, rather than only the final `BUILD FAILED` message. Installer instructions are in `WINDOWS_INSTALL.txt`; manual setup is available if automated setup fails.

## AI and NPU problems

Ollama and OpenVINO NPU are separate engines and use different model formats. See [NPU_SETUP.md](NPU_SETUP.md). Include the model, runtime version, Intel NPU driver version, and reported execution device. NPU compilation can take time on first load. A detected device alone does not prove a particular model can run on it.

## Useful report details

Include application version, OS, Python version if applicable, board/firmware, installation method, expected behavior, actual behavior, and sanitized logs. Never post passwords, private captures, or identifying network data. Support is provided as time allows.
