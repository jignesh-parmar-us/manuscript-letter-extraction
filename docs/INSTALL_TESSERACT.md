# Installing Tesseract OCR

Phase 2 uses **Tesseract**, a free, offline OCR engine, to suggest labels for groups of **printed** Devanagari letters (see `docs/implementation_plan_phase2.md`, C10 to C12). The app calls the `tesseract` program directly, so no Python package is needed. Everything runs on your computer: no page is sent anywhere.

You need:
- **Tesseract 5.x** (4.1 works, but 5 is tested);
- the **language models** `hin` (Hindi), `san` (Sanskrit) and `mar` (Marathi), plus the script model `script/Devanagari`.

---

## macOS

Which way to install depends on the processor (Apple menu → **About This Mac**):
- **Intel Mac** (this one: Intel Core i5): use **MacPorts** (section A). Recent Homebrew versions no longer support Intel Macs. The Homebrew installer stops with *"Homebrew on macOS is only supported on Apple Silicon processors!"*
- **Apple Silicon Mac** (M1 or later): use **Homebrew** (section B).

### A. Intel Mac: MacPorts

MacPorts needs the **Xcode Command Line Tools**. This Mac already has them. On another Mac, run `xcode-select --install` first.

1. Download the MacPorts installer for **macOS 15 Sequoia** from https://www.macports.org/install.php. Choose the `.pkg` file for your macOS version (Apple menu → About This Mac).
2. Open the `.pkg` and follow the steps. It asks for your Mac password.
3. **Close Terminal and open a new window.** The installer adds `/opt/local/bin` to the PATH, but only new windows see it. Check it:
   ```sh
   port version
   ```
4. Install Tesseract with the Hindi, Sanskrit and Marathi models (this takes a few minutes):
   ```sh
   sudo port selfupdate
   sudo port install tesseract tesseract-hin tesseract-san tesseract-mar
   ```
5. Add the script model `script/Devanagari`. You can also replace the three language models with the more accurate "best" versions (about 60 MB):
   ```sh
   TESSDATA=/opt/local/share/tessdata
   for lang in hin san mar; do
     sudo curl -fL -o "$TESSDATA/$lang.traineddata" \
       "https://github.com/tesseract-ocr/tessdata_best/raw/main/$lang.traineddata"
   done
   sudo mkdir -p "$TESSDATA/script"
   sudo curl -fL -o "$TESSDATA/script/Devanagari.traineddata" \
     "https://github.com/tesseract-ocr/tessdata_best/raw/main/script/Devanagari.traineddata"
   ```
   If `tesseract --list-langs` (step C) shows another folder, use that folder instead of `/opt/local/share/tessdata`.

Updating later:
```sh
sudo port selfupdate && sudo port upgrade outdated
```
An upgrade may put back the default models. If it does, run step 5 again.

### B. Apple Silicon Mac: Homebrew

1. Open **Terminal** (Applications → Utilities → Terminal).
2. Install Homebrew. Paste this line and press Return:
   ```sh
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
   It asks for your Mac password (nothing shows while you type it).
3. At the end, Homebrew prints **"Next steps"**. Run them:
   ```sh
   echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
   eval "$(/opt/homebrew/bin/brew shellenv)"
   ```
4. Install Tesseract:
   ```sh
   brew install tesseract
   ```
5. This installs Tesseract with English only. Add only the models we need, in the more accurate "best" version (about 60 MB):
   ```sh
   TESSDATA="$(brew --prefix)/share/tessdata"
   for lang in hin san mar; do
     curl -fL -o "$TESSDATA/$lang.traineddata" \
       "https://github.com/tesseract-ocr/tessdata_best/raw/main/$lang.traineddata"
   done
   mkdir -p "$TESSDATA/script"
   curl -fL -o "$TESSDATA/script/Devanagari.traineddata" \
     "https://github.com/tesseract-ocr/tessdata_best/raw/main/script/Devanagari.traineddata"
   ```
   (Or `brew install tesseract-lang` for all languages, about 650 MB.)

Updating later: `brew upgrade tesseract`. If an upgrade removes the models, run step 5 again.

The "best" models are slower but more accurate than the default ones. A page of printed text still takes only a few seconds.

### C. Check the installation

```sh
tesseract --version
tesseract --list-langs
```

`--list-langs` must list `hin`, `san` and `mar` (and `script/Devanagari`).

Then read one of the printed sample pages. Run this in the project folder:
```sh
tesseract samples/blackandwhite/Untitled-15.jpg - -l san+hin --psm 6
```

Devanagari text should appear in the Terminal. A few errors are normal at this stage. If the text looks right, Tesseract is ready.

---

## Windows (for the team)

1. Download the installer from the **UB Mannheim** builds, which the Tesseract project itself links to: https://github.com/UB-Mannheim/tesseract/wiki (choose the 64-bit `tesseract-ocr-w64-setup-5.x.x.exe`).
2. Run it. On the **"Choose Components"** page, open **Additional language data** and tick **Hindi**, **Sanskrit** and **Marathi**. Under **Additional script data**, tick **Devanagari**.
3. Keep the default folder `C:\Program Files\Tesseract-OCR`. The app looks for Tesseract there even when it is not on the PATH.
4. To use it from the command line, add `C:\Program Files\Tesseract-OCR` to the **PATH**: Start → "Edit the system environment variables" → Environment Variables → Path → Edit → New.
5. Check it in a **new** Command Prompt:
   ```bat
   tesseract --version
   tesseract --list-langs
   ```

To use the "best" models on Windows, download the same `.traineddata` files as in macOS Option 2. Save them in `C:\Program Files\Tesseract-OCR\tessdata\` (replacing the existing files).

---

## How the app finds Tesseract

In this order:
1. the path set in the app's settings (**Settings → Tesseract program**), if any;
2. `tesseract` on the PATH;
3. the usual install folders:
   - `/usr/local/bin` (older Homebrew installs on Intel)
   - `/opt/homebrew/bin` (Homebrew on Apple Silicon)
   - `/opt/local/bin` (MacPorts)
   - `C:\Program Files\Tesseract-OCR`

If it is not found, the "Suggest labels" button explains what is missing and links to this file. The rest of the app works without Tesseract.

## Training Tesseract on a book's checked lines (C30, macOS)

Only for trying Tesseract fine-tuned on a book's checked lines (`docs/implementation_plan_phase3_later.md`, C30).
Reading does not need it. The MacPorts port has no training programs, so a script builds them from source
**at the same version** as the installed `tesseract`, into a folder of their own (default `~/tesstrain`), with no
`sudo`. CMake and pkgconf come from PyPI into `~/tesstrain/venv`. It also downloads the float start model
`tessdata_best/script/Devanagari` (the installed models cannot be fine-tuned) and the langdata files training needs.
The build takes about 15 minutes.

```zsh
tools/tesstrain/setup.sh                 # or: tools/tesstrain/setup.sh <folder>
```

Then, on a **copy** of the library (`tools/harness/copy_library.sh ~/harness/libcopy`):

```zsh
PYTHONPATH=src .venv/bin/python tools/tesstrain/export.py --library ~/harness/libcopy --book 8 --out ~/tesstrain/book8
for k in 0 1 2 3; do
  PYTHONPATH=src .venv/bin/python tools/tesstrain/train.py --data ~/tesstrain/book8 --fold $k
done
PYTHONPATH=src .venv/bin/python tools/tesstrain/score.py --library ~/harness/libcopy --book 8 --data ~/tesstrain/book8
```

`export.py` writes the checked lines as training pairs in Measure's four folds. `train.py` trains one model per
fold, without that fold's pages. `score.py` reads each fold's lines with the installed model and with the fold's
model, the same way the Whole lines route does. It prints the characters wrong and writes `score.html`, which lists
every line. Training and scoring are heavy jobs: they take the heavy-job lock (`docs/SPEED_PLAN.md`, S1).
To remove everything: delete `~/tesstrain`.

## Troubleshooting

| Problem | Fix |
|---|---|
| *"Homebrew on macOS is only supported on Apple Silicon processors!"* | This is an Intel Mac. Use MacPorts (section A). |
| `command not found: port` or `brew` | Open a new Terminal window. For Homebrew, run the "Next steps" from step B.3 first. |
| `command not found: tesseract` | Open a new Terminal window. Check with `ls /opt/local/bin/tesseract` (MacPorts) or `ls /opt/homebrew/bin/tesseract` (Homebrew). |
| `Failed loading language 'san'` | The model is missing. Run step A.5 or B.5 again, and check that `tesseract --list-langs` shows it. |
| `curl: (22) ... 404` while downloading a model | The file name is case sensitive: `script/Devanagari.traineddata` has a capital D. |
| Wrong letters on old typefaces | Expected for unusual letter forms. Try `-l san`, `-l hin`, `-l script/Devanagari` and compare. C10 measures which works best on our pages. |
