#!/usr/bin/env python3

"""
ipod-drop
---------
Downloads songs from YouTube / YouTube Music as iTunes-compatible M4A files
with embedded cover art and metadata, ready to drag into Finder for iPod Touch
(iOS 9.3.5) sync.

Usage:
  python ipod_drop.py                        # interactive
  python ipod_drop.py --url <URL>            # single video or playlist
  python ipod_drop.py --url <URL> --name "My Album" --out ~/Music/iPod

Dependencies:
  pip install yt-dlp tqdm
  brew install ffmpeg   (macOS)
"""

import os
import re
import sys
import json
import shutil
import subprocess
import tempfile
import time
import argparse
from pathlib import Path

import yt_dlp
from tqdm import tqdm

# ─────────────────────────────────────────────────────────────────
#  FFMPEG / FFPROBE DETECTION
# ─────────────────────────────────────────────────────────────────

def _find_ffmpeg():
    for candidate in [shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError(
        "FFmpeg not found.\n"
        "  macOS:   brew install ffmpeg\n"
        "  Linux:   sudo apt install ffmpeg\n"
        "  Windows: https://ffmpeg.org/download.html"
    )

FFMPEG  = _find_ffmpeg()
FFPROBE = shutil.which("ffprobe") or FFMPEG.replace("ffmpeg", "ffprobe")

# ─────────────────────────────────────────────────────────────────
#  AAC ENCODER DETECTION
#  Priority: Apple AudioToolbox (hw) → libfdk_aac → native aac
#  All three produce perfectly iPod-compatible AAC inside M4A.
# ─────────────────────────────────────────────────────────────────

def _detect_aac_encoder():
    candidates = [
        ("aac_at",     True,  "Apple AudioToolbox (hardware)"),
        ("libfdk_aac", False, "Fraunhofer FDK AAC"),
        ("aac",        False, "FFmpeg native AAC"),
    ]
    try:
        result = subprocess.run(
            [FFMPEG, "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5
        )
        available = result.stdout
    except Exception:
        return "aac", False, "FFmpeg native AAC"

    for name, is_hw, desc in candidates:
        if name not in available:
            continue
        try:
            test = subprocess.run(
                [FFMPEG, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                 "-t", "0.1", "-c:a", name, "-b:a", "128k", "-f", "null", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5
            )
            if test.returncode == 0:
                return name, is_hw, desc
        except Exception:
            continue

    return "aac", False, "FFmpeg native AAC"

# ─────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────

def safe_name(s: str, max_len: int = 120) -> str:
    s = re.sub(r'[\\/:*?"<>|]', "-", s).strip(". ")
    return s[:max_len]

def get_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True
        ).stdout.strip()
        return float(out)
    except Exception:
        return 0.0

class _SilentLogger:
    def debug(self, msg):   pass
    def warning(self, msg): pass
    def error(self, msg):   pass

# ─────────────────────────────────────────────────────────────────
#  COOKIE CONFIGURATION  (module-level, set by main())
# ─────────────────────────────────────────────────────────────────

_BROWSER = None  # e.g. "safari", "chrome", etc.

def _ydl_opts(with_cookies: bool = True) -> dict:
    opts: dict = {"quiet": True, "logger": _SilentLogger(), "no_warnings": True}
    if _BROWSER and with_cookies:
        opts["cookiesfrombrowser"] = (_BROWSER, None, None, None)
    return opts

# ─────────────────────────────────────────────────────────────────
#  PLAYLIST / VIDEO EXPANSION
# ─────────────────────────────────────────────────────────────────

def expand_url(url: str) -> tuple[str, list[dict]]:
    """
    Returns (album_name, tracks) where each track is:
      {"title": str, "artist": str, "url": str}
    """
    opts = {**_ydl_opts(), "extract_flat": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if info.get("_type") == "playlist":
        entries = info.get("entries") or []
        tracks = []
        for e in entries:
            if not e:
                continue
            vid_url = (
                e.get("url")
                or e.get("webpage_url")
                or f"https://www.youtube.com/watch?v={e['id']}"
            )
            tracks.append({"title": e.get("title", ""), "artist": "", "url": vid_url})
        album = info.get("title", "Playlist")
        print(f"  Found {len(tracks)} track(s) in: {album}")
        return album, tracks

    title = info.get("title", "Track")
    return title, [{"title": title, "artist": "", "url": url}]

# ─────────────────────────────────────────────────────────────────
#  FETCH FULL METADATA FOR A SINGLE VIDEO
# ─────────────────────────────────────────────────────────────────

def fetch_metadata(url: str) -> dict:
    with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
        return ydl.extract_info(url, download=False) or {}

# ─────────────────────────────────────────────────────────────────
#  DOWNLOAD BEST AUDIO STREAM
# ─────────────────────────────────────────────────────────────────

def download_audio(url: str, stem: str) -> Path:
    """Download best audio to <stem>.<ext>. Returns the actual file path."""

    def _run(use_cookies: bool):
        opts = {
            **_ydl_opts(with_cookies=use_cookies),
            "format": "bestaudio/best",
            "outtmpl": f"{stem}.%(ext)s",
            "ffmpeg_location": FFMPEG,
            "postprocessors": [],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    try:
        _run(True)
    except Exception:
        if _BROWSER:
            print("    ⚠️  Retrying without cookies...")
            _run(False)
        else:
            raise

    parent = Path(stem).parent
    name   = Path(stem).name
    for f in parent.iterdir():
        if f.stem == name and f.suffix.lower() in {".webm", ".opus", ".m4a", ".mp4", ".ogg", ".aac"}:
            return f

    raise RuntimeError(f"Downloaded audio file not found for: {url}")

# ─────────────────────────────────────────────────────────────────
#  DOWNLOAD THUMBNAIL → JPEG
# ─────────────────────────────────────────────────────────────────

def download_cover(url: str, stem: str) -> Path | None:
    opts = {
        **_ydl_opts(),
        "skip_download": True,
        "writethumbnail": True,
        "outtmpl": f"{stem}.%(ext)s",
        "ffmpeg_location": FFMPEG,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception:
        return None

    for ext in ("jpg", "jpeg", "png", "webp"):
        raw = Path(f"{stem}.{ext}")
        if raw.exists():
            jpg = Path(f"{stem}_cover.jpg")
            # Convert to plain JPEG — iOS 9 is strict about embedded image format
            subprocess.run(
                [FFMPEG, "-y", "-i", str(raw),
                 "-vf", "scale='min(600,iw)':-1",   # cap at 600 px (saves space, still sharp on Retina)
                 "-q:v", "2",                         # high quality JPEG
                 str(jpg)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            raw.unlink(missing_ok=True)
            return jpg if jpg.exists() else None

    return None

# ─────────────────────────────────────────────────────────────────
#  ENCODE TO ITUNES-COMPATIBLE M4A
#
#  iOS 9.3.5 / iPod touch requirements:
#    - Container : MP4 / M4A  (not WebM / Ogg)
#    - Codec     : AAC-LC     (not HE-AAC v2 — old hardware decodes it but
#                              cover art sometimes breaks; LC is safer)
#    - Bitrate   : 256 kbps   (transparent quality, fast seek)
#    - Cover art : attached as video stream with disposition=attached_pic
#                  AND written to the iTunes covr atom via -write_id3v2 isn't
#                  needed; ffmpeg's mov muxer writes covr automatically.
#    - Tags      : title / artist / album / track — iTunes-style atoms
#    - faststart : moov atom at front → playback starts without full download
# ─────────────────────────────────────────────────────────────────

def encode_m4a(
    src: Path,
    out: Path,
    encoder: str,
    title: str,
    artist: str,
    album: str,
    track_num: int,
    total: int,
    cover: Path | None,
) -> None:
    duration = get_duration(src)

    cmd = [FFMPEG, "-y", "-i", str(src)]
    n_inputs = 1

    if cover and cover.exists():
        cmd += ["-i", str(cover)]
        n_inputs = 2

    cmd += [
        "-map", "0:a",
        "-c:a", encoder,
        "-b:a", "256k",
        "-profile:a", "aac_low",   # AAC-LC — broadest compatibility
        "-metadata", f"title={title}",
        "-metadata", f"artist={artist}",
        "-metadata", f"album={album}",
        "-metadata", f"track={track_num}/{total}",
        "-metadata", "comment=ipod-drop",
    ]

    if n_inputs == 2:
        cmd += [
            "-map", "1:v",
            "-c:v", "mjpeg",
            "-disposition:v:0", "attached_pic",
        ]

    cmd += ["-movflags", "+faststart", str(out)]

    pbar = tqdm(
        total=max(int(duration), 1),
        unit="s",
        desc="    Encoding",
        ncols=64,
        leave=False,
    )
    proc = subprocess.Popen(
        cmd + ["-progress", "pipe:1", "-nostats"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    last = 0
    for line in proc.stdout:
        if "out_time_ms=" in line:
            try:
                ms  = int(line.split("=")[1].strip())
                cur = min(ms // 1000, int(duration))
                pbar.update(cur - last)
                last = cur
            except ValueError:
                pass
    proc.wait()
    pbar.close()

    if proc.returncode != 0:
        # Fallback: native aac encoder, no cover art
        fallback = [
            FFMPEG, "-y", "-i", str(src),
            "-map", "0:a", "-c:a", "aac", "-b:a", "256k",
            "-profile:a", "aac_low",
            "-metadata", f"title={title}",
            "-metadata", f"artist={artist}",
            "-metadata", f"album={album}",
            "-metadata", f"track={track_num}/{total}",
            "-movflags", "+faststart", str(out),
        ]
        subprocess.run(fallback, check=True, capture_output=True)

# ─────────────────────────────────────────────────────────────────
#  CACHE  (per-output-folder, keyed by YouTube URL)
# ─────────────────────────────────────────────────────────────────

_CACHE_FILE = "ipod_drop_cache.json"

def _load_cache(folder: Path) -> dict:
    p = folder / _CACHE_FILE
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_cache(folder: Path, cache: dict) -> None:
    (folder / _CACHE_FILE).write_text(
        json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
    )

# ─────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ipod-drop — downloads YouTube/YT Music → iTunes-compatible M4A"
    )
    parser.add_argument("--url",     help="YouTube playlist or video URL")
    parser.add_argument("--name",    help="Album / folder name override")
    parser.add_argument("--out",     help="Output directory (default: current dir)")
    parser.add_argument("--browser", help="Browser for cookies (premium/private)",
                        choices=["safari", "chrome", "firefox", "edge", "brave", "opera"])
    parser.add_argument("--no-bell", action="store_true", help="Suppress terminal bell on finish")
    args = parser.parse_args()

    print("╔══════════════════════════════════════════════╗")
    print("║   🎵  ipod-drop  —  YouTube → M4A           ║")
    print("║   Optimised for iPod touch  iOS 9.3.5        ║")
    print("╚══════════════════════════════════════════════╝")

    # ── Cookie / browser setup ─────────────────────────────────────────────────
    global _BROWSER
    browsers = ["safari", "chrome", "firefox", "edge", "brave", "opera"]

    if args.browser:
        _BROWSER = args.browser
    else:
        print("\n🔐 Use browser cookies? (required for Premium / private content)")
        for i, b in enumerate(browsers, 1):
            print(f"   {i} — {b.capitalize()}")
        print("   0 — No (public videos only)")
        choice = input("Choice [0-6]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(browsers):
            _BROWSER = browsers[int(choice) - 1]

    if _BROWSER:
        print(f"   Using cookies from: {_BROWSER.capitalize()}")
    else:
        print("   No cookies — public videos only")

    # ── Encoder ────────────────────────────────────────────────────────────────
    print("\n🔍 Detecting best AAC encoder...")
    encoder, is_hw, enc_desc = _detect_aac_encoder()
    label = "Hardware" if is_hw else "Software"
    print(f"   {label}: {enc_desc}")

    # ── Source URL ─────────────────────────────────────────────────────────────
    if args.url:
        url = args.url
    else:
        url = input("\nYouTube / YT Music URL (video or playlist): ").strip()
        if not url:
            print("No URL provided. Exiting.")
            sys.exit(1)

    print("\n📋 Fetching info...")
    album_name, tracks = expand_url(url)

    if args.name:
        album_name = args.name
    else:
        override = input(f"\nAlbum / folder name [{album_name}]: ").strip()
        if override:
            album_name = override

    album_name = safe_name(album_name)

    if not tracks:
        print("No tracks found. Exiting.")
        sys.exit(1)

    # ── Output folder ──────────────────────────────────────────────────────────
    base = Path(args.out) if args.out else Path.cwd()
    out_dir = base / album_name
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n📁 Output: {out_dir}")

    # ── Load cache ─────────────────────────────────────────────────────────────
    cache = _load_cache(out_dir)
    if cache:
        print(f"💾 Cache: {len(cache)} track(s) already downloaded")

    # ── Download loop ──────────────────────────────────────────────────────────
    total     = len(tracks)
    succeeded = 0
    skipped   = 0
    t0        = time.time()

    for idx, track in enumerate(tracks, 1):
        track_url = track["url"]
        prefix    = f"  [{idx}/{total}]"
        num_str   = f"{idx:02d}"

        print(f"\n{'─' * 50}")

        # Cache hit — skip without any network call
        if track_url in cache:
            entry    = cache[track_url]
            t_title  = entry["title"]
            t_artist = entry.get("artist", "")
            filename = f"{num_str} - {safe_name(t_title)}.m4a"
            out_m4a  = out_dir / filename

            # Fix filename if track order changed
            cached_file = out_dir / entry["filename"]
            if cached_file.exists() and cached_file != out_m4a:
                cached_file.rename(out_m4a)
                cache[track_url]["filename"] = filename
                _save_cache(out_dir, cache)

            if out_m4a.exists():
                skipped += 1
                print(f"{prefix} ⏭️  {t_title}  (cached)")
                continue

        # Fetch full metadata if title or artist is missing
        t_artist = track.get("artist", "")
        if not track.get("title") or not t_artist:
            print(f"{prefix} Fetching metadata...")
            try:
                info = fetch_metadata(track_url)
                if not track.get("title"):
                    track["title"] = info.get("title", f"Track {idx}")
                if not t_artist:
                    # yt-dlp sets 'artist' for YT Music; fall back to uploader for regular YT
                    t_artist = (
                        info.get("artist")
                        or info.get("creator")
                        or info.get("uploader")
                        or info.get("channel", "")
                    )
            except Exception:
                track["title"] = f"Track {idx}"

        t_title  = track["title"]
        filename = f"{num_str} - {safe_name(t_title)}.m4a"
        out_m4a  = out_dir / filename

        print(f"{prefix} 🎵  {t_title}")
        if t_artist:
            print(f"         Artist : {t_artist}")

        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)

                print("    ⬇️  Downloading audio...")
                raw_audio = download_audio(track_url, str(tmp_path / "audio"))

                print("    🖼️  Downloading cover art...")
                cover = download_cover(track_url, str(tmp_path / "thumb"))
                if not cover:
                    print("    (no cover art found — metadata still embedded)")

                print("    🔧  Encoding M4A...")
                encode_m4a(
                    src=raw_audio,
                    out=out_m4a,
                    encoder=encoder,
                    title=t_title,
                    artist=t_artist,
                    album=album_name,
                    track_num=idx,
                    total=total,
                    cover=cover,
                )

            duration = get_duration(out_m4a)
            size_mb  = out_m4a.stat().st_size / (1024 * 1024)
            print(f"    ✅  Saved: {filename}  ({size_mb:.1f} MB, {int(duration//60)}:{int(duration%60):02d})")

            cache[track_url] = {
                "title":    t_title,
                "artist":   t_artist,
                "filename": filename,
                "duration": duration,
            }
            _save_cache(out_dir, cache)
            succeeded += 1

        except Exception as e:
            print(f"    ❌  Failed: {e}")

    # ── Summary ────────────────────────────────────────────────────────────────
    elapsed  = time.time() - t0
    failed   = total - succeeded - skipped
    mins, sec = divmod(elapsed, 60)

    print(f"\n{'═' * 50}")
    print(f"  Done!  {succeeded} downloaded  |  {skipped} skipped  |  {failed} failed")
    print(f"  Time : {int(mins)}m {sec:.1f}s")
    print(f"  Folder: {out_dir}")
    print(f"{'═' * 50}")

    print("\n📱 To sync to iPod touch (iOS 9.3.5):")
    print("   1. Open Finder → select your iPod in the sidebar")
    print("   2. Click the 'Music' tab")
    print("   3. Drag the output folder into the Finder music list")
    print("   4. Click 'Apply' / 'Sync'")

    if not args.no_bell:
        print("\a", end="", flush=True)
        try:
            subprocess.run(["say", "Downloads complete"], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


if __name__ == "__main__":
    main()
