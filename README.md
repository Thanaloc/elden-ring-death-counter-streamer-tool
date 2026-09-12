# Elden Death Counter

Automatic death counter for Elden Ring, shown live in OBS or Streamlabs.
Two numbers on screen: your all-time total, and your deaths on the current
boss, which you reset once you beat it.

Detection reads the text on screen. No memory reading, no hooks into the
game process.

## Install

Download `elden-counter-windows.zip` from [Releases](../../releases), unzip
it anywhere, and run `elden-counter.exe` from inside the folder. Keep the
folder together: the exe needs the files next to it.

It ships with Tesseract and English. Other languages are downloaded on first
setup, which takes a second and about a megabyte.

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
elden-counter languages --add fra   download a language
elden-counter boss "Radagon"   change the boss shown
elden-counter total 1481       set the lifetime total
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
Press F9 to correct it. The number is on screen, so nothing drifts silently.

F9 also saves what the detector was looking at over the previous twelve
seconds, into a `misses` folder next to your settings, along with every
reading and score. Those frames are the only way to work out why a death did
not register. Turn it off with `--no-record-misses`.

Reading fails on very bright scenes or busy backgrounds where the text
washes out.

**Something that is not a death got counted.**
Note what was on screen and raise `--similarity`. Measured worst false
positive was 0.40, so there is room above the 0.60 default.

**Windows Defender flagged the download.**
False positive. The build is unsigned, and an unsigned executable nobody has
downloaded before starts with no reputation at all, which is enough on its
own. On VirusTotal, 2 engines out of 65 react, both with generic
machine-learning labels rather than a named malware, while Kaspersky, ESET,
BitDefender and Microsoft report nothing. You can check any release yourself
by uploading it to [VirusTotal](https://www.virustotal.com).

If you would rather not run an unsigned binary, `pip install
elden-death-counter` gets you the same tool from source.

**Which language code do I use?**
The Tesseract three-letter code for your game's language: `eng`, `fra`,
`deu`, `spa`, `ita`, `por`, `rus`, `jpn`. `elden-counter languages` lists
what you have.

**My language is missing.**
Setup downloads it for you. To do it ahead of time:
`elden-counter languages --add fra`. Files land in the folder printed by
`elden-counter languages` and persist between runs. Offline? Grab the
`.traineddata` from
[tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) and drop it
in there by hand.

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

**I stopped with Ctrl+C and came back. Is my progress kept?**
Yes. Relaunching with `--boss "Malenia"` keeps that boss's count, because
naming the boss you are already on is not the same as switching. Switching to
a different boss starts at zero. To deliberately restart a boss you are
already on, add `--restart`.

**I already have deaths before installing this.**
`elden-counter total 1481` sets the lifetime total. Your save file shows the
real number in the stats screen. To start the boss counter partway through
too: `elden-counter boss "Malenia" --count 47`.

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
