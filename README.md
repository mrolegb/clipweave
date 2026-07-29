# Clipweave

Clipweave assembles a folder of short videos into one coherent montage. It filters by orientation and size, skips obvious duplicates, orders clips by visual continuity, and writes a browser/player-friendly H.264 MP4.

## Requirements

- Python 3.10+
- FFmpeg and FFprobe in `PATH`
- Python packages:

```powershell
python -m pip install opencv-python numpy
```

## Basic Usage

```powershell
python clipweave.py "D:\stuff\grok-favorites\little"
```

By default this creates:

```text
<input folder>\clipweave_vertical.mp4
<input folder>\clipweave_vertical.manifest.json
```

Intermediate normalized clips are created in a temporary directory and deleted automatically.

## Options

```powershell
python clipweave.py "D:\clips" `
  --orientation vertical `
  --audio remove `
  --max-duration 600 `
  --transition fade `
  --output "D:\clips\final.mp4"
```

Important parameters:

- `--orientation vertical|horizontal|any`  
  Chooses which clips are eligible. The final video uses the most common exact resolution among matching clips, so black bars are avoided.

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

- `--order visual|name|duration`  
  `visual` orders clips by similarity between the end of one clip and the start of the next.

- `--crf N` and `--preset NAME`  
  Encoding quality controls. Default is `--crf 16 --preset slow`, which favors quality over speed.

- `--work-dir PATH` and `--keep-work`  
  Use these only for debugging. Normal runs delete intermediates.

## Selection Rules

Clipweave reads each candidate video at the start, middle, and end. It uses those frames to:

- remove exact file duplicates;
- remove strong visual duplicates;
- prefer longer Grok-extension clips over shorter 10/20 second variants when they look like the same sequence;
- order the selected clips by visual continuity;
- shorten fade duration when the outgoing and incoming frames are already similar.

It does not crop clips or choose sub-ranges inside clips. Every selected clip is used from start to finish.

## Output

The output is H.264 MP4 with `yuv420p`, which should open in normal players, browsers, and editors. A JSON manifest is written next to the final video with selected clips, durations, dimensions, and transition lengths.
