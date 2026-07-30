## Windows

`@EXE@` is portable: download it and run it. Nothing to install, no Python and no
separate potrace. Windows 10 or 11, 64-bit.

It is not code signed, so SmartScreen warns the first time. Choose **More info**
then **Run anyway**. The `.zip` below holds the same executable plus the licences.

## Other platforms

```
pip install "svgseg[gui]"
svgseg-gui
```

with potrace from your package manager (`apt install potrace`,
`brew install potrace`).

## Licences

svgseg is GPL-3.0-or-later. The executable contains potrace @POTRACE_VERSION@ by
Peter Selinger, which is GPL-2.0-or-later, so its complete unmodified source is
attached here as `potrace-@POTRACE_VERSION@.tar.gz` and its licence ships inside
the zip under `potrace/`. See `THIRD-PARTY.md` in the zip for everything else
that is bundled.
