# Translating svgseg

The interface is translated with Qt's own tooling. You do not need to know Python:
translations live in `.ts` files that you edit in a graphical tool.

English is the source language. Its strings are the ones written in the code, so
there is no `svgseg_en.ts`.

## What you need

```bash
pip install "svgseg[gui]"
```

That brings in `pyside6-linguist`, `pyside6-lupdate` and `pyside6-lrelease`.

## Improving an existing translation

Spanish lives in `svgseg/gui/translations/svgseg_es.ts`.

```bash
pyside6-linguist svgseg/gui/translations/svgseg_es.ts   # edit
pyside6-lrelease svgseg/gui/translations/svgseg_es.ts   # compile to .qm
```

Commit **both** the `.ts` and the `.qm`. The wheel ships the compiled `.qm`, so a
`.ts` change alone would not reach users.

Check your work by launching the app and picking your language from the
**Language** menu. Switching applies immediately, no restart.

## Adding a new language

Use the two-letter ISO 639-1 code, for example `fr` for French:

```bash
pyside6-lupdate svgseg/gui/main_window.py svgseg/gui/preview.py svgseg/gui/app.py \
    -source-language en_US -target-language fr_FR \
    -ts svgseg/gui/translations/svgseg_fr.ts

pyside6-linguist svgseg/gui/translations/svgseg_fr.ts
pyside6-lrelease svgseg/gui/translations/svgseg_fr.ts
```

Then add the language name to `LANGUAGE_NAMES` in `svgseg/gui/i18n.py`, written in
that language itself:

```python
LANGUAGE_NAMES = {
    "en": "English",
    "es": "Espanol",
    "fr": "Francais",
}
```

The menu picks up any language with a compiled `.qm` present, so nothing else
needs touching.

## Refreshing after the code changes

When new strings are added to the interface, run `lupdate` again on every
catalogue. It preserves existing translations and marks the new strings as
unfinished:

```bash
for ts in svgseg/gui/translations/svgseg_*.ts; do
    pyside6-lupdate svgseg/gui/main_window.py svgseg/gui/preview.py svgseg/gui/app.py \
        -ts "$ts"
done
```

## Two things the tests enforce

`pytest tests/test_gui_i18n.py` fails if either goes wrong:

1. **No untranslated or unfinished strings.** A half-translated catalogue shows a
   mix of languages, which reads worse than plain English.
2. **Placeholders must survive.** `{pieces}`, `{width}` and friends are filled in
   at runtime; dropping or renaming one raises an error in front of the user. Keep
   them exactly as they appear in the source, though you may reorder them freely.

## What not to translate

Qt's own dialogs, such as the file picker, come from Qt's translations rather than
from this project, and are loaded automatically for your language. If one shows up
in English, that is upstream in Qt, not here.
