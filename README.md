# Elden Death Counter

An automatic death counter for Elden Ring, displayed live in OBS or
Streamlabs. Two numbers on screen: your all-time total, and your deaths on
the current boss, which you reset with a keypress once you finally beat it.

Detection works by reading the text on screen. No memory reading, no hooks
into the game process, nothing that could interest anti-cheat.

## Install

**Without Python.** Download `elden-counter.exe` from
[Releases](../../releases). It ships with its own Tesseract engine and
language data for English, French, German, Spanish, Italian, Portuguese and
Russian, so there is nothing else to install.

**With Python 3.10 or newer:**

```
pip install elden-death-counter
```

This route needs the Tesseract engine separately. On Windows, use the
[UB-Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki) and
tick your game's language. On Linux, `apt install tesseract-ocr
tesseract-ocr-eng`. The engine is looked up on PATH first, then in the usual
install locations, so you do not need to edit PATH yourself.

## Getting started

```
elden-counter setup
elden-counter run --boss "Malenia"
```

Setup asks you to die once and press F8 while the death text is on screen.
It finds the line of text on its own, opens a page in your browser so you
can confirm the box with one click, then reads the text and remembers it.
That is all it needs.

If your game is not in English, pass the language: `--lang fra`, `--lang
deu`, `--lang jpn`. The tool has no text hardcoded anywhere - it learns
yours.

Then add a **browser source** in OBS pointing at `http://127.0.0.1:4747`,
sized 600x300. The background is already transparent. Untick "Shutdown
source when not visible", otherwise the counter stops updating whenever you
switch scenes.

## Hotkeys while streaming

| Key | Effect |
|---|---|
| F9 | Add a death to both counters |
| F10 | Remove one |
| F11 | Reset the boss counter, leaving the total untouched |
| F12 | Boss defeated: the score goes to your history and the counter restarts at zero |

## Commands

```
elden-counter setup            # learn the death text
elden-counter run              # detection and overlay
elden-counter run --manual     # count only with hotkeys
elden-counter diagnose         # watch what the detector reads, live
elden-counter langues          # list the languages available
elden-counter boss "Radagon"   # change the boss on screen
elden-counter history          # past bosses and what they cost you
elden-counter reset            # boss counter back to zero
elden-counter reset --all      # wipe everything, history included
elden-counter --version
```

Add `--monitor 2` to `setup`, `run` and `diagnose` if the game is not on
your primary display.

## Why read the text

The first version matched the shape of a fingerprint learned from several
deaths. It worked, but it had no idea what it was looking at: the edge of
the dark veil, or the map's fast-travel dialog, resembled it closely enough
to trigger a count. Guardrails piled up - consistency across deaths, HUD
exclusion, shape filtering, counter-examples, multiple fingerprints - and
blind spots remained.

Reading the text is specific to meaning. A darkened band reads as nothing.
The map reads as something else. Measured on the same real captures that
defeated the shape matcher: 7 deaths out of 12 read, **zero false positives
across 37 images**, menus and map included. The worst true reading scored
0.85 similarity, the worst false one 0.40.

The deaths that go unread are degraded frames, caught mid-fade or washed out
against a very bright scene. In practice the screen is checked twice a
second for the several seconds the text stays up, so a single successful
read is enough.

Comparison is fuzzy rather than exact, which matters more than it sounds.
A real death in the Consecrated Snowfields once read as `VOUSAVEZRER`
instead of `VOUSAVEZPERI`: three wrong characters, still 0.87 similarity,
comfortably counted.

## Tuning

`--similarity` sets the match threshold, 0.60 by default. Raise it if
another screen triggers a count, lower it if deaths slip through. There is
room on both sides.

`elden-counter diagnose` prints every read as it happens. It is the first
place to look when something misbehaves.

## Known rough edges

Language data is copied on first run into a folder next to your settings.
`elden-counter langues` prints the exact path. To add a language, drop the
matching `.traineddata` file from
[tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) in there;
it persists between runs, unlike the copy bundled inside the executable.

Tesseract cannot open paths containing accented characters. If your Windows
username has one, the tool picks a neutral folder automatically, and tells
you plainly if it cannot.

On Windows, global hotkeys sometimes need the terminal running as
administrator.

On console through a capture card, run setup with the preview window in the
exact position it will keep during the stream.

## License

MIT.
