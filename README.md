# ipod-drop

> **This repository is archived.** All features have been merged into [streamlist](https://github.com/AdinathChaudhari/streamlist), which works for Apple Music, modern iOS, and iPod sync via Finder. Use that instead.

---

ipod-drop was a downloader for YouTube / YouTube Music built specifically for **iPod touch running iOS 9.3.5** — it used mutagen to write iTunes-compatible `covr` atoms because ffmpeg's iPod muxer produces a malformed tag that iOS 9 ignores.

The following features were ported to streamlist before archiving:

- Square cover art crop (600×600 sRGB JPEG via Pillow)
- `album_artist` tag for Apple Music grouping
- `creator` field in the artist resolution fallback chain

streamlist proved to work perfectly with Apple Music sync, including correct cover art display — making a separate iPod-specific tool unnecessary.
