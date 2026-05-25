# ipod-drop

Download songs from YouTube and YouTube Music as iTunes-compatible M4A files, ready to sync to an iPod touch via Finder.

Built specifically for **iPod touch running iOS 9.3.5** — AAC-LC encoding, embedded cover art, and proper iTunes metadata atoms so everything shows up correctly in the Music app.

## Features

- Downloads single videos or full playlists
- Embeds cover art (thumbnail → JPEG → iTunes `covr` atom)
- Full metadata: title, artist, album, track number
- Smart caching — skips already-downloaded tracks on re-runs
- Auto-retry on failure (failed tracks not cached)
- Best AAC encoder auto-detected: Apple AudioToolbox → FDK → native fallback
- Cookie support for YouTube Premium and private playlists

## Requirements

```bash
pip install yt-dlp tqdm
brew install ffmpeg   # macOS
```

## Usage

**Interactive:**
```bash
python ipod_drop.py
```

**With a URL directly:**
```bash
python ipod_drop.py --url "https://youtube.com/playlist?list=..."
python ipod_drop.py --url "https://youtu.be/dQw4w9WgXcQ"
```

**All options:**
```
--url URL        YouTube playlist or video URL
--name NAME      Album / folder name override
--out DIR        Output directory (default: current dir)
--browser        Browser for cookies: safari, chrome, firefox, edge, brave, opera
--no-bell        Suppress the terminal bell on finish
```

## Syncing to iPod touch

1. Connect your iPod touch via USB
2. Open **Finder** → select your iPod in the sidebar
3. Click the **Music** tab
4. Drag the output folder into the music list
5. Click **Sync**

## Output

Each track is saved as:
```
Album Name/
  01 - Song Title.m4a
  02 - Song Title.m4a
  ...
  ipod_drop_cache.json   ← resume cache, safe to delete
```

## Notes

- AAC-LC profile is used (not HE-AAC v2) for broadest compatibility with old iOS hardware
- Cover art is scaled to 600 px max before embedding — sharp on Retina, smaller file size
- `moov` atom is placed at the front of each file (`faststart`) for instant playback
- The cache is keyed by YouTube URL, so re-running the script on the same output folder safely skips completed tracks
