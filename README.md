# Elden Death Counter

Automatic death counter for Elden Ring, shown live in OBS or Streamlabs.
Two numbers on screen: your all-time total, and your deaths on the current
boss, which you reset once you beat it.

Detection reads the text on screen. No memory reading, no hooks into the
game process.

## Install

Download `elden-counter.exe` from [Releases](../../releases). It ships with
Tesseract and language data for English, French, German, Spanish, Italian,
Portuguese and Russian.

With Python 3.10+: `pip install elden-death-counter`, plus the Tesseract
engine ([Windows installer](https://github.com/UB-Mannheim/tesseract/wiki),
or `apt install tesseract-ocr` on Linux).

## Use

```
elden-counter setup
elden-counter run --boss "Malenia"
```

Setup asks you to die once and press F8 while the death text is up. It finds
the text, opens a browser page so you can confirm the box, then reads the
text and remembers it.

Add a browser source in OBS at `http://127.0.0.1:4747`, 600x300. Untick
"Shutdown source when not visible".

Not playing in English? Pass `--lang fra`, `--lang deu`, `--lang jpn`.
Nothing is hardcoded; it learns your text.

## Hotkeys

| Key | Effect |
|---|---|
| F9 | Add a death |
| F10 | Remove one |
| F11 | Reset the boss counter, total untouched |
| F12 | Boss beaten: archive the score, restart at zero |

## Commands

```
elden-counter setup            learn the death text
elden-counter run              detection and overlay
elden-counter run --manual     hotkeys only
elden-counter diagnose         watch what it reads, live
elden-counter languages        list available languages
elden-counter boss "Radagon"   change the boss shown
elden-counter history          past bosses and their cost
elden-counter reset            boss counter to zero
elden-counter reset --all      wipe everything
```

Add `--monitor 2` to `setup`, `run` and `diagnose` if the game is not on
your primary display.

## FAQ

**Can this get me banned?**
It reads pixels from your screen. It never touches the game process or its
memory, which is what anti-cheat looks for.

**Setup says no readable text.**
Check `zone-lue.png` next to your settings: that is the exact image handed to
the OCR. If the text looks sharp there, your box is probably too wide. Keep
it tight on the letters.

**Nothing counts during a fight.**
Run `elden-counter run --debug` and watch the similarity scores. Near the
threshold means lowering `--similarity` to 0.5 will do. Near zero means the
text is not being read at all, usually because the box is wrong or the
language is not the game's.

**A death was missed.**
Expected occasionally. Reading fails on very bright scenes or busy
backgrounds where the text washes out. Press F9 to correct it. The number is
on screen, so nothing drifts silently.

**Something that is not a death got counted.**
Note what was on screen and raise `--similarity`. Measured worst false
positive was 0.40, so there is room above the 0.60 default.

**Which language code do I use?**
The Tesseract three-letter code for your game's language: `eng`, `fra`,
`deu`, `spa`, `ita`, `por`, `rus`, `jpn`. `elden-counter languages` lists
what you have.

**My language is missing.**
Download the matching `.traineddata` from
[tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) and drop it
in the folder printed by `elden-counter languages`. It persists between runs.

**Tesseract errors about an illegal byte sequence.**
It cannot open paths with accented characters, which happens when your
Windows username has one. The tool picks a neutral folder automatically and
says so if it cannot.

**Hotkeys do nothing while the game is focused.**
Run the terminal as administrator. Global keyboard hooks need it on some
Windows setups.

**The overlay froze after I switched scenes.**
Untick "Shutdown source when not visible" on the browser source.

**Does it work on console?**
Through a capture card, yes. Run setup with the preview window exactly where
it will stay during the stream.

**Can I move the counter or restyle it?**
It is a plain HTML page in `eldencounter/overlay/`. Edit it.

## How it works

The text is read with Tesseract inside a zone you confirm once, then
compared to the reference with fuzzy matching. Fuzzy matters: a real death in
the Consecrated Snowfields read as `VOUSAVEZRER` instead of `VOUSAVEZPERI`
and still scored 0.87.

An earlier version matched the shape of a learned fingerprint instead. It had
no idea what it was looking at, so the edge of the dark veil and the map's
fast-travel dialog both triggered counts. Reading the text is specific to
meaning: a darkened band reads as nothing, the map reads as something else.

Measured on real captures: 7 deaths out of 12 read, zero false positives
across 37 images including menus and map. Worst true reading 0.85, worst
false one 0.40. Unread deaths are degraded frames, caught mid-fade or washed
out. The screen is checked twice a second while the text is up, so one
successful read is enough.

## License

MIT.
