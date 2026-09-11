# Elden Death Counter

Automatic death counter for Elden Ring, shown live in OBS or Streamlabs.
Two numbers on screen: your all-time total, and your deaths on the current
boss, which you reset once you beat it.

Detection reads the text on screen.

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
elden-counter total 1481       set the lifetime total
elden-counter history          past bosses and their cost
elden-counter reset            boss counter to zero
elden-counter reset --all      wipe everything
```

Add `--monitor _NUMBEROFMONITOR_` to `setup`, `run` and `diagnose` if the game is not on
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

**I already have deaths before installing this.**
`elden-counter total 1481` sets the lifetime total. Your save file shows the
real number in the stats screen. To start the boss counter partway through
too: `elden-counter boss "Malenia" --count 47`.

**Can I move the counter or restyle it?**
It is a plain HTML page in `eldencounter/overlay/`. Edit it.

## Disclaimer    

This counter is not fully precise and 100% fiable. Missed death could happen, don't hesitate to reach out so we can fix it. Otherwise, if one death sometimes doesn't bother you, don't hesitate to use F9.

## License

MIT.
