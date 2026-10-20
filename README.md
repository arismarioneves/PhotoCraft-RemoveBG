# PhotoCraft-RemoveBG

AI background removal for [PhotoCraft](https://github.com/storytold/photocraft) on Windows.
Select a layer, choose **Filter › Plug-ins › Remove Background (AI)**, and a few seconds later the
layer has a mask that hides the background. It runs entirely on your computer.

> **A stop-gap.** PhotoCraft's own *Remove Background* uses a classical algorithm that struggles
> with busy backgrounds, and native AI background removal is being designed in
> [storytold/photocraft#4098](https://github.com/storytold/photocraft/issues/4098). This project
> fills the gap until then and will be retired once PhotoCraft ships it. A side-by-side comparison
> is in [this comment](https://github.com/storytold/photocraft/issues/2788#issuecomment-6295656662).

## What you get

- **Filter › Plug-ins › Remove Background (AI)** in PhotoCraft. The result is a layer mask on the
  active layer: no pixels are deleted, and you can refine the edge by painting on the mask or with
  Select and Mask.
- **One undo step.** Ctrl+Z restores the layer as it was.
- **Send to › Remove background** in Windows Explorer: saves a transparent PNG of each image in a
  `cutouts` folder next to it, without opening PhotoCraft.
- **Private and offline.** After installation nothing is downloaded and no image leaves your
  computer.

## Requirements

- Windows 10 or 11, 64-bit.
- PhotoCraft 0.9.0 or 0.10.0 (the versions this was tested with) in `C:\Program Files\PhotoCraft`.
- 8 GB of RAM: one cut-out uses about 1.3 GB.
- Python 3.11 to 3.14, 64-bit. If none is found, the installer offers to install Python 3.12 with
  winget. An older Python already on the computer is left alone.
- Internet during installation (about 35 MB of Python packages and a 170 MB model).

## Install

1. Download this repository (Code › Download ZIP) and extract it anywhere.
2. Double-click `INSTALL.bat`. No administrator rights are needed.

The installer creates a private Python environment in `%LOCALAPPDATA%\PhotoCraft-RemoveBG`,
downloads the model and adds three shortcuts: **PhotoCraft (Remove Background)** on the desktop and
in the Start menu, and **Remove background** in *Send to*. Run it again to update.

## Use

### In PhotoCraft

1. Open PhotoCraft with the **PhotoCraft (Remove Background)** shortcut. The plug-in only works in
   a PhotoCraft opened this way.
2. Select the layer.
3. **Filter › Plug-ins › Remove Background (AI)**.

A translucent blue layer covers the image while it works. The first click after opening PhotoCraft
loads the model and takes a few seconds longer. After that, a 2-megapixel photo takes about 8–10
seconds on a 4-core desktop CPU (about 3 of them in the model, the rest in PhotoCraft), and longer
while other programs keep the CPU busy.

### In Windows Explorer

Right-click images or a folder › **Send to › Remove background** (on Windows 11: *Show more
options* › *Send to*). Folders are scanned recursively; the PNGs go into a `cutouts` folder next to
each original.

## Models

| Model | License | Notes |
|---|---|---|
| ISNet (default) | Apache-2.0 | Free for any use. |
| BRIA RMBG-1.4 | [bria-rmbg-1.4](https://huggingface.co/briaai/RMBG-1.4) | **Non-commercial use only.** In our tests it was cleaner on portraits and on people carrying objects. |

To use RMBG-1.4, run `install.ps1 -Model rmbg-1.4` from the extracted folder (in PowerShell:
`powershell -ExecutionPolicy Bypass -File .\install.ps1 -Model rmbg-1.4`). You will be asked to
type `I ACCEPT` after reading the license summary. `install.ps1 -Model isnet` switches back.

## Troubleshooting

- **The menu item is missing.** PhotoCraft was opened with its normal icon (or by double-clicking
  a file). Close it and open it with the **PhotoCraft (Remove Background)** shortcut.
- **Nothing happens / an error message appears.** Details are in
  `%LOCALAPPDATA%\PhotoCraft-RemoveBG\helper.log`. Include that file when reporting a problem.
- **"Not enough memory".** Close other programs and try again.
- **"Port … is in use by another program".** Change `controlPort` (and `lockPort`) in
  `%LOCALAPPDATA%\PhotoCraft-RemoveBG\config.json`.
- **"This PhotoCraft version is not supported".** A newer PhotoCraft changed something this
  add-on depends on; check for an update here.
- Keep the PhotoCraft window open while it works; behaviour with a minimized window was not tested.

## Known limitations

- One layer per click: the active layer. Text, shape and adjustment layers are refused by
  PhotoCraft itself (plug-in filters need a pixel layer). Smart Objects work.
- RGB and Grayscale documents only (convert CMYK or Lab with Image › Mode first).
- The model works at 1024 × 1024, so hair and fine edges on very large photos may need touching up.
- Redoing a *Remove Background (AI)* step (Ctrl+Shift+Z) computes it again.
- The shortcut opens a separate PhotoCraft window; files opened by double-clicking in Explorer go to
  a normal PhotoCraft without the plug-in.

## How it works

PhotoCraft plug-ins are sandboxed WebAssembly filters with no access to files, processes or the
network, so a model cannot run inside one. The plug-in here does nothing to the pixels: running it
only adds a *Remove Background (AI)* step to the history. A small Python helper, started by the
shortcut, opens PhotoCraft with its [control channel](https://github.com/storytold/photocraft/blob/main/docs/control-protocol.md)
(loopback only, token-protected), watches for that step, exports the layer, runs the ONNX model with
onnxruntime on the CPU and sends the mask back, grouped into a single undo step. The helper exits
when PhotoCraft closes.

## Uninstall

Double-click `UNINSTALL.bat`. It removes the shortcuts, the Python environment, the model and the
settings. PhotoCraft itself is not changed.

## Development

```powershell
python3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
```

Tests that need PhotoCraft run when `PHOTOCRAFT_EXE` and `PHOTOCRAFT_CLI` point to
`photocraft.exe` and `photocraft-cli.exe` (the portable zip from the PhotoCraft releases works);
otherwise they are skipped. Tests marked `slow` install into a temporary folder and need internet;
tests marked `model` download the ISNet model once into `.cache/models`. For an end-to-end check
against a real PhotoCraft window:

```powershell
.venv\Scripts\python scripts\smoke.py --exe <path\to\photocraft.exe>
```

## License

MIT, see [LICENSE](LICENSE). Third-party components and model licenses:
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
