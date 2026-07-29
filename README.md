# Clipweave

![Clipweave banner](assets/clipweave-app-banner.png)

Clipweave assembles a folder of short videos or images into one coherent montage. It filters by orientation and size, skips obvious duplicates, orders clips by visual continuity, and writes a browser/player-friendly H.264 MP4.

## Requirements

- Python 3.10+
- FFmpeg and FFprobe in `PATH`
- Python packages:

```powershell
python -m pip install -r requirements.txt
```

The desktop UI uses `PySide6`, which is included in `requirements.txt`.

For a full local setup:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
```

## Project Layout

```text
clipweave.py          CLI entry point
clipweave/cli.py      argument parsing
clipweave/pipeline.py orchestration and manifest writing
clipweave/analysis.py frame sampling and visual vectors
clipweave/selection.py filtering, duplicate removal, ordering
clipweave/render.py   FFmpeg normalization, fades, concatenation
clipweave/media.py    FFprobe, frame reads, process helpers
clipweave/gui.py      PySide desktop UI entrypoint
clipweave/gui_panels.py desktop UI path/options panels
clipweave/gui_widgets.py shared desktop UI widgets and sizing
clipweave/gui_worker.py desktop UI background build worker
clipweave/gui_assets.py desktop UI asset path resolution
assets/               README banner and app icon
tests/                unit tests for selection, manifest, render, CLI, and GUI wiring
```

## Basic Usage

```powershell
python clipweave.py "C:\montage\clips"
```

By default this creates:

```text
<input folder>\clipweave_videos_vertical.mp4
<input folder>\clipweave_videos_vertical.manifest.json
```

Intermediate normalized clips are created in a temporary directory and deleted automatically.

## Download Windows Build

The latest Windows binaries are published on every `main` update:

https://github.com/mrolegb/clipweave/releases/latest

Download `clipweave-windows.zip` from the release assets. It contains `clipweave.exe`, `clipweave-gui.exe`, and the README.

## Quick Start With Make

Linux/macOS:

```bash
make install
make run INPUT=/path/to/clips
make slideshow INPUT=/path/to/photos IMAGE_DURATION=3
make mixed INPUT=/path/to/media
```

Windows with Visual Studio Build Tools `nmake`:

```cmd
nmake /f Makefile.win install
nmake /f Makefile.win run INPUT=D:\path\to\clips
nmake /f Makefile.win slideshow INPUT=D:\path\to\photos
```

Windows with GNU Make:

```cmd
mingw32-make -f Makefile.windows install
mingw32-make -f Makefile.windows run INPUT=C:/path/to/clips
```

All make targets expect `ffmpeg` and `ffprobe` to already be available in `PATH`.
`make check` and the Windows `check` targets run Python compilation plus the unit test suite.

## Local Only

Clipweave runs locally. It does not call external APIs or upload media. The only external programs it expects at runtime are local `ffmpeg` and `ffprobe` binaries.

## Desktop UI

The command line tool remains the primary interface, but Clipweave also includes a small local desktop UI:

```powershell
python clipweave-gui.py
```

The UI supports the same core options as the CLI: media mode, orientation, audio, target filtering, smart editing, duration limits, ordering, CRF/preset, input folder, target file, and output path. The form uses two option columns with short field explanations, checkboxes for binary options, and disables controls that do not apply to the selected media type. Builds run in a background thread and print the final manifest into the log panel.

To package the GUI as a local app, install PyInstaller and build per platform:

```powershell
python -m pip install pyinstaller
pyinstaller --onefile --windowed --add-data "assets;assets" clipweave-gui.py
```

For a CLI binary:

```powershell
pyinstaller --onefile clipweave.py
```

FFmpeg is not bundled yet; installed binaries still expect `ffmpeg` and `ffprobe` in `PATH`.
On Linux/macOS, use `--add-data "assets:assets"` instead.

## Testing

Run the test suite locally with:

```powershell
python -m unittest discover -v
```

GitHub Actions also runs the same compile and unit test checks on every push and pull request.

When `main` is updated, GitHub Actions builds Windows CLI and GUI binaries and publishes them as the `clipweave-windows` workflow artifact.

The tests avoid real FFmpeg work and cover:

- option parsing and default output behavior;
- orientation, size, duplicate, target, smart editing, ordering, and duration selection logic;
- fade duration decisions and manifest serialization;
- media discovery behavior with mocked readers;
- GUI field wiring, image-mode audio behavior, startup status, and asset resolution.

## Video Montage

Use the default `--media videos` mode to build a montage from video files:

```powershell
python clipweave.py "D:\clips" `
  --media videos `
  --orientation vertical `
  --audio remove
```

Supported video extensions: `.mp4`, `.mov`, `.mkv`, `.webm`, `.avi`, `.m4v`.

## Image Slideshow

Use `--media images` to build a slideshow from still images. Each image becomes a fixed-duration video segment.

```powershell
python clipweave.py "D:\photos" `
  --media images `
  --orientation vertical `
  --image-duration 3
```

`--image-duration` controls how long each photo stays on screen, in seconds. The default is `3`.

Supported image extensions: `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`.

## Mixed Media

Use `--media mixed` to combine videos and still images in one output:

```powershell
python clipweave.py "D:\media" `
  --media mixed `
  --orientation vertical `
  --image-duration 2.5 `
  --audio remove
```

Images are treated like clips for duplicate detection, target filtering, ordering, and fade transitions.

## Options

```powershell
python clipweave.py "D:\clips" `
  --orientation vertical `
  --media videos `
  --target "D:\clips\reference.jpg" `
  --audio remove `
  --max-duration 600 `
  --transition fade `
  --output "D:\clips\final.mp4"
```

Important parameters:

- `--orientation vertical|horizontal|any`  
  Chooses which clips are eligible. The final video uses the most common exact resolution among matching clips, so black bars are avoided.

- `--media videos|images|mixed`  
  `videos` is the default. Use `images` to build a slideshow, or `mixed` to combine videos and still images.

- `--image-duration SECONDS`  
  Duration for each still image. Default is `3`.

- `--target PATH` and `--target-threshold FLOAT`  
  Use a reference image or video to reject media that is visually too different from the target. The target only filters the selection; it is not forced to be the first item. Default threshold is `0.35`.

- `--audio remove|keep`  
  `remove` is the default. Fade transitions are only used when audio is removed; with audio kept, clips are joined with hard cuts to avoid audio artifacts.

- `--max-duration SECONDS`  
  Upper limit for selected source material. Whole clips are used; clips are not trimmed to fit the limit.

- `--output PATH`  
  Output path. Default is the input folder.

- `--transition fade|cut`  
  `fade` uses shorter fades when adjacent frames are visually similar.

- `--duplicate-threshold FLOAT`  
  Default `0.965`. Lower values remove more near-duplicates; higher values keep more clips.

- `--smart-editing`
  Samples each video across its timeline and trims or skips clips whose frames are mostly already represented by earlier selected clips. This keeps more of the final montage focused on new visual material.

- `--smart-sample-rate FLOAT`, `--smart-threshold FLOAT`, `--smart-max-known-ratio FLOAT`, and `--smart-min-segment-duration FLOAT`
  Tune smart editing. Defaults are `1.0` frame/sec, `0.94` similarity, `0.55` maximum already-known frame ratio, and `2.0` seconds minimum salvaged segment length.

- `--no-smart-reorder-segments`
  By default, smart editing runs a second visual ordering pass after segment trimming. This flag keeps salvaged segments in the first-pass clip order.

- `--no-smart-dedupe-segments`
  By default, smart editing runs a second visual duplicate pass after segment trimming. This flag keeps all salvaged segments.

- `--order visual|name|duration`
  `visual` orders clips by transition similarity using boundary frames plus short sampled frame sequences. Trimmed segments from one source stay in source-time order.

- `--crf N` and `--preset NAME`  
  Encoding quality controls. Default is `--crf 16 --preset slow`, which favors quality over speed.

- `--work-dir PATH` and `--keep-work`  
  Use these only for debugging. Normal runs delete intermediates.

## Selection Rules

Clipweave reads each candidate video or image and samples visual vectors. For videos it samples the start, middle, and end; for images the same still frame is used throughout. It uses those vectors to:

- remove exact file duplicates;
- remove strong visual duplicates;
- prefer longer Grok-extension clips over shorter 10/20 second variants when they look like the same sequence;
- optionally trim repeated clips to novel segments, or skip them when no useful segment remains, with `--smart-editing`;
- order the selected clips by visual continuity while preserving source-time order inside trimmed segment groups;
- shorten fade duration when the outgoing and incoming frames are already similar;
- optionally reject media below `--target-threshold` similarity to a target image/video.

It does not crop clips or choose sub-ranges inside clips. Every selected clip is used from start to finish.

For image slideshows, each selected image is converted into a still video segment using `--image-duration`.

## Output

The output is H.264 MP4 with `yuv420p`, which should open in normal players, browsers, and editors. A JSON manifest is written next to the final video with selected clips, durations, dimensions, and transition lengths.
