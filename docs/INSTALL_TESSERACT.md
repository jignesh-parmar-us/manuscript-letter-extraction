# Installing Tesseract OCR

Phase 2 uses **Tesseract**, a free, offline OCR engine, to suggest labels for groups of **printed** Devanagari letters (see `docs/implementation_plan_phase2.md`, C10 to C12). The app calls the `tesseract` program directly, so no Python package is needed. Everything runs on your computer: no page is sent anywhere.

You need:
- **Tesseract 5.x** (4.1 works, but 5 is tested);
- the **language models** `hin` (Hindi), `san` (Sanskrit) and `mar` (Marathi), plus the script model `script/Devanagari`.

---

## macOS

This Mac has no Homebrew yet. Homebrew is the usual way to install command-line tools on macOS, and it makes updates easy. Steps A and B take about 10 to 15 minutes.

### A. Install Homebrew (once)

1. Open **Terminal** (Applications → Utilities → Terminal).
2. Paste this line and press Return:
   ```sh
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
   It asks for your Mac password (nothing shows while you type it). It may also install the **Xcode Command Line Tools**; accept that.
3. At the end, Homebrew prints **"Next steps"**. Run the commands it shows there. On an **Intel Mac** (this one) Homebrew lives in `/usr/local` and usually needs nothing more. On an **Apple Silicon Mac** (M1 to M4) it lives in `/opt/homebrew`, and the next steps are:
   ```sh
   echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
   eval "$(/opt/homebrew/bin/brew shellenv)"
   ```
4. Check it:
   ```sh
   brew --version
   ```

### B. Install Tesseract and the Devanagari models

```sh
brew install tesseract
```

This installs Tesseract with English only. Choose **one** way to add the Devanagari models:

**Option 1: all languages (simplest, about 650 MB):**
```sh
brew install tesseract-lang
```

**Option 2: only the models we need, in the more accurate "best" version (about 60 MB, recommended):**
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

### Updating later

```sh
brew upgrade tesseract
```

The models you downloaded in Option 2 stay where they are. If an upgrade removes them, run the Option 2 commands again.

### Without Homebrew (alternative)

If you would rather not install Homebrew, **MacPorts** works too. Install MacPorts from https://www.macports.org/install.php (pick your macOS version), then run:
```sh
sudo port install tesseract tesseract-hin tesseract-san tesseract-mar
```

Then check it as in step C.

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
   - `/usr/local/bin` (Homebrew on Intel)
   - `/opt/homebrew/bin` (Homebrew on Apple Silicon)
   - `/opt/local/bin` (MacPorts)
   - `C:\Program Files\Tesseract-OCR`

If it is not found, the "Suggest labels" button explains what is missing and links to this file. The rest of the app works without Tesseract.

## Troubleshooting

| Problem | Fix |
|---|---|
| `command not found: brew` after installing Homebrew | Run the "Next steps" commands from step A.3, then open a new Terminal window. |
| `command not found: tesseract` | Open a new Terminal window. Check with `ls "$(brew --prefix)/bin/tesseract"`. |
| `Failed loading language 'san'` | The model is missing. Run step B again, and check that `tesseract --list-langs` shows it. |
| `curl: (22) ... 404` while downloading a model | The file name is case sensitive: `script/Devanagari.traineddata` has a capital D. |
| Wrong letters on old typefaces | Expected for unusual letter forms. Try `-l san`, `-l hin`, `-l script/Devanagari` and compare. C10 measures which works best on our pages. |
