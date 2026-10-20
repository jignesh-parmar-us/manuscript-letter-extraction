#!/bin/zsh
# C30a: Tesseract's training programs, built once into a folder of their own (default ~/tesstrain), no sudo.
#
#   tools/tesstrain/setup.sh [folder]
#
# Builds Tesseract from source at the SAME version as the installed `tesseract` (MacPorts), with its training
# programs (lstmtraining, combine_tessdata, unicharset_extractor, merge_unicharsets, combine_lang_model; text2image
# only if Pango is installed), against MacPorts' Leptonica and ICU. CMake and pkgconf come from PyPI into
# <folder>/venv. Also fetches the float start model tessdata_best/script/Devanagari and the langdata files
# combine_lang_model needs. The app's own Tesseract is not touched. About 15 minutes (the build); run it again
# to rebuild after a Tesseract upgrade. docs/INSTALL_TESSERACT.md, "Training Tesseract".
set -euo pipefail
DEST=${1:-$HOME/tesstrain}
PY=${PYTHON:-python3}
VER=$(tesseract --version 2>&1 | head -1 | awk '{print $2}')
[[ -n $VER ]] || { echo "No tesseract on the PATH (docs/INSTALL_TESSERACT.md)."; exit 1; }
echo "Tesseract $VER -> $DEST"
mkdir -p $DEST/src $DEST/tessdata/configs $DEST/langdata

# 1. CMake and pkgconf (no MacPorts packages needed beyond leptonica and icu, which tesseract already uses)
[[ -x $DEST/venv/bin/cmake ]] || { $PY -m venv $DEST/venv && $DEST/venv/bin/pip install -q cmake pkgconf; }

# 2. the source at the installed version, built with the training programs
SRC=$DEST/src/tesseract-$VER
if [[ ! -d $SRC ]]; then
  curl -fsSL "https://github.com/tesseract-ocr/tesseract/archive/refs/tags/$VER.tar.gz" | tar -xz -C $DEST/src
fi
export PKG_CONFIG_PATH=/opt/local/lib/pkgconfig:/opt/homebrew/lib/pkgconfig:/usr/local/lib/pkgconfig
# without Pango, skip text2image (CMake would otherwise stop: it requires Pango whenever pkg-config is found)
if ! $DEST/venv/bin/pkgconf --exists pango; then
  perl -0pi -e 's/if\(PKG_CONFIG_FOUND\)(\s*pkg_check_modules\(\s*PANGO)/if(PKG_CONFIG_FOUND AND NOT NO_PANGO)$1/' \
    $SRC/src/training/CMakeLists.txt
  echo "(no Pango: text2image is not built)"
fi
$DEST/venv/bin/cmake -S $SRC -B $DEST/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=$DEST \
  -DBUILD_TRAINING_TOOLS=ON -DBUILD_TESTS=OFF -DDISABLE_CURL=ON -DDISABLE_ARCHIVE=ON -DGRAPHICS_DISABLED=ON \
  -DOPENMP_BUILD=OFF -DENABLE_NATIVE=OFF -DNO_PANGO=ON -DPKG_CONFIG_EXECUTABLE=$DEST/venv/bin/pkgconf \
  -DCMAKE_PREFIX_PATH="/opt/local;/opt/homebrew;/usr/local" -DICU_ROOT=/opt/local
nice -n 10 $DEST/venv/bin/cmake --build $DEST/build -j 4
$DEST/venv/bin/cmake --install $DEST/build

# 3. the start model (float, tessdata_best) beside the configs that `lstm.train` needs
cp $SRC/tessdata/configs/* $DEST/tessdata/configs/
[[ -s $DEST/tessdata/Devanagari.traineddata ]] || curl -fsSL -o $DEST/tessdata/Devanagari.traineddata \
  "https://github.com/tesseract-ocr/tessdata_best/raw/main/script/Devanagari.traineddata"

# 4. langdata for combine_lang_model
for f in radical-stroke.txt Devanagari.unicharset Gujarati.unicharset Latin.unicharset; do
  [[ -s $DEST/langdata/$f ]] || curl -fsSL -o $DEST/langdata/$f \
    "https://github.com/tesseract-ocr/langdata_lstm/raw/main/$f" || echo "($f not found, skipped)"
done

for p in tesseract lstmtraining combine_tessdata unicharset_extractor merge_unicharsets combine_lang_model; do
  [[ -x $DEST/bin/$p ]] || { echo "Missing $DEST/bin/$p: the build failed."; exit 1; }
done
echo "Done: $DEST/bin has the training programs; start model $DEST/tessdata/Devanagari.traineddata."
